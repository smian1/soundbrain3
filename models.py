from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import logging
from datetime import datetime
import pytz
from sqlalchemy import func, Index

# Set up logging for this module
logger = logging.getLogger(__name__)

# Define a base class for declarative models
class Base(DeclarativeBase):
    pass

# Initialize SQLAlchemy with the custom base class
db = SQLAlchemy(model_class=Base)

# User model for authentication and user management
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=True)
    uid = db.Column(db.String(255), unique=True, nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True)
    timezone = db.Column(db.String(50), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)

    def __init__(self, username, password=None, uid=None, email=None, first_name=None, last_name=None, profile_picture=None, timezone=None):
        self.username = username
        if password:
            self.password = generate_password_hash(password)
        self.uid = uid
        self.email = email
        self.first_name = first_name
        self.last_name = last_name
        self.profile_picture = profile_picture
        self.timezone = timezone
        logger.debug(f"Created user {username} with UID: {uid}")

    def check_password(self, password):
        """Verify the user's password"""
        return check_password_hash(self.password, password)

    def __repr__(self):
        return f"<User {self.username}>"

    # Add relationships
    temp_segments = relationship('temp_segments', back_populates='user')
    summaries = relationship('summaries', back_populates='user')

# Main model to store session data
class Main(db.Model):
    __tablename__ = 'main'

    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String, nullable=False)
    session_id = db.Column(db.String, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    host = db.Column(db.String, nullable=False)
    raw_data = db.Column(JSONB, nullable=False)  # Stores JSON data

    # Establish a one-to-many relationship with Segment model
    segments = db.relationship('Segment', back_populates='main', cascade='all, delete-orphan')

# Segment model to store individual parts of a session
class Segment(db.Model):
    __tablename__ = 'segments'

    id = db.Column(db.Integer, primary_key=True)
    main_id = db.Column(db.Integer, db.ForeignKey('main.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    speaker = db.Column(db.String, nullable=False)
    speaker_id = db.Column(db.Integer)
    is_user = db.Column(db.Boolean, nullable=False)
    start_time = db.Column(db.Float)
    end_time = db.Column(db.Float)
    timestamp = db.Column(db.DateTime(timezone=True), default=db.func.now())
    summary_id = db.Column(db.Integer, db.ForeignKey('summaries.id'), nullable=True)
    processed = db.Column(db.Boolean, default=False)

    # Establish the many-to-one relationship with Main model
    main = relationship('Main', back_populates='segments')

    # Add relationship to summaries
    summary = relationship('summaries', back_populates='segments')

    def to_dict(self):
        """
        Convert the Segment object to a dictionary for serialization
        Ensures the timestamp is in UTC and ISO format
        """
        utc_timestamp = self.timestamp.replace(tzinfo=pytz.UTC)
        
        return {
            'id': self.id,
            'main_id': self.main_id,
            'text': self.text,
            'speaker': self.speaker,
            'speaker_id': self.speaker_id,
            'is_user': self.is_user,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'timestamp': utc_timestamp.isoformat(),
            'summary_id': self.summary_id,
            'processed': self.processed
        }

class temp_segments(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    segment_id = db.Column(db.Integer, nullable=False)
    speaker = db.Column(db.String(255))
    text = db.Column(db.Text)
    timestamp = db.Column(db.DateTime(timezone=True), default=func.now())
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    locked = db.Column(db.Boolean, default=False)
    lock_timestamp = db.Column(db.DateTime(timezone=True))
    processed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    processing_attempts = db.Column(db.Integer, default=0)

    # Add an index for faster queries
    __table_args__ = (
        Index('idx_user_id_locked', user_id, locked),
        Index('idx_processed_at', processed_at),
    )

    # Add relationship to User
    user = relationship('User', back_populates='temp_segments')

class summaries(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    headline = db.Column(db.Text, nullable=False)
    bullet_points = db.Column(db.ARRAY(db.Text), nullable=False)
    tag = db.Column(db.String(255))
    fact_checker = db.Column(db.ARRAY(db.Text))
    timestamp = db.Column(db.DateTime(timezone=True), default=func.now())
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())

    # Update relationship to User
    user = relationship('User', back_populates='summaries')

    # Add relationship to Segment
    segments = relationship('Segment', back_populates='summary')