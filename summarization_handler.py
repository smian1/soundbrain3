import emoji
from datetime import datetime, timedelta
import pytz
from models import db, temp_segments, Segment, summaries, User
from summarization import generate_summary
import traceback
from sqlalchemy import func
import logging
import os
import requests
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

def increment_processing_attempts(session, segments):
    for seg in segments:
        seg.processing_attempts += 1
        session.add(seg)
    session.flush()

def remove_exceeded_attempts_segments(session, segments, max_attempts=3):
    segments_to_remove = [seg for seg in segments if seg.processing_attempts >= max_attempts]
    if segments_to_remove:
        segment_ids_to_remove = [seg.segment_id for seg in segments_to_remove]
        delete_result = session.query(temp_segments).filter(
            temp_segments.segment_id.in_(segment_ids_to_remove)
        ).delete(synchronize_session=False)
        logger.info(f"Removed {delete_result} segments after exceeding max attempts")

def process_segments_for_summary(user_id, start_time, end_time):
    logger.info(f"Processing segments for User {user_id} from {start_time} to {end_time}")
    Session = sessionmaker(bind=db.engine)
    session = Session()
    try:
        segments_to_process = session.query(temp_segments).filter(
            temp_segments.user_id == user_id,
            temp_segments.processed_at.is_(None),
            temp_segments.timestamp >= start_time,
            temp_segments.timestamp < end_time
        ).order_by(temp_segments.timestamp.asc()).all()

        logger.info(f"Found {len(segments_to_process)} segments to process for User {user_id}")

        if not segments_to_process:
            logger.info(f"No segments to process for User {user_id} in the given time range")
            return "no_segments", None

        total_text = " ".join([seg.text for seg in segments_to_process])

        if len(total_text.strip()) < 50:
            logger.info(f"Text too short for summarization: {total_text}")
            return "insufficient_context", None

        logger.info(f"Generating summary for User {user_id}")
        summary = generate_summary(total_text, session, user_id, segments_to_process[0].timestamp)

        if summary:
            logger.info(f"Summary generated for User {user_id}. Creating database entry.")
            new_summary = summaries(
                user_id=user_id,
                headline=summary.headline,
                bullet_points=summary.bullet_points,
                tag=summary.tag,
                fact_checker=summary.fact_checker,
                timestamp=segments_to_process[0].timestamp,
                created_at=datetime.utcnow()
            )
            session.add(new_summary)
            session.flush()
            logger.info(f"New summary added with ID: {new_summary.id}")

            segment_ids = [seg.segment_id for seg in segments_to_process]
            update_result = session.query(Segment).filter(Segment.id.in_(segment_ids)).update({
                Segment.processed: True,
                Segment.summary_id: new_summary.id
            }, synchronize_session=False)
            logger.info(f"Updated {update_result} Segment records")

            delete_result = session.query(temp_segments).filter(temp_segments.segment_id.in_(segment_ids)).delete(synchronize_session=False)
            logger.info(f"Deleted {delete_result} temp_segments records")

            logger.info("Committing changes to database")
            session.commit()
            logger.info(f"Successfully created summary for User {user_id}")

            user = session.query(User).get(user_id)
            if user and user.email:
                reflect_success = send_to_reflect(new_summary, user.email)
                if reflect_success:
                    logger.info(f"Sent summary to Reflect for User {user_id}")
                else:
                    logger.warning(f"Failed to send summary to Reflect for User {user_id}")
            else:
                logger.warning(f"User email not found for User {user_id}, skipping Reflect update")
            
            return "success", new_summary.id
        else:
            logger.info(f"No summary generated for User {user_id}")
            return "insufficient_context", None

    except Exception as e:
        logger.error(f"Error during summary creation for User {user_id}: {str(e)}")
        logger.error(traceback.format_exc())
        session.rollback()
        return "error", None
    finally:
        session.close()

def send_to_reflect(summary, email):
    logger.info("Attempting to send summary to Reflect")
    try:
        # Get user's timezone setting
        user = User.query.filter_by(email=email).first()
        user_timezone = pytz.timezone(user.timezone or 'America/Los_Angeles')
        
        # Format the summary with user's local time
        local_time = datetime.now(pytz.timezone('UTC')).astimezone(user_timezone)
        timestamp = local_time.strftime("%I:%M %p")
        formatted_summary = f"### {timestamp} - **{summary.headline}** #{summary.tag}\n\n"
        
        # Handle bullet points whether they're a list or a string
        if isinstance(summary.bullet_points, list):
            formatted_summary += "\n".join(f"- {point}" for point in summary.bullet_points)
        else:
            formatted_summary += "\n".join(f"- {point}" for point in summary.bullet_points.split('\n'))

        # Add fact-checker information if available
        if summary.fact_checker and isinstance(summary.fact_checker, list):
            formatted_summary += "\n    - ❗**Fact Checker**\n"
            formatted_summary += "\n".join(f"      - {fact}" for fact in summary.fact_checker)
        elif summary.fact_checker:
            formatted_summary += "\n    - ❗**Fact Checker**\n"
            formatted_summary += f"      - {summary.fact_checker}"

        # Prepare API request
        graph_id = os.getenv('REFLECT_GRAPH_ID')
        access_token = os.getenv('REFLECT_ACCESS_TOKEN')
        
        if not graph_id or not access_token:
            logger.error("Reflect API credentials are not set. Please set REFLECT_GRAPH_ID and REFLECT_ACCESS_TOKEN in Replit Secrets.")
            return False

        reflect_api_url = f'https://reflect.app/api/graphs/{graph_id}/daily-notes'
        headers = {
            "Authorization": f"Bearer {access_token}",
        }
        data = {
            "date": local_time.strftime('%Y-%m-%d'),
            "text": formatted_summary,
            "transform_type": "list-append",
            "list_name": "Updates",
        }
        
        # Send request to Reflect API
        response = requests.put(reflect_api_url, headers=headers, json=data)
        response.raise_for_status()
        logger.info(f"Reflect API response status code: {response.status_code}")
        return True
    except requests.RequestException as e:
        logger.error(f"Error calling Reflect API: {str(e)}")
        if hasattr(e, 'response'):
            logger.error(f"Response status code: {e.response.status_code}")
            logger.error(f"Response content: {e.response.text}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error in send_to_reflect: {str(e)}")
        return False

def cleanup_locked_segments():
    logger.info("Starting cleanup of locked segments")
    with db.session() as session:
        try:
            lock_expiry = datetime.utcnow() - timedelta(minutes=30)
            updated = session.query(temp_segments).filter(
                temp_segments.locked == True,
                temp_segments.lock_timestamp < lock_expiry
            ).update({
                'locked': False,
                'lock_timestamp': None
            }, synchronize_session=False)
            session.commit()
            logger.info(f"Cleaned up {updated} old locked segments")
        except Exception as e:
            logger.error(f"Error cleaning up locked segments: {str(e)}")
            logger.error(traceback.format_exc())
            session.rollback()

def process_user_segments_in_chunks(user_id, chunk_size_minutes=10, max_attempts=3):
    Session = sessionmaker(bind=db.engine)
    with Session() as session:
        try:
            earliest_segment = session.query(temp_segments).filter(
                temp_segments.user_id == user_id,
                temp_segments.processed_at.is_(None)
            ).order_by(temp_segments.timestamp.asc()).first()

            if not earliest_segment:
                logger.info(f"No unprocessed segments for User {user_id}")
                return

            current_start = earliest_segment.timestamp
            while True:
                current_end = current_start + timedelta(minutes=chunk_size_minutes)
                
                status, summary_id = process_segments_for_summary(user_id, current_start, current_end)
                
                if status in ["insufficient_context", "no_segments", "error"]:
                    # Increment processing attempts for these segments
                    segments_to_update = session.query(temp_segments).filter(
                        temp_segments.user_id == user_id,
                        temp_segments.timestamp >= current_start,
                        temp_segments.timestamp < current_end
                    ).all()
                    
                    for segment in segments_to_update:
                        segment.processing_attempts += 1
                        if segment.processing_attempts >= max_attempts:
                            session.delete(segment)
                        else:
                            session.add(segment)
                    
                    session.commit()
                    logger.info(f"Incremented processing attempts for segments of User {user_id} from {current_start} to {current_end}")
                
                # Move to the next chunk
                current_start = current_end
                
                # Check if there are more segments to process
                next_segment = session.query(temp_segments).filter(
                    temp_segments.user_id == user_id,
                    temp_segments.timestamp >= current_end,
                    temp_segments.processed_at.is_(None)
                ).first()
                
                if not next_segment:
                    break  # No more segments to process

        except SQLAlchemyError as e:
            logger.error(f"Database error processing segments for User {user_id}: {str(e)}")
            session.rollback()
        except Exception as e:
            logger.error(f"Error processing segments for User {user_id}: {str(e)}")
            logger.error(traceback.format_exc())

def summarization_task():
    logger.info("Starting Summarization Task")
    users = User.query.all()

    for user in users:
        process_user_segments_in_chunks(user.id)

    logger.info("Finished Summarization Task")
