import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'exploreease-secret-key-2025'
    ADMIN_SECRET_KEY = os.environ.get('ADMIN_SECRET_KEY') or 'admin123'
    UPLOAD_FOLDER = 'static/uploads'
    
    # For production - will be set by Render
    if 'DATABASE_URL' in os.environ:
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL').replace('postgres://', 'postgresql://')
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///database.db'
