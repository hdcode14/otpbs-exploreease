import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'exploreease-secret-key-2025'
    ADMIN_SECRET_KEY = os.environ.get('ADMIN_SECRET_KEY') or 'admin123'
    UPLOAD_FOLDER = 'static/uploads'
