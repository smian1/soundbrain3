# SoundBrain Pro - Webhook Data Storage and Real-time Transcript Display

## Project Overview

SoundBrain Pro is a Flask-based application that serves as a webhook endpoint for receiving and storing transcription data. It provides a real-time admin interface for viewing incoming transcripts, with advanced features for data visualization and analysis. The project uses PostgreSQL for data storage and implements robust user authentication for secure access to the admin panel. It now includes an optimized summarization feature that periodically generates summaries of accumulated transcript segments.

## Features

1. **Webhook Endpoint**:
   - Receives JSON payloads containing transcription data.
   - Stores main session information and individual transcript segments.
   - Supports unique identifiers (UID) for each transcription session.
   - Forwards webhook data to a specified URL for additional processing.

2. **Admin Interface**:
   - Real-time display of incoming transcripts.
   - User authentication with both local and Google OAuth 2.0 support.
   - Interactive timeline for navigating transcripts by date and hour.
   - Dynamic charts for visualizing speaker activity and word frequency.
   - Responsive design for mobile and desktop use.

3. **Database Integration**:
   - Uses SQLAlchemy ORM with PostgreSQL.
   - Stores data in main tables: `User`, `Main`, `Segment`, `temp_segments`, and `summaries`.
   - Efficient querying for large datasets with pagination support.

4. **Real-time Updates**:
   - Implements real-time updates to the admin interface using Socket.IO.
   - Instant display of new transcript segments as they are received.

5. **User Authentication**:
   - Secure login system using Flask-Login.
   - Password hashing for enhanced security.
   - Google OAuth 2.0 integration for easy sign-in.
   - Session management for multiple users.

6. **Data Visualization**:
   - Interactive charts using Chart.js.
   - Speaker activity visualization with heatmaps.
   - Word cloud generation for frequently used terms.
   - Real-time updates to charts as new data comes in.

7. **Responsive Design**:
   - Mobile-friendly admin interface using Tailwind CSS.
   - Adaptive layout for various screen sizes.
   - Collapsible sidebar for better mobile experience.

8. **Advanced Filtering and Analysis**:
   - Filter transcripts by date and hour using an interactive timeline.
   - Word frequency analysis with stop word filtering.
   - Dashboard with key statistics (e.g., total segments, most active hour).

9. **Logging and Error Handling**:
   - Comprehensive logging system for debugging and monitoring.
   - Graceful error handling with informative error messages.
   - Detailed error tracking with traceback information.

10. **Security Features**:
    - CSRF protection for form submissions.
    - Secure session handling.
    - Input validation to prevent SQL injection and other attacks.

11. **Optimized Periodic Summarization**:
    - Automatically generates summaries of accumulated transcript segments every 30 seconds.
    - Uses OpenAI's GPT model for generating concise summaries.
    - Efficiently processes only unprocessed or new segments since the last summarization.
    - Stores summaries in the database for later retrieval.
    - Classifies summaries into predefined categories.
    - Performs fact-checking on the summarized content.
    - Links summaries to original segments for easy reference.

12. **Efficient Segment Management**:
    - Temporary storage of segments in `temp_segments` table.
    - Optimized querying to process only unprocessed or new segments.
    - Locking mechanism to prevent concurrent processing of the same segments.
    - Automatic cleanup of locked segments after 30 minutes.
    - Efficient handling of unprocessed or newly added segments.

## Technical Stack

- **Backend**: Flask (Python 3.x)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Frontend**: HTML, JavaScript, Chart.js, Tailwind CSS
- **Authentication**: Flask-Login, Authlib for OAuth
- **Real-time Updates**: Socket.IO
- **WSGI Server**: Gunicorn with Eventlet workers
- **Asynchronous Processing**: Eventlet
- **Natural Language Processing**: NLTK for word tokenization and stop word removal
- **Summarization**: OpenAI GPT model via LangChain
- **Task Scheduling**: APScheduler for periodic summarization and cleanup tasks

## Database Structure

The application uses PostgreSQL as its database, managed through SQLAlchemy ORM. The database consists of five main tables:

1. **`main` Table**: 
   - Stores the main session information for each transcription session.
   - Fields: id, uid, session_id, timestamp, host, raw_data (JSONB)

2. **`segments` Table**: 
   - Stores individual transcript segments associated with a `main` entry.
   - Fields: id, main_id, text, speaker, speaker_id, is_user, start_time, end_time, timestamp, summary_id, processed

3. **`user` Table**: 
   - Stores user information for authentication and profile management.
   - Fields: id, username, password, uid, email, first_name, last_name, profile_picture, timezone

4. **`temp_segments` Table**: 
   - Temporarily stores segments for processing and summarization.
   - Fields: id, user_id, segment_id, speaker, text, timestamp, created_at, locked, lock_timestamp, processed_at

5. **`summaries` Table**: 
   - Stores generated summaries of transcript segments.
   - Fields: id, user_id, headline, bullet_points, tag, fact_checker, timestamp, created_at

### Key Relationships:
- `segments` to `main`: Many-to-one relationship
- `temp_segments` to `user`: Many-to-one relationship
- `summaries` to `user`: Many-to-one relationship
- `segments` to `summaries`: Many-to-one relationship

### Indexes:
- `idx_temp_segments_created_at` on `temp_segments.created_at`
- `idx_temp_segments_lock_timestamp` on `temp_segments.lock_timestamp`
- `idx_temp_segments_locked` on `temp_segments.locked`
- `idx_temp_segments_user_id_processed_at` on `temp_segments.user_id` and `processed_at`
- `idx_user_id_locked` on `temp_segments.user_id` and `locked`

## Summarization Process

1. **Segment Accumulation**: 
   - New segments are stored in both the `segments` and `temp_segments` tables.
   - The `accumulate_segment` function handles this process, marking new segments as unprocessed.

2. **Periodic Processing**: 
   - Every 30 seconds, a background task (`summarization_task`) checks for accumulated segments.
   - Uses APScheduler for task scheduling.

3. **Efficient Segment Selection**:
   - The process now efficiently selects only unprocessed segments or new segments added since the last processing.
   - This optimization prevents unnecessary reprocessing of already summarized segments.

4. **Segment Locking**: 
   - Before processing, segments are locked to prevent concurrent processing.
   - A cleanup job releases locks older than 30 minutes to prevent deadlocks.

5. **Summary Generation**: 
   - If segments are found, they are processed using OpenAI's GPT model via LangChain.
   - The `generate_summary` function handles the actual summarization.

6. **Storage**: 
   - Generated summaries are stored in the `summaries` table.
   - Includes headline, bullet points, tags, and fact-checking information.

7. **Linking**: 
   - Processed segments in the `segments` table are linked to the corresponding summary via the `summary_id` field.

8. **Cleanup**: 
   - Processed segments are removed from `temp_segments` and marked as processed in `segments`.
   - The `processed_at` timestamp is updated for all processed segments.

9. **Error Handling**: 
   - Comprehensive error handling and logging throughout the process.
   - Failed summarization attempts are logged, and segments are unlocked for future processing.

## Recent Improvements

- Optimized segment selection process to prevent unnecessary reprocessing.
- Enhanced error handling in the summarization process.
- Improved efficiency in handling cases where no segments need processing.
- Updated logging for better tracking of the summarization process.
- Increased the time interval for processing segments from 5 minutes to 20 minutes to provide more context for summarization.
- Improved the rendering of summaries in the admin interface, including better handling of fact-checker information.

## Setup and Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/soundbrain-pro.git
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up PostgreSQL database**:
   - Create a PostgreSQL database.
   - Update the connection string in `config.py`:
     ```python
     SQLALCHEMY_DATABASE_URI = 'postgresql://username:password@localhost:5432/soundbrain_db'
     ```

4. **Set up environment variables**:
   - Set `OPENAI_API_KEY` for OpenAI GPT access.
   - Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` for Google OAuth.

5. **Initialize the database**:
   ```bash
   flask db upgrade
   ```

6. **Run the application**:
   ```bash
   python app.py
   ```

## Usage

### Webhook Endpoint

Send POST requests to `/webhook?uid=<unique_identifier>` with a JSON payload containing session information and transcript segments.

### Admin Interface

Access the admin interface at `http://[your-domain]/admin`. Log in using local credentials or Google OAuth.

### Retrieving Summaries

Use the `/get_summaries` endpoint to retrieve generated summaries, and `/get_summary_segments/<summary_id>` to get segments associated with a specific summary.

## Deployment

- The application is configured for deployment on Replit.
- Ensure all required environment variables are set in Replit Secrets.
- For other platforms, adjust the `Procfile` or deployment scripts accordingly.

## Future Enhancements

- Implement pagination for transcript segments in the admin interface.
- Add search functionality to allow searching through transcripts by keywords or speaker.
- Expand user management with different roles and permissions.
- Add unit and integration tests to ensure application reliability.
- Containerize the application using Docker for easier deployment.
- Implement more sophisticated data analysis tools.
- Create comprehensive API documentation for the webhook endpoint.

## Credits

- Developed by: [Your Name/Team]
- OpenAI GPT Integration: LangChain
- Frontend Framework: Tailwind CSS
- Charting Library: Chart.js

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.

## Contact

For questions or support, please contact [your-email@example.com].