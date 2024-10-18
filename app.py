import sys

#import eventlet
#eventlet.monkey_patch()

import warnings
warnings.filterwarnings("ignore", message="Can not find any timezone configuration")

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, abort, Response, stream_with_context
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO
from authlib.integrations.flask_client import OAuth
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, text
from models import db, Main, Segment, User, temp_segments, summaries
from config import Config
import logging
from datetime import datetime, timedelta
import traceback
import pytz
import nltk
import os
import requests
import json
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from google.auth.transport import requests as google_requests
import sys
from secrets import token_urlsafe
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from collections import Counter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_, or_
import emoji
import time
from pytz import timezone as pytz_timezone
from summarization_handler import summarization_task, cleanup_locked_segments
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit
from sqlalchemy.orm import sessionmaker

# Add these lines near the top of the file, after the imports
nltk.download('punkt')
nltk.download('stopwords')
nltk.download('averaged_perceptron_tagger')
nltk.download('maxent_ne_chunker')
nltk.download('words')

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Reduce logging noise from other libraries
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)

# Initialize Flask app
try:
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['TIMEZONE'] = pytz.timezone('UTC')
    db.init_app(app)
    socketio = SocketIO(app)
    # ... rest of your initialization code ...
except Exception as e:
    logger.error(f"Error during app initialization: {e}", exc_info=True)
    raise

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize OAuth
oauth = OAuth(app)

# OAuth configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    logger.error("Google OAuth credentials are not set. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.")
    sys.exit(1)

redirect_uri = "https://soundbrain-2dce81400d7f.herokuapp.com/login/google/authorized"

google = oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
    redirect_uri=redirect_uri
)

# Create client_secrets.json file
client_secrets = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "project_id": os.getenv("GOOGLE_PROJECT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "redirect_uris": [
            "https://soundbrain-2dce81400d7f.herokuapp.com/login/google/authorized"
        ]
    }
}

with open('client_secrets.json', 'w') as f:
    json.dump(client_secrets, f)

# Update the flow configuration
flow = Flow.from_client_secrets_file(
    'client_secrets.json',
    scopes=["https://www.googleapis.com/auth/userinfo.profile", "https://www.googleapis.com/auth/userinfo.email", "openid"],
    redirect_uri="https://soundbrain-2dce81400d7f.herokuapp.com/login/google/authorized"
)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Initialize the scheduler
scheduler = BackgroundScheduler()

def init_scheduler():
    if scheduler.running:
        return

    scheduler.start()

    def summarization_task_wrapper():
        with app.app_context():
            Session = sessionmaker(bind=db.engine)
            with Session() as session:
                summarization_task()

    def cleanup_locked_segments_wrapper():
        with app.app_context():
            cleanup_locked_segments()

    scheduler.add_job(
        func=summarization_task_wrapper,
        trigger=IntervalTrigger(minutes=5),
        id='summarization_job',
        name='Generate summaries every 5 minutes',
        replace_existing=True)

    scheduler.add_job(
        func=cleanup_locked_segments_wrapper,
        trigger=IntervalTrigger(minutes=15),
        id='cleanup_locked_segments_job',
        name='Cleanup locked segments every 15 minutes',
        replace_existing=True)

    atexit.register(lambda: scheduler.shutdown())

# Initialize scheduler
init_scheduler()

@app.route('/scheduler_status')
@login_required
def scheduler_status():
    if not current_user.is_admin:
        abort(403)  # Forbidden for non-admin users
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'name': job.name,
            'next_run_time': str(job.next_run_time),
            'trigger': str(job.trigger)
        })
    
    return jsonify({
        'running': scheduler.running,
        'jobs': jobs
    })

# Route handlers for various endpoints

@app.route('/')
def index():
    """Render the landing page."""
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        logger.debug(f"Login attempt for username: {username}")
        try:
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_user(user)
                logger.info(f"User {username} logged in successfully")
                if not user.uid:
                    return redirect(url_for('set_uid'))
                return redirect(url_for('admin'))
            else:
                logger.warning(f"Invalid login attempt for {username}")
                flash('Invalid username or password', 'error')
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            logger.error(traceback.format_exc())
            flash('An error occurred during login. Please try again later.', 'error')
        return redirect(url_for('index'))
    
    # For GET requests, just render the landing page
    return render_template('login.html')

@app.route('/login/google')
def login_google():
    """Initiate the Google OAuth flow."""
    # Generate and store nonce
    nonce = token_urlsafe(32)
    session['google_auth_nonce'] = nonce
    
    return google.authorize_redirect(redirect_uri=redirect_uri, nonce=nonce)

@app.route('/login/google/authorized')
def google_authorized():
    logger.debug(f"Received callback at: {request.url}")
    try:
        token = google.authorize_access_token()
        nonce = session.pop('google_auth_nonce', None)
        if not nonce:
            raise ValueError("Missing nonce in session")
        
        userinfo = google.parse_id_token(token, nonce=nonce)
        email = userinfo['email']

        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                username=email,
                email=email,
                first_name=userinfo.get('given_name'),
                last_name=userinfo.get('family_name'),
                profile_picture=userinfo.get('picture')
            )
            db.session.add(user)
            db.session.commit()

        login_user(user)

        session['email'] = email
        session['first_name'] = user.first_name
        session['last_name'] = user.last_name
        session['profile_picture'] = user.profile_picture
        session['uid'] = user.uid
        session['timezone'] = user.timezone

        if not user.uid:
            return redirect(url_for('set_uid'))
        return redirect(url_for('admin'))
    except Exception as e:
        logger.error(f"Error during Google login: {str(e)}")
        logger.error(traceback.format_exc())
        db.session.rollback()  # Add this line to rollback the session in case of error
        session.clear()
        return redirect(url_for('login', error="An error occurred during login. Please try again."))

@app.route('/set_uid', methods=['GET', 'POST'])
@login_required
def set_uid():
    if current_user.uid:
        return redirect(url_for('admin'))
    
    if request.method == 'POST':
        uid = request.form.get('uid')
        if uid:
            current_user.uid = uid
            db.session.commit()
            logger.info(f"UID set for user {current_user.username}: {uid}")
            return redirect(url_for('admin'))
    return render_template('set_uid.html')

@app.route('/logout')
@login_required
def logout():
    """Log out the current user and redirect to the landing page."""
    logout_user()
    session.clear()  # Clear all session data
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/admin')
@app.route('/admin2')
@login_required
def admin():
    if not current_user.uid:
        return redirect(url_for('set_uid'))
    segments = []
    logger.debug(f"Segments in admin route: {segments}")
    
    # Determine which template to use based on the route
    template = 'admin2.html' if request.path == '/admin2' else 'admin.html'
    
    return render_template(template, 
                           segments=segments, 
                           user_uid=current_user.uid,
                           username=current_user.username,
                           email=current_user.email,
                           first_name=current_user.first_name,
                           last_name=current_user.last_name,
                           profile_picture=current_user.profile_picture,
                           timezone=current_user.timezone)

@app.route('/get_transcripts', methods=['GET'])
@login_required
def get_transcripts():
    date_str = request.args.get('date')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 200))
    hour = request.args.get('hour')

    if not date_str or date_str == 'Invalid Date':
        return jsonify({'error': 'Invalid or missing date parameter'}), 400
    
    try:
        pacific_tz = pytz.timezone('US/Pacific')
        selected_date = datetime.strptime(date_str, '%Y-%m-%d')
        selected_date = pacific_tz.localize(selected_date)
        
        utc_start = selected_date.astimezone(pytz.UTC)
        utc_end = (selected_date + timedelta(days=1)).astimezone(pytz.UTC)

        query = db.session.query(Segment).join(Main).filter(
            Main.uid == current_user.uid,
            Segment.timestamp >= utc_start,
            Segment.timestamp < utc_end
        )

        if hour is not None:
            hour = int(hour)
            hour_start = utc_start + timedelta(hours=hour)
            hour_end = hour_start + timedelta(hours=1)
            query = query.filter(
                Segment.timestamp >= hour_start,
                Segment.timestamp < hour_end
            )

        query = query.order_by(Segment.timestamp.asc())

        total_segments = query.count()
        total_pages = (total_segments + per_page - 1) // per_page

        segments = query.offset((page - 1) * per_page).limit(per_page).all()
        
        if not segments:
            return jsonify({
                'segments': [],
                'timezone': 'US/Pacific',
                'total_pages': 0,
                'current_page': 1
            }), 200
    
        serialized_segments = [segment.to_dict() for segment in segments]
    
        return jsonify({
            'segments': serialized_segments,
            'timezone': 'US/Pacific',
            'total_pages': total_pages,
            'current_page': page
        }), 200
    except Exception as e:
        logger.error(f"Error fetching transcripts: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/webhook', methods=['GET'])
def webhook_get():
    """Respond to GET requests to the webhook endpoint."""
    return jsonify({'message': 'Webhook is active. Please use POST method to submit data.'}), 200

@app.route('/webhook', methods=['POST'])
def webhook_post():
    try:
        # Extract UID from query parameter
        uid = request.args.get('uid')
        if not uid:
            logger.error('Missing UID parameter')
            return jsonify({'error': 'Missing UID parameter'}), 400

        # Parse JSON payload
        payload = request.json
        if not payload:
            logger.error('Invalid JSON payload')
            return jsonify({'error': 'Invalid JSON payload'}), 400

        # Extract required fields from payload
        session_id = payload.get('session_id')
        if not session_id:
            logger.error('Missing session_id in payload')
            return jsonify({'error': 'Missing session_id in payload'}), 400

        logger.debug(f"Received payload: {payload}")

        # Forward the webhook data to the specified URL
        #forward_url = f"https://friend-chat-79fbdb3555bc.herokuapp.com/webhook?uid={uid}"
        #try:
        #    forward_response = requests.post(forward_url, json=payload)
        #    forward_response.raise_for_status()
        #    logger.info(f"Successfully forwarded webhook data to {forward_url}")
        #except requests.RequestException as e:
        #    logger.error(f"Error forwarding webhook data: {str(e)}")
            # Note: Continuing execution even if forwarding fails

        # Create main entry in the database
        main_entry = Main(
            uid=uid,
            session_id=session_id,
            timestamp=datetime.utcnow(),
            host=request.remote_addr,
            raw_data=payload
        )
        db.session.add(main_entry)
        logger.debug("Added main entry to session")

        try:
            db.session.flush()  # Flush to get the main_entry.id
            logger.debug(f"Flushed main entry, got id: {main_entry.id}")
        except Exception as flush_error:
            logger.error(f"Error during flush: {str(flush_error)}")
            logger.error(traceback.format_exc())
            raise

        # Create segment entries and accumulate segments
        segments = payload.get('segments', [])
        for segment in segments:
            segment_entry = Segment(
                main_id=main_entry.id,
                text=segment.get('text'),
                speaker=segment.get('speaker'),
                speaker_id=segment.get('speaker_id'),
                is_user=segment.get('is_user'),
                start_time=segment.get('start_time'),
                end_time=segment.get('end_time'),
                timestamp=datetime.utcnow(),
                summary_id=None  # Initialize summary_id as None
            )
            db.session.add(segment_entry)
            db.session.flush()  # This will assign an ID to segment_entry
            logger.debug(f"Added segment entry: {segment_entry}")

            # Emit new segment to all connected clients via WebSocket
            socketio.emit('new_segment', segment_entry.to_dict())

            # Accumulate segment for summarization
            accumulate_segment(uid, session_id, segment, segment_entry.id)

        # Commit the transaction
        try:
            db.session.commit()
            #logger.info(f"Webhook data processed successfully for UID: {uid}")
            return jsonify({'message': 'Data processed successfully'}), 200
        except Exception as commit_error:
            logger.error(f"Error during commit: {str(commit_error)}")
            logger.error(traceback.format_exc())
            db.session.rollback()
            return jsonify({'error': 'Error processing data'}), 500

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing webhook data: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/generate_hash/<password>')
def generate_hash(password):
    """
    Generate a hash for a given password.
    Useful for creating new user passwords.
    """
    return generate_password_hash(password)

@app.route('/health')
def health_check():
    """
    Perform a health check on the application and database connection.
    Returns a JSON response indicating the health status.
    """
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'healthy', 'database': 'connected'}), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({'status': 'unhealthy', 'database': 'disconnected', 'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """
    Handle WebSocket connection attempts.
    Reject the connection if the user is not authenticated.
    """
    if not current_user.is_authenticated:
        return False  # Reject the connection

@app.route('/get_heatmap_data')
@login_required
def get_heatmap_data():
    date_str = request.args.get('date')
    
    if not date_str:
        return jsonify({'error': 'Missing date parameter'}), 400
    
    try:
        pacific_tz = pytz.timezone('US/Pacific')
        selected_date = datetime.strptime(date_str, '%Y-%m-%d')
        selected_date = pacific_tz.localize(selected_date)
        
        utc_start = selected_date.astimezone(pytz.UTC)
        utc_end = (selected_date + timedelta(days=1)).astimezone(pytz.UTC)

        hourly_counts = db.session.query(
            func.extract('hour', Segment.timestamp).label('hour'),
            func.count(Segment.id).label('count')
        ).join(Main).filter(
            Main.uid == current_user.uid,
            Segment.timestamp >= utc_start,
            Segment.timestamp < utc_end
        ).group_by(
            func.extract('hour', Segment.timestamp)
        ).order_by(
            func.extract('hour', Segment.timestamp)
        ).all()

        heatmap_data = [0] * 24

        for hour, count in hourly_counts:
            utc_time = utc_start.replace(hour=int(hour), minute=0, second=0, microsecond=0)
            pacific_time = utc_time.astimezone(pacific_tz)
            pacific_hour = pacific_time.hour
            heatmap_data[pacific_hour] = count

        return jsonify(heatmap_data), 200

    except Exception as e:
        logger.error(f"Error fetching heatmap data: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/get_word_cloud_data')
@login_required
def get_word_cloud_data():
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'error': 'Missing date parameter'}), 400
    
    try:
        pacific_tz = pytz.timezone('US/Pacific')
        selected_date = datetime.strptime(date_str, '%Y-%m-%d')
        selected_date = pacific_tz.localize(selected_date)
        
        utc_start = selected_date.astimezone(pytz.UTC)
        utc_end = (selected_date + timedelta(days=1)).astimezone(pytz.UTC)

        segments = Segment.query.join(Main).filter(
            Main.uid == current_user.uid,
            Segment.timestamp >= utc_start,
            Segment.timestamp < utc_end
        ).all()

        all_text = ' '.join([segment.text for segment in segments])
        
        # Use a try-except block for word tokenization
        try:
            from nltk.tokenize import word_tokenize
            from nltk.corpus import stopwords
            words = word_tokenize(all_text.lower())
            stop_words = set(stopwords.words('english'))
        except LookupError:
            # If NLTK data is not available, fall back to simple splitting
            words = all_text.lower().split()
            stop_words = set(['i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', "you're", "you've", "you'll", "you'd", 'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', "she's", 'her', 'hers', 'herself', 'it', "it's", 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves', 'what', 'which', 'who', 'whom', 'this', 'that', "that'll", 'these', 'those', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', "don't", 'should', "should've", 'now', 'd', 'll', 'm', 'o', 're', 've', 'y', 'ain', 'aren', "aren't", 'couldn', "couldn't", 'didn', "didn't", 'doesn', "doesn't", 'hadn', "hadn't", 'hasn', "hasn't", 'haven', "haven't", 'isn', "isn't", 'ma', 'mightn', "mightn't", 'mustn', "mustn't", 'needn', "needn't", 'shan', "shan't", 'shouldn', "shouldn't", 'wasn', "wasn't", 'weren', "weren't", 'won', "won't", 'wouldn', "wouldn't"])
        
        # Add custom words to filter out
        custom_stop_words = {'um', 'uh', 'like', 'yeah', 'okay', 'oh', 'just', 'know', 'think', 'going', 'really', 'get', 'well', 'thing', 'things', 'way', 'kind', 'lot'}
        stop_words.update(custom_stop_words)
        
        filtered_words = [word for word in words if word.isalnum() and word not in stop_words and len(word) > 2]
        
        from collections import Counter
        word_freq = Counter(filtered_words)
        
        # Filter out words that appear too frequently (e.g., more than 50% of the time)
        total_words = sum(word_freq.values())
        word_cloud_data = [
            {"text": word, "value": count} 
            for word, count in word_freq.most_common(50) 
            if count < total_words * 0.5
        ]

        return jsonify(word_cloud_data), 200

    except Exception as e:
        logger.error(f"Error fetching word cloud data: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/get_dashboard_stats')
@login_required
def get_dashboard_stats():
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'error': 'Missing date parameter'}), 400
    
    try:
        pacific_tz = pytz.timezone('US/Pacific')
        selected_date = datetime.strptime(date_str, '%Y-%m-%d')
        selected_date = pacific_tz.localize(selected_date)
        
        utc_start = selected_date.astimezone(pytz.UTC)
        utc_end = (selected_date + timedelta(days=1)).astimezone(pytz.UTC)

        total_segments = Segment.query.join(Main).filter(
            Main.uid == current_user.uid,
            Segment.timestamp >= utc_start,
            Segment.timestamp < utc_end
        ).count()

        hourly_counts = db.session.query(
            func.extract('hour', Segment.timestamp).label('hour'),
            func.count(Segment.id).label('count')
        ).join(Main).filter(
            Main.uid == current_user.uid,
            Segment.timestamp >= utc_start,
            Segment.timestamp < utc_end
        ).group_by(
            func.extract('hour', Segment.timestamp)
        ).order_by(
            func.count(Segment.id).desc()
        ).first()

        most_active_hour = None
        if hourly_counts:
            utc_hour = int(hourly_counts[0])
            utc_time = utc_start.replace(hour=utc_hour, minute=0, second=0, microsecond=0)
            pacific_time = utc_time.astimezone(pacific_tz)
            most_active_hour = pacific_time.hour

        return jsonify({
            'total_segments': total_segments,
            'most_active_hour': most_active_hour
        }), 200

    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

def accumulate_segment(uid, session_id, segment_data, segment_id):
    user = User.query.filter_by(uid=uid).first()
    if not user:
        logger.error(f'User not found for UID: {uid}')
        return

    new_segment = temp_segments(
        user_id=user.id,
        segment_id=segment_id,
        speaker=segment_data.get('speaker'),
        text=segment_data.get('text'),
        timestamp=datetime.utcnow(),
        processed_at=None  # Ensure new segments are marked as unprocessed
    )
    db.session.add(new_segment)
    db.session.commit()

@app.route('/get_summaries', methods=['GET'])
@login_required
def get_summaries():
    date_str = request.args.get('date')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 500))
    hour = request.args.get('hour')

    if not date_str:
        date_str = datetime.now(pytz.timezone('US/Pacific')).strftime('%Y-%m-%d')

    try:
        pacific_tz = pytz.timezone('US/Pacific')
        selected_date = datetime.strptime(date_str, '%Y-%m-%d')
        selected_date = pacific_tz.localize(selected_date)
        
        utc_start = selected_date.astimezone(pytz.UTC)
        utc_end = (selected_date + timedelta(days=1)).astimezone(pytz.UTC)

        query = summaries.query.filter(
            summaries.user_id == current_user.id,
            summaries.timestamp >= utc_start,
            summaries.timestamp < utc_end
        )

        if hour is not None:
            hour = int(hour)
            hour_start = utc_start + timedelta(hours=hour)
            hour_end = hour_start + timedelta(hours=1)
            query = query.filter(
                summaries.timestamp >= hour_start,
                summaries.timestamp < hour_end
            )

        query = query.order_by(summaries.timestamp.desc())

        total_summaries = query.count()
        total_pages = (total_summaries + per_page - 1) // per_page

        summaries_list = query.offset((page - 1) * per_page).limit(per_page).all()
        
        serialized_summaries = [{
            'id': summary.id,
            'headline': summary.headline,
            'bullet_points': summary.bullet_points,
            'tag': summary.tag,
            'fact_checker': summary.fact_checker,
            'timestamp': summary.timestamp.isoformat()
        } for summary in summaries_list]
    
        return jsonify({
            'summaries': serialized_summaries,
            'total_pages': total_pages,
            'current_page': page
        }), 200
    except Exception as e:
        logger.error(f"Error fetching summaries: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/get_summary_segments/<int:summary_id>', methods=['GET'])
@login_required
def get_summary_segments(summary_id):
    try:
        summary = summaries.query.get(summary_id)
        if not summary or summary.user_id != current_user.id:
            return jsonify({'error': 'Summary not found or access denied'}), 404
        
        segments = Segment.query.filter_by(summary_id=summary_id).all()
        result = [segment.to_dict() for segment in segments]
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error fetching summary segments: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/get_user_uid')
@login_required
def get_user_uid():
    try:
        logger.debug(f"Fetching UID for user: {current_user.username}")
        return jsonify({'uid': current_user.uid})
    except Exception as e:
        logger.error(f"Error in get_user_uid for user {current_user.username}: {str(e)}")
        return jsonify({'error': 'An error occurred while fetching the UID'}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {str(e)}")
    logger.error(traceback.format_exc())
    return jsonify(error="An unexpected error occurred"), 500

@app.route('/summary_updates')
@login_required
def summary_updates():
    def event_stream():
        last_check = time.time()
        while True:
            # Check for new summaries every 5 seconds
            time.sleep(5)
            new_summaries = check_for_new_summaries(current_user.id, last_check)
            for summary in new_summaries:
                yield f"data: {json.dumps(summary)}\n\n"
            last_check = time.time()

    return Response(stream_with_context(event_stream()), content_type='text/event-stream')

@app.route('/admin/check_backlog', methods=['GET'])
@login_required
def check_backlog():
    # Only allow admin users to access this route
    if not current_user.is_admin:
        abort(403)
    
    # Fetch a few entries from temp_segments
    backlog = temp_segments.query.limit(10).all()
    backlog_data = [{
        'id': seg.id,
        'user_id': seg.user_id,
        'text': seg.text,
        'timestamp': seg.timestamp.isoformat(),
        'processed_at': seg.processed_at.isoformat() if seg.processed_at else None
    } for seg in backlog]
    
    # Fetch the latest summaries
    latest_summaries = summaries.query.order_by(summaries.timestamp.desc()).limit(5).all()
    summaries_data = [{
        'id': sum.id,
        'user_id': sum.user_id,
        'headline': sum.headline,
        'bullet_points': sum.bullet_points,
        'tag': sum.tag,
        'fact_checker': sum.fact_checker,
        'timestamp': sum.timestamp.isoformat()
    } for sum in latest_summaries]
    
    return jsonify({
        'backlog_segments': backlog_data,
        'latest_summaries': summaries_data
    }), 200


def check_for_new_summaries(user_id, last_check):
    new_summaries = summaries.query.filter(
        summaries.user_id == user_id,
        summaries.timestamp > datetime.fromtimestamp(last_check, pytz.UTC)
    ).order_by(summaries.timestamp.asc()).all()

    return [{
        'id': summary.id,
        'headline': summary.headline,
        'bullet_points': summary.bullet_points,
        'tag': summary.tag,
        'fact_checker': summary.fact_checker,
        'timestamp': summary.timestamp.isoformat()
    } for summary in new_summaries]

if __name__ != '__main__':
    # On Replit, this block may not be executed, so we ensure the scheduler starts
    # and application context is properly set up.
    pass

if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', 5000))
        socketio.run(app, host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Failed to run app: {e}", exc_info=True)