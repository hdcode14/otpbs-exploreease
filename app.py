from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime
import os
import time
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'exploreease-secret-key-2025')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ADMIN_SECRET_KEY'] = os.environ.get('ADMIN_SECRET_KEY', 'admin123')

@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ==================== DATABASE CONNECTION FUNCTION ====================
# ==================== DATABASE CONNECTION FUNCTION ====================
def get_db_connection():
    """
    Universal database connection that works on both local and Render
    Uses persistent disk on Render which survives redeploys
    """
    if 'RENDER' in os.environ:
        # On Render - use persistent disk
        db_path = '/opt/render/data/database.db'
        print("🟢 Using Render SQLite database at:", db_path)
    else:
        # Local development
        db_path = 'database.db'
        print("🟢 Using local SQLite database at:", db_path)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
# ==================== END DATABASE CONNECTION ====================
# ==================== END DATABASE CONNECTION ====================

def debug_database_state():
    """Debug function to check database state"""
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Check tables
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = c.fetchall()
        print("DEBUG: Tables in database:", [table[0] for table in tables])
        
        # Check recent bookings
        c.execute("SELECT id, user_id, package_id, total_price FROM bookings ORDER BY id DESC LIMIT 5")
        recent_bookings = c.fetchall()
        print("DEBUG: Recent bookings:", recent_bookings)
        
        # Check payments table structure
        c.execute("PRAGMA table_info(payments)")
        payment_columns = c.fetchall()
        print("DEBUG: Payments table columns:", payment_columns)
        
        # Check if there are any payments
        c.execute("SELECT COUNT(*) FROM payments")
        payment_count = c.fetchone()[0]
        print("DEBUG: Total payments:", payment_count)
        
    except Exception as e:
        print(f"DEBUG Error: {e}")
    finally:
        conn.close()

def verify_and_fix_payments_table():
    """Verify and fix the payments table if needed"""
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Check if payments table has all required columns
        c.execute("PRAGMA table_info(payments)")
        columns = c.fetchall()
        column_names = [col[1] for col in columns]
        print("DEBUG: Payments table columns:", column_names)
        
        # Add missing columns if needed
        required_columns = ['id', 'booking_id', 'user_id', 'amount', 'payment_method', 'status', 'transaction_id', 'payment_date', 'created_at']
        
        for req_col in required_columns:
            if req_col not in column_names:
                print(f"DEBUG: Adding missing column: {req_col}")
                if req_col == 'amount':
                    c.execute(f"ALTER TABLE payments ADD COLUMN {req_col} REAL NOT NULL DEFAULT 0.0")
                elif req_col in ['payment_date', 'created_at']:
                    c.execute(f"ALTER TABLE payments ADD COLUMN {req_col} DATETIME DEFAULT CURRENT_TIMESTAMP")
                else:
                    c.execute(f"ALTER TABLE payments ADD COLUMN {req_col} TEXT")
        
        conn.commit()
        print("DEBUG: Payments table verified and fixed if needed")
        
    except Exception as e:
        print(f"DEBUG: Error verifying payments table: {e}")
        conn.rollback()
    finally:
        conn.close()

def create_payment_simple(booking_id, user_id, amount, payment_method, transaction_id=None, max_retries=5, retry_delay=0.5):
    """Enhanced payment creation with better error handling and type conversion"""
    
    for attempt in range(max_retries):
        conn = None
        try:
            print(f"🔄 PAYMENT ATTEMPT {attempt + 1}/{max_retries} for booking {booking_id}")
            
            # Increase delay between retries
            if attempt > 0:
                time.sleep(retry_delay * attempt)
                print(f"⏳ Retrying after {retry_delay * attempt} seconds...")
            
            conn = get_db_connection()
            # More aggressive timeout settings
            conn.execute("PRAGMA busy_timeout = 10000")  # 10 seconds
            conn.execute("PRAGMA journal_mode=WAL")
            
            c = conn.cursor()
            
            # Convert amount safely - handle both string and numeric types
            try:
                if isinstance(amount, str):
                    # Remove any currency symbols or commas
                    clean_amount = amount.replace('₹', '').replace('$', '').replace(',', '').strip()
                    amount_float = float(clean_amount)
                    print(f"💰 String amount '{amount}' converted to float: {amount_float}")
                else:
                    amount_float = float(amount)
                    print(f"💰 Numeric amount converted to float: {amount_float}")
            except (ValueError, TypeError) as e:
                print(f"❌ Amount conversion failed: {e}")
                print(f"❌ Original amount: {amount} (type: {type(amount)})")
                amount_float = 0.0
            
            print(f"💰 Final amount for payment: {amount_float} (type: {type(amount_float)})")
            
            if not transaction_id:
                transaction_id = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{booking_id}"
            
            print(f"📝 Inserting payment with transaction ID: {transaction_id}")
            
            # Simple insert with error handling
            c.execute('''
                INSERT INTO payments (booking_id, user_id, amount, payment_method, transaction_id, status)
                VALUES (?, ?, ?, ?, ?, 'Pending')
            ''', (booking_id, user_id, amount_float, payment_method, transaction_id))
            
            payment_id = c.lastrowid
            conn.commit()
            print(f"✅ PAYMENT SUCCESS: ID {payment_id}")
            return payment_id
            
        except sqlite3.OperationalError as e:
            error_msg = str(e)
            print(f"❌ DATABASE ERROR (Attempt {attempt + 1}): {error_msg}")
            
            if conn:
                conn.close()
                
            if "database is locked" in error_msg and attempt < max_retries - 1:
                print(f"🔄 Database locked, will retry...")
                continue
            else:
                print(f"💥 Final database error after {max_retries} attempts")
                return None
                
        except sqlite3.IntegrityError as e:
            print(f"❌ INTEGRITY ERROR: {e}")
            if conn:
                conn.close()
            return None
            
        except Exception as e:
            print(f"❌ UNEXPECTED ERROR: {e}")
            import traceback
            print(f"📋 Traceback: {traceback.format_exc()}")
            if conn:
                conn.close()
            return None
    
    print(f"💥 All {max_retries} payment attempts failed")
    return None

def create_payment_safe(booking_id, user_id, amount, payment_method, transaction_id=None):
    """
    Safe payment creation with type conversion and validation
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        print(f"DEBUG: Creating payment - booking_id: {booking_id}, user_id: {user_id}, amount: {amount}, type: {type(amount)}")
        
        # Convert amount to float safely
        try:
            if isinstance(amount, str):
                # Remove any currency symbols, commas, etc.
                clean_amount = amount.replace('₹', '').replace('$', '').replace(',', '').strip()
                amount_float = float(clean_amount)
                print(f"DEBUG: Converted string '{amount}' to float: {amount_float}")
            else:
                amount_float = float(amount)
                print(f"DEBUG: Converted {amount} to float: {amount_float}")
        except (ValueError, TypeError) as e:
            print(f"ERROR: Converting amount '{amount}' to float: {e}")
            return None
        
        # Validate amount
        if amount_float <= 0:
            print(f"ERROR: Invalid amount: {amount_float}")
            return None
        
        print(f"DEBUG: Final amount: {amount_float} (type: {type(amount_float)})")
        
        # Generate transaction ID if not provided
        if not transaction_id:
            transaction_id = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{booking_id}"
        
        print(f"DEBUG: Transaction ID: {transaction_id}")
        
        # Insert payment
        c.execute('''
            INSERT INTO payments 
            (booking_id, user_id, amount, payment_method, transaction_id, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (booking_id, user_id, amount_float, payment_method, transaction_id, 'Pending'))
        
        payment_id = c.lastrowid
        conn.commit()
        print(f"SUCCESS: Payment created with ID: {payment_id}")
        return payment_id
        
    except Exception as e:
        print(f"ERROR: Creating payment: {e}")
        import traceback
        print(f"ERROR Traceback: {traceback.format_exc()}")
        conn.rollback()
        return None
    finally:
        conn.close()
        
def update_database_schema():
    """Update database schema to add missing columns"""
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Check if refund_amount column exists in bookings table
        c.execute("PRAGMA table_info(bookings)")
        columns = [col[1] for col in c.fetchall()]
        
        # Add missing columns if they don't exist
        if 'refund_amount' not in columns:
            print("Adding refund_amount column to bookings table...")
            c.execute("ALTER TABLE bookings ADD COLUMN refund_amount REAL DEFAULT 0.0")
        
        # Add any other missing columns that might be needed
        missing_columns = [
            ('booking_date', 'DATETIME DEFAULT CURRENT_TIMESTAMP'),
            ('travel_date', 'DATETIME'),
            ('refund_amount', 'REAL DEFAULT 0.0')
        ]
        
        for column_name, column_type in missing_columns:
            if column_name not in columns:
                print(f"Adding {column_name} column to bookings table...")
                c.execute(f"ALTER TABLE bookings ADD COLUMN {column_name} {column_type}")
        
        conn.commit()
        print("Database schema updated successfully!")
        
    except Exception as e:
        print(f"Error updating database schema: {e}")
        conn.rollback()
    finally:
        conn.close()

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Existing tables creation code...
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  is_admin BOOLEAN DEFAULT FALSE,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS packages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  destination TEXT NOT NULL,
                  category TEXT NOT NULL,
                  duration TEXT NOT NULL,
                  price REAL NOT NULL,
                  rating REAL NOT NULL,
                  latitude REAL NOT NULL,
                  longitude REAL NOT NULL,
                  description TEXT NOT NULL,
                  image TEXT NOT NULL,
                  region TEXT NOT NULL,
                  itinerary TEXT NOT NULL,
                  inclusions TEXT NOT NULL,
                  available_slots INTEGER DEFAULT 50,
                  is_active BOOLEAN DEFAULT TRUE,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS wishlist
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  package_id INTEGER NOT NULL,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users(id),
                  FOREIGN KEY (package_id) REFERENCES packages(id),
                  UNIQUE(user_id, package_id))''')
    
    # UPDATED BOOKINGS TABLE WITH ALL COLUMNS
    c.execute('''CREATE TABLE IF NOT EXISTS bookings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  package_id INTEGER NOT NULL,
                  guests INTEGER DEFAULT 1,
                  travelers INTEGER DEFAULT 1,
                  total_price REAL DEFAULT 0.0,  
                  total_cost REAL DEFAULT 0.0,  
                  amount REAL DEFAULT 0.0,       
                  price REAL DEFAULT 0.0,        
                  booking_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                  booked_on DATETIME DEFAULT CURRENT_TIMESTAMP,
                  travel_date DATETIME,
                  status TEXT DEFAULT 'confirmed',
                  payment_status TEXT DEFAULT 'pending',
                  refund_amount REAL DEFAULT 0.0,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users(id),
                  FOREIGN KEY (package_id) REFERENCES packages(id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS payments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  booking_id INTEGER NOT NULL,
                  user_id INTEGER NOT NULL,
                  amount REAL NOT NULL,
                  payment_method TEXT NOT NULL,
                  status TEXT DEFAULT 'pending',
                  transaction_id TEXT UNIQUE,
                  payment_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (booking_id) REFERENCES bookings(id),
                  FOREIGN KEY (user_id) REFERENCES users(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS refund_requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  booking_id INTEGER NOT NULL,
                  user_id INTEGER NOT NULL,
                  reason TEXT NOT NULL,
                  refund_amount REAL DEFAULT 0.0,
                  status TEXT DEFAULT 'Pending',
                  requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  processed_at DATETIME,
                  FOREIGN KEY (booking_id) REFERENCES bookings(id),
                  FOREIGN KEY (user_id) REFERENCES users(id))''')
    
    # Check if packages already exist to avoid duplicates - FIXED VERSION
    c.execute('SELECT COUNT(*) FROM packages')
    package_count = c.fetchone()[0]
    
    # Only insert sample packages if table is empty
    if package_count == 0:
        packages = [
            # West Bengal
            ('Darjeeling Delight', 'Darjeeling', 'Hill Station', '5D / 4N', 14999, 4.7, 
             27.0360, 88.2627, 'Experience the queen of hills with breathtaking views of Kanchenjunga and lush tea gardens.', 
             'darjeeling.jpg', 'West Bengal',
             'Day 1: Arrival & Local Sightseeing|Day 2: Tiger Hill & Batasia Loop|Day 3: Ghoom Monastery|Day 4: Tea Garden Visit|Day 5: Departure',
             'Accommodation|Meals|Transport|Guide|Entry Fees'),
            
            ('Sundarban Safari', 'South 24 Parganas', 'Wildlife', '3D / 2N', 9499, 4.5,
             21.9497, 88.9401, 'Explore the mystical mangrove forests and spot the Royal Bengal Tiger in their natural habitat.', 
             'sundarban.jpg', 'West Bengal',
             'Day 1: Arrival & Boat Safari|Day 2: Tiger Spotting & Bird Watching|Day 3: Village Tour & Departure',
             'Accommodation|All Meals|Boat Safari|Guide|Permits'),
            
            ('Kolkata Heritage Walk', 'Kolkata', 'Cultural', '2D / 1N', 6999, 4.6,
             22.5726, 88.3639, 'Discover the cultural capital of India with its colonial architecture and rich history.', 
             'kolkata.jpg', 'West Bengal',
             'Day 1: Victoria Memorial & Park Street|Day 2: Howrah Bridge & Kalighat Temple',
             'Hotel Stay|Breakfast|Transport|Guide|Entry Fees'),
            
            # Northeast India
            ('Majestic Meghalaya', 'Shillong & Cherrapunjee', 'Nature', '6D / 5N', 18499, 4.8,
             25.5788, 91.8933, 'Witness the living root bridges and stunning waterfalls in the abode of clouds.', 
             'meghalaya.jpg', 'Northeast',
             'Day 1: Arrival in Shillong|Day 2: Cherrapunjee Waterfalls|Day 3: Living Root Bridges|Day 4: Dawki River|Day 5: Local Markets|Day 6: Departure',
             'Accommodation|All Meals|Transport|Guide|Activities'),
            
            ('Mystical Arunachal', 'Tawang', 'Adventure', '7D / 6N', 21999, 4.7,
             27.5880, 91.8650, 'Explore the land of dawn-lit mountains with ancient monasteries and pristine landscapes.', 
             'arunachal.jpg', 'Northeast',
             'Day 1: Guwahati to Bomdila|Day 2: Bomdila to Tawang|Day 3: Tawang Monastery|Day 4: Madhuri Lake|Day 5: Bum La Pass|Day 6: Return Journey|Day 7: Departure',
             'Accommodation|All Meals|Transport|Inner Line Permits|Guide'),
            
            ('Dzukou Dream Trail', 'Nagaland', 'Trekking', '5D / 4N', 16999, 4.6,
             25.6514, 94.1058, 'Trek through the beautiful Dzukou Valley with its unique flora and stunning landscapes.', 
             'dzuko.jpg', 'Northeast',
             'Day 1: Arrival in Kohima|Day 2: Trek to Dzukou Valley|Day 3: Valley Exploration|Day 4: Return Trek|Day 5: Departure',
             'Accommodation|All Meals|Trek Guide|Camping Equipment|Permits'),
            
            # Other India
            ('Goa Beach Escape', 'Goa', 'Beach', '4D / 3N', 12999, 4.7,
             15.2993, 74.1240, 'Relax on pristine beaches and experience Portuguese heritage in this tropical paradise.', 
             'goa.jpg', 'Other India',
             'Day 1: Arrival & Beach Visit|Day 2: North Goa Exploration|Day 3: South Goa Relaxation|Day 4: Departure',
             'Beach Resort|Breakfast|Transport|Water Sports'),
            
            ('Himalayan Escape', 'Himachal', 'Adventure', '6D / 5N', 17999, 4.8,
             31.1048, 77.1734, 'Experience the majestic Himalayas with adventure activities and scenic beauty.', 
             'himachal.jpg', 'Other India',
             'Day 1: Delhi to Manali|Day 2: Solang Valley|Day 3: Rohtang Pass|Day 4: Local Sightseeing|Day 5: Kasol Visit|Day 6: Departure',
             'Accommodation|All Meals|Transport|Adventure Activities'),
            
            ('Royal Rajasthan', 'Jaipur–Udaipur–Jodhpur', 'Heritage', '6D / 5N', 19499, 4.7,
             26.9124, 75.7873, 'Experience royal heritage with palaces, forts, and cultural experiences.', 
             'rajasthan.jpg', 'Other India',
             'Day 1: Jaipur Arrival|Day 2: Amber Fort & City Palace|Day 3: Udaipur Lake City|Day 4: Jodhpur Fort|Day 5: Desert Experience|Day 6: Departure',
             'Heritage Hotels|All Meals|Transport|Guide|Cultural Shows'),
            
            # International
            ('Discover Dubai', 'UAE', 'Luxury', '5D / 4N', 58999, 4.9,
             25.2048, 55.2708, 'Experience luxury shopping, stunning architecture, and desert adventures.', 
             'dubai.jpg', 'International',
             'Day 1: Burj Khalifa & Dubai Mall|Day 2: Desert Safari|Day 3: Palm Jumeirah|Day 4: Abu Dhabi Day Trip|Day 5: Departure',
             '5-Star Hotel|Breakfast|Sightseeing|Desert Safari|Visa Assistance'),
            
            ('Bangkok Getaway', 'Thailand', 'Leisure', '4D / 3N', 47999, 4.8,
             13.7563, 100.5018, 'Explore vibrant street markets, ancient temples, and delicious street food.', 
             'bangkok.jpg', 'International',
             'Day 1: Arrival & Street Food Tour|Day 2: Grand Palace & Temples|Day 3: Floating Markets|Day 4: Departure',
             'Hotel Stay|Breakfast|Tours|Airport Transfers'),
            
            ('Bali Bliss', 'Indonesia', 'Honeymoon', '6D / 5N', 64999, 4.9,
             -8.4095, 115.1889, 'Perfect romantic getaway with beautiful beaches, temples, and luxury resorts.', 
             'bali.jpg', 'International',
             'Day 1: Arrival in Ubud|Day 2: Temple Tour|Day 3: Beach Day|Day 4: Water Sports|Day 5: Romantic Dinner|Day 6: Departure',
             'Luxury Villa|All Meals|Private Transport|Spa Sessions')
        ]
        
        for package in packages:
            # Check if package already exists before inserting
            c.execute('SELECT COUNT(*) FROM packages WHERE name = ? AND destination = ?', 
                     (package[0], package[1]))
            exists = c.fetchone()[0]
            
            if exists == 0:
                c.execute('''INSERT INTO packages 
                            (name, destination, category, duration, price, rating, latitude, longitude, 
                             description, image, region, itinerary, inclusions) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', package)
    
    # Check if admin user exists
    c.execute('SELECT COUNT(*) FROM users WHERE email = ?', ('admin@exploreease.com',))
    admin_exists = c.fetchone()[0]
    
    # Only create admin user if it doesn't exist
    if admin_exists == 0:
        admin_password = generate_password_hash('admin123')
        c.execute('INSERT INTO users (name, email, password, is_admin) VALUES (?, ?, ?, ?)',
                  ('Admin User', 'admin@exploreease.com', admin_password, True))
    
    conn.commit()
    conn.close()
    print("Database initialized successfully with all required tables!")
    
    # Update schema to add any missing columns
    update_database_schema()
    verify_and_fix_payments_table()
    debug_database_state()

# Initialize database only once when app starts
# Initialize database on first request
@app.before_first_request
def initialize_database():
    init_db()

class User(UserMixin):
    def __init__(self, id, name, email, is_admin):
        self.id = id
        self.name = name
        self.email = email
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1], user[2], user[4])
    return None

# Cache control middleware
@app.after_request
def add_header(response):
    """
    Add headers to prevent caching for authenticated pages
    """
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# Authentication Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin'))
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        remember = True if request.form.get('remember') else False
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE email = ?', (email,))
        user_data = c.fetchone()
        conn.close()
        
        if user_data and check_password_hash(user_data[3], password):
            user = User(user_data[0], user_data[1], user_data[2], user_data[4])
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            
            # Create response with cache control
            if user.is_admin:
                flash('Admin login successful!', 'success')
                redirect_url = next_page or url_for('admin')
            else:
                flash('Logged in successfully!', 'success')
                redirect_url = next_page or url_for('index')
            
            response = make_response(redirect(redirect_url))
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        else:
            flash('Invalid email or password!', 'error')
    
    # For GET requests, also add cache control
    response = make_response(render_template('login.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        admin_secret = request.form.get('admin_secret', '')  # Hidden admin field
        
        conn = get_db_connection()
        c = conn.cursor()
        
        try:
            hashed_password = generate_password_hash(password)
            
            # Check if this should be an admin registration
            is_admin = False
            if admin_secret:
                # Verify admin secret key
                if admin_secret == app.config.get('ADMIN_SECRET_KEY', 'admin123'):
                    is_admin = True
                    print(f"🔐 Admin user created: {email}")
                else:
                    flash('Invalid admin secret key! Regular user account created.', 'warning')
            
            c.execute('INSERT INTO users (name, email, password, is_admin) VALUES (?, ?, ?, ?)',
                     (name, email, hashed_password, is_admin))
            conn.commit()
            
            if is_admin:
                flash('Admin registration successful! Please login.', 'success')
            else:
                flash('Registration successful! Please login.', 'success')
                
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists!', 'error')
        finally:
            conn.close()
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully!', 'success')
    
    # Create response with cache control
    response = make_response(redirect(url_for('index')))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.set_cookie('session', '', expires=0)
    return response

# Routes
@app.route('/')
def index():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM packages WHERE is_active = TRUE LIMIT 6')
    featured_packages = c.fetchall()
    conn.close()
    return render_template('index.html', packages=featured_packages)

@app.route('/packages')
def packages():
    region = request.args.get('region', 'all')
    category = request.args.get('category', 'all')
    sort = request.args.get('sort', 'name')
    search = request.args.get('search', '')
    
    conn = get_db_connection()
    c = conn.cursor()
    
    query = 'SELECT * FROM packages WHERE is_active = TRUE'
    params = []
    
    if region != 'all':
        query += ' AND region = ?'
        params.append(region)
    
    if category != 'all':
        query += ' AND category = ?'
        params.append(category)
    
    if search:
        query += ' AND (name LIKE ? OR destination LIKE ? OR description LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    if sort == 'price_low':
        query += ' ORDER BY price ASC'
    elif sort == 'price_high':
        query += ' ORDER BY price DESC'
    elif sort == 'rating':
        query += ' ORDER BY rating DESC'
    else:
        query += ' ORDER BY name ASC'
    
    c.execute(query, params)
    packages_list = c.fetchall()
    conn.close()
    
    return render_template('packages.html', packages=packages_list, 
                         region=region, category=category, sort=sort, search=search)

@app.route('/package/<int:package_id>')
def package_detail(package_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM packages WHERE id = ?', (package_id,))
    package = c.fetchone()
    conn.close()
    
    if not package:
        flash('Package not found!', 'error')
        return redirect(url_for('packages'))
    
    return render_template('package_detail.html', package=package)

# Admin Package Management
@app.route('/admin/packages')
@login_required
def admin_packages():
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM packages ORDER BY created_at DESC')
    packages_list = c.fetchall()
    conn.close()
    
    return render_template('admin_packages.html', packages=packages_list)

@app.route('/admin/package/add', methods=['GET', 'POST'])
@login_required
def add_package():
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        destination = request.form['destination']
        category = request.form['category']
        duration = request.form['duration']
        price = float(request.form['price'])
        rating = float(request.form['rating'])
        latitude = float(request.form['latitude'])
        longitude = float(request.form['longitude'])
        description = request.form['description']
        region = request.form['region']
        itinerary = request.form['itinerary']
        inclusions = request.form['inclusions']
        available_slots = int(request.form['available_slots'])
        
        # Handle image upload
        image_file = request.files['image']
        image_filename = 'default.jpg'  # default image
        
        if image_file and image_file.filename != '':
            # Save the uploaded file
            image_filename = image_file.filename
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
            image_file.save(image_path)
        
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('''INSERT INTO packages 
                    (name, destination, category, duration, price, rating, latitude, longitude,
                     description, image, region, itinerary, inclusions, available_slots)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (name, destination, category, duration, price, rating, latitude, longitude,
                   description, image_filename, region, itinerary, inclusions, available_slots))
        
        conn.commit()
        conn.close()
        
        flash('Package added successfully!', 'success')
        return redirect(url_for('admin_packages'))
    
    return render_template('add_package.html')

@app.route('/admin/package/edit/<int:package_id>', methods=['GET', 'POST'])
@login_required
def edit_package(package_id):
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    if request.method == 'POST':
        name = request.form['name']
        destination = request.form['destination']
        category = request.form['category']
        duration = request.form['duration']
        price = float(request.form['price'])
        rating = float(request.form['rating'])
        latitude = float(request.form['latitude'])
        longitude = float(request.form['longitude'])
        description = request.form['description']
        region = request.form['region']
        itinerary = request.form['itinerary']
        inclusions = request.form['inclusions']
        available_slots = int(request.form['available_slots'])
        is_active = True if request.form.get('is_active') else False
        
        # Handle image upload
        image_file = request.files['image']
        
        if image_file and image_file.filename != '':
            # Save the uploaded file
            image_filename = image_file.filename
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
            image_file.save(image_path)
            
            c.execute('''UPDATE packages SET 
                        name=?, destination=?, category=?, duration=?, price=?, rating=?,
                        latitude=?, longitude=?, description=?, image=?, region=?, 
                        itinerary=?, inclusions=?, available_slots=?, is_active=?
                        WHERE id=?''',
                      (name, destination, category, duration, price, rating, latitude, longitude,
                       description, image_filename, region, itinerary, inclusions, 
                       available_slots, is_active, package_id))
        else:
            # Keep existing image if no new image uploaded
            c.execute('''UPDATE packages SET 
                        name=?, destination=?, category=?, duration=?, price=?, rating=?,
                        latitude=?, longitude=?, description=?, region=?, 
                        itinerary=?, inclusions=?, available_slots=?, is_active=?
                        WHERE id=?''',
                      (name, destination, category, duration, price, rating, latitude, longitude,
                       description, region, itinerary, inclusions, available_slots, 
                       is_active, package_id))
        
        conn.commit()
        conn.close()
        
        flash('Package updated successfully!', 'success')
        return redirect(url_for('admin_packages'))
    
    # GET request - load package data
    c.execute('SELECT * FROM packages WHERE id = ?', (package_id,))
    package = c.fetchone()
    conn.close()
    
    if not package:
        flash('Package not found!', 'error')
        return redirect(url_for('admin_packages'))
    
    return render_template('edit_package.html', package=package)

@app.route('/admin/package/delete/<int:package_id>')
@login_required
def delete_package(package_id):
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if package has any bookings
    c.execute('SELECT COUNT(*) FROM bookings WHERE package_id = ?', (package_id,))
    booking_count = c.fetchone()[0]
    
    if booking_count > 0:
        # Soft delete - set is_active to False
        c.execute('UPDATE packages SET is_active = FALSE WHERE id = ?', (package_id,))
        flash('Package has existing bookings. It has been deactivated instead of deleted.', 'warning')
    else:
        # Hard delete - remove package completely
        c.execute('DELETE FROM packages WHERE id = ?', (package_id,))
        flash('Package deleted successfully!', 'success')
    
    conn.commit()
    conn.close()
    return redirect(url_for('admin_packages'))

@app.route('/admin/package/toggle/<int:package_id>')
@login_required
def toggle_package(package_id):
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT is_active FROM packages WHERE id = ?', (package_id,))
    package = c.fetchone()
    
    if package:
        new_status = not package[0]
        c.execute('UPDATE packages SET is_active = ? WHERE id = ?', (new_status, package_id))
        status_text = "activated" if new_status else "deactivated"
        flash(f'Package {status_text} successfully!', 'success')
    
    conn.commit()
    conn.close()
    return redirect(url_for('admin_packages'))

# Wishlist functionality
@app.route('/wishlist/add/<int:package_id>')
@login_required
def add_to_wishlist(package_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        c.execute('INSERT OR IGNORE INTO wishlist (user_id, package_id) VALUES (?, ?)',
                  (current_user.id, package_id))
        conn.commit()
        flash('Added to wishlist!', 'success')
    except:
        flash('Already in wishlist!', 'info')
    
    conn.close()
    return redirect(request.referrer or url_for('packages'))

@app.route('/wishlist')
@login_required
def view_wishlist():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT p.* FROM packages p 
                 JOIN wishlist w ON p.id = w.package_id 
                 WHERE w.user_id = ?''', (current_user.id,))
    wishlist_packages = c.fetchall()
    conn.close()
    return render_template('wishlist.html', packages=wishlist_packages)

@app.route('/wishlist/remove/<int:package_id>')
@login_required
def remove_from_wishlist(package_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('DELETE FROM wishlist WHERE user_id = ? AND package_id = ?',
              (current_user.id, package_id))
    conn.commit()
    conn.close()
    flash('Removed from wishlist!', 'success')
    return redirect(url_for('view_wishlist'))

# Payment and Booking Process - FIXED VERSION
@app.route('/book/<int:package_id>', methods=['GET', 'POST'])
@login_required
def book_package(package_id):
    if request.method == 'POST':
        travel_date = request.form['travel_date']
        guests = int(request.form['travelers'])
        payment_method = request.form.get('payment_method', 'card')
        
        print(f"DEBUG: Starting booking process - package_id: {package_id}, guests: {guests}")
        
        # Use separate database connections for booking and payment
        try:
            # STEP 1: Create booking in one transaction
            conn_booking = get_db_connection()
            conn_booking.execute("PRAGMA busy_timeout=5000")
            c_booking = conn_booking.cursor()
            
            # Check package availability
            c_booking.execute('SELECT price, available_slots FROM packages WHERE id = ?', (package_id,))
            package = c_booking.fetchone()
            
            if not package:
                flash('Package not found!', 'error')
                return redirect(url_for('packages'))
            
            print(f"DEBUG: Package found - price: {package[0]}, available_slots: {package[1]}")
            
            if package[1] < guests:
                flash('Not enough available slots!', 'error')
                return redirect(url_for('package_detail', package_id=package_id))
            
            total_price = float(package[0]) * guests  # Ensure it's float
            print(f"DEBUG: Total price calculated: {total_price} (type: {type(total_price)})")
            
            # Create booking
            c_booking.execute('''INSERT INTO bookings 
                        (user_id, package_id, travel_date, guests, total_price, status, payment_status)
                        VALUES (?, ?, ?, ?, ?, 'Pending', 'Pending')''',
                      (current_user.id, package_id, travel_date, guests, total_price))
            
            booking_id = c_booking.lastrowid
            print(f"DEBUG: Booking created with ID: {booking_id}")
            
            # COMMIT booking immediately to release lock
            conn_booking.commit()
            conn_booking.close()
            print(f"DEBUG: Booking committed successfully")
            
            # STEP 2: Create payment in separate transaction
            transaction_id = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{booking_id}"
            print(f"DEBUG: Calling create_payment_simple with booking_id: {booking_id}, amount: {total_price} (type: {type(total_price)})")
            
            # Ensure amount is properly converted to float
            payment_amount = float(total_price)  # Double conversion to be safe
            print(f"DEBUG: Payment amount after conversion: {payment_amount} (type: {type(payment_amount)})")
            
            payment_id = create_payment_simple(booking_id, current_user.id, payment_amount, payment_method, transaction_id)
            
            if not payment_id:
                flash('Payment creation failed! Please try again.', 'error')
                return redirect(url_for('package_detail', package_id=package_id))
            
            print(f"DEBUG: Payment created successfully with ID: {payment_id}")
            
            # Redirect to payment processing
            return redirect(url_for('process_payment', booking_id=booking_id))
            
        except Exception as e:
            print(f"DEBUG: Error in book_package: {e}")
            import traceback
            print(f"DEBUG Traceback: {traceback.format_exc()}")
            flash('Booking failed! Please try again.', 'error')
            return redirect(url_for('package_detail', package_id=package_id))
    
    # GET request - show booking form (existing code remains the same)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM packages WHERE id = ?', (package_id,))
    package = c.fetchone()
    conn.close()
    
    if not package:
        flash('Package not found!', 'error')
        return redirect(url_for('packages'))
    
    return render_template('booking.html', package=package)

@app.route('/payment/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def process_payment(booking_id):
    print(f"🔍 PAYMENT ROUTE STARTED for booking_id: {booking_id}")
    
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Get booking and payment details
        c.execute('''SELECT 
                     b.id, b.user_id, b.package_id, b.travel_date, b.guests, 
                     b.total_price, b.status, b.payment_status,
                     p.name as package_name, p.destination as package_destination,
                     pay.id as payment_id, pay.transaction_id, pay.amount as payment_amount, pay.payment_method
                     FROM bookings b 
                     JOIN packages p ON b.package_id = p.id 
                     JOIN payments pay ON b.id = pay.booking_id 
                     WHERE b.id = ? AND b.user_id = ?''', (booking_id, current_user.id))
        booking_data = c.fetchone()
        
        if not booking_data:
            flash('Booking not found!', 'error')
            return redirect(url_for('my_bookings'))
        
        # Convert to dictionary
        booking_dict = {
            'id': booking_data[0],
            'user_id': booking_data[1],
            'package_id': booking_data[2],
            'travel_date': booking_data[3],
            'guests': booking_data[4],
            'total_price': float(booking_data[5]),
            'status': booking_data[6],
            'payment_status': booking_data[7],
            'package_name': booking_data[8],
            'destination': booking_data[9],
            'payment_id': booking_data[10],
            'transaction_id': booking_data[11],
            'amount': float(booking_data[12]),
            'payment_method': booking_data[13]
        }
        
        if request.method == 'POST':
            payment_method = request.form.get('payment_method')
            print(f"🔍 Processing {payment_method} payment for booking {booking_id}")
            
            # Handle different payment methods
            if payment_method == 'card':
                # Credit/Debit Card processing
                card_number = request.form.get('card_number')
                expiry_date = request.form.get('expiry_date')
                cvv = request.form.get('cvv')
                card_holder = request.form.get('card_holder')
                
                if not all([card_number, expiry_date, cvv, card_holder]):
                    flash('Please fill all card details!', 'error')
                    return render_template('payment.html', booking=booking_dict)
                
                # Simulate card validation
                if len(card_number.replace(' ', '')) != 16 or not card_number.replace(' ', '').isdigit():
                    flash('Invalid card number!', 'error')
                    return render_template('payment.html', booking=booking_dict)
                
                if len(cvv) != 3 or not cvv.isdigit():
                    flash('Invalid CVV!', 'error')
                    return render_template('payment.html', booking=booking_dict)
                
                print(f"✅ Card payment validated for booking {booking_id}")
                
            elif payment_method == 'upi':
                # UPI processing
                upi_id = request.form.get('upi_id')
                
                if not upi_id or '@' not in upi_id:
                    flash('Please enter a valid UPI ID!', 'error')
                    return render_template('payment.html', booking=booking_dict)
                
                print(f"✅ UPI payment initiated for booking {booking_id}")
                
            elif payment_method == 'netbanking':
                # Net Banking processing
                bank_name = request.form.get('bank_name')
                
                if not bank_name:
                    flash('Please select a bank!', 'error')
                    return render_template('payment.html', booking=booking_dict)
                
                print(f"✅ Net Banking payment initiated for booking {booking_id}")
            
            # Process payment (simulate success)
            try:
                # Update payment method if changed
                if payment_method != booking_dict['payment_method']:
                    c.execute('UPDATE payments SET payment_method = ? WHERE id = ?', 
                             (payment_method, booking_dict['payment_id']))
                
                # Update booking and payment status
                c.execute('UPDATE bookings SET status = "Confirmed", payment_status = "Paid" WHERE id = ?', 
                         (booking_id,))
                c.execute('UPDATE payments SET status = "Success" WHERE booking_id = ?', 
                         (booking_id,))
                c.execute('UPDATE packages SET available_slots = available_slots - ? WHERE id = ?', 
                         (booking_dict['guests'], booking_dict['package_id']))
                
                conn.commit()
                conn.close()
                
                print(f"✅ Payment processed successfully via {payment_method}")
                flash(f'Payment successful via {payment_method.upper()}! Booking confirmed.', 'success')
                return redirect(url_for('booking_confirmation', booking_id=booking_id))
                
            except Exception as e:
                print(f"❌ Error processing payment: {e}")
                conn.rollback()
                conn.close()
                flash('Payment processing failed! Please try again.', 'error')
        
        # GET request - show payment page
        conn.close()
        return render_template('payment.html', booking=booking_dict)
        
    except Exception as e:
        print(f"❌ CRITICAL ERROR in process_payment: {e}")
        flash('An error occurred while loading the payment page.', 'error')
        return redirect(url_for('my_bookings'))
    
@app.route('/admin/register', methods=['GET', 'POST'])
def admin_register():
    """Admin registration route (only accessible by existing admins or for initial setup)"""
    # For security, you might want to restrict this route
    # For now, we'll allow it but in production, you should add proper access control
    
    if current_user.is_authenticated and not current_user.is_admin:
        flash('Access denied! Only admins can register new admin users.', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        admin_secret = request.form.get('admin_secret', '')  # Optional secret key for extra security
        
        # Basic validation
        if not all([name, email, password]):
            flash('Please fill all required fields!', 'error')
            return render_template('admin_register.html')
        
        # Check if it's the first admin (no admins in system)
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users WHERE is_admin = TRUE')
        admin_count = c.fetchone()[0]
        
        # If no admins exist, allow registration without secret
        # If admins exist, require admin secret
        if admin_count > 0:
            if admin_secret != app.config.get('ADMIN_SECRET_KEY', 'admin123'):
                flash('Invalid admin secret key!', 'error')
                conn.close()
                return render_template('admin_register.html')
        
        try:
            hashed_password = generate_password_hash(password)
            c.execute('INSERT INTO users (name, email, password, is_admin) VALUES (?, ?, ?, ?)',
                     (name, email, hashed_password, True))
            conn.commit()
            flash('Admin registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists!', 'error')
        finally:
            conn.close()
    
    return render_template('admin_register.html')

@app.route('/booking/confirm/<int:booking_id>')
@login_required
def booking_confirmation(booking_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    # FIXED QUERY with proper column order
    c.execute('''SELECT 
                 b.id, b.user_id, b.package_id, b.travel_date, b.guests, 
                 b.total_price, b.status, b.payment_status, b.booking_date,
                 p.name as package_name, p.destination, p.duration, p.image, 
                 p.itinerary, p.inclusions,
                 u.name as user_name, u.email,
                 pay.transaction_id, pay.payment_method, pay.created_at as payment_date
                 FROM bookings b 
                 JOIN packages p ON b.package_id = p.id 
                 JOIN users u ON b.user_id = u.id
                 JOIN payments pay ON b.id = pay.booking_id 
                 WHERE b.id = ? AND b.user_id = ?''', (booking_id, current_user.id))
    
    booking_tuple = c.fetchone()
    conn.close()
    
    if not booking_tuple:
        flash('Booking not found!', 'error')
        return redirect(url_for('my_bookings'))
    
    # Convert tuple to dictionary with CORRECT mapping and safe date handling
    booking_dict = {
        'id': booking_tuple[0],
        'user_id': booking_tuple[1],
        'package_id': booking_tuple[2],
        'travel_date': safe_format_date(booking_tuple[3]),  # Safe date formatting
        'guests': booking_tuple[4],
        'total_price': float(booking_tuple[5]) if booking_tuple[5] else 0.0,
        'status': booking_tuple[6],
        'payment_status': booking_tuple[7],
        'booking_date': safe_format_date(booking_tuple[8]),  # Safe date formatting
        'package_name': booking_tuple[9],
        'destination': booking_tuple[10],
        'duration': booking_tuple[11],
        'image': booking_tuple[12],
        'itinerary': booking_tuple[13],
        'inclusions': booking_tuple[14],
        'user_name': booking_tuple[15],
        'user_email': booking_tuple[16],
        'transaction_id': booking_tuple[17],
        'payment_method': booking_tuple[18],
        'payment_date': safe_format_date(booking_tuple[19])  # Safe date formatting
    }
    
    return render_template('booking_confirmation.html', booking=booking_dict)

# Add this custom filter for safe date formatting
@app.template_filter('safe_strftime')
def safe_strftime(value, format='%Y-%m-%d'):
    """Safely format dates, handling both datetime objects and strings"""
    if value is None:
        return "N/A"
    
    # If it's already a string, return as is
    if isinstance(value, str):
        return value
    
    # If it's a datetime object, format it
    if hasattr(value, 'strftime'):
        return value.strftime(format)
    
    # If it's a float or int, try to convert to datetime
    try:
        # Handle timestamp floats
        from datetime import datetime
        if isinstance(value, (int, float)):
            # If it's a reasonable timestamp (after 2000)
            if value > 946684800:  # Jan 1, 2000
                return datetime.fromtimestamp(value).strftime(format)
        return str(value)
    except:
        return str(value)

# Register the filter
app.jinja_env.filters['safe_strftime'] = safe_strftime

# Booking Details and Document Generation
@app.route('/booking/details/<int:booking_id>')
@login_required
def booking_details(booking_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    # FIXED QUERY with proper column selection and aliases
    c.execute('''SELECT 
                 b.id, b.user_id, b.package_id, b.travel_date, b.guests, 
                 b.total_price, b.status, b.payment_status, b.booking_date,
                 p.name as package_name, p.destination, p.duration, p.image, 
                 p.itinerary, p.inclusions,
                 u.name as user_name, u.email,
                 pay.transaction_id, pay.payment_method, pay.created_at as payment_date
                 FROM bookings b 
                 JOIN packages p ON b.package_id = p.id 
                 JOIN users u ON b.user_id = u.id
                 JOIN payments pay ON b.id = pay.booking_id 
                 WHERE b.id = ? AND b.user_id = ?''', (booking_id, current_user.id))
    
    booking_tuple = c.fetchone()
    conn.close()
    
    if not booking_tuple:
        flash('Booking not found!', 'error')
        return redirect(url_for('my_bookings'))
    
    # DEBUG: Print the raw tuple to see the actual data order
    print("🔍 RAW BOOKING TUPLE:")
    for i, value in enumerate(booking_tuple):
        print(f"   Index {i}: {value} (type: {type(value)})")
    
    # Convert tuple to dictionary with CORRECT mapping
    booking_dict = {
        'id': booking_tuple[0],
        'user_id': booking_tuple[1],
        'package_id': booking_tuple[2],
        'travel_date': booking_tuple[3],
        'guests': booking_tuple[4],
        'total_price': float(booking_tuple[5]) if booking_tuple[5] else 0.0,
        'status': booking_tuple[6],
        'payment_status': booking_tuple[7],
        'booking_date': booking_tuple[8],
        'package_name': booking_tuple[9],
        'destination': booking_tuple[10],
        'duration': booking_tuple[11],
        'image': booking_tuple[12],
        'itinerary': booking_tuple[13],
        'inclusions': booking_tuple[14],
        'user_name': booking_tuple[15],
        'user_email': booking_tuple[16],
        'transaction_id': booking_tuple[17],
        'payment_method': booking_tuple[18],
        'payment_date': booking_tuple[19]
    }
    
    # DEBUG: Print the final dictionary
    print("🔍 FINAL BOOKING DICTIONARY:")
    for key, value in booking_dict.items():
        print(f"   {key}: {value} (type: {type(value)})")
    
    return render_template('booking_details.html', booking=booking_dict)

@app.context_processor
def utility_processor():
    """Make utilities available to all templates"""
    def format_date(date_value, fmt='%Y-%m-%d'):
        return safe_format_date(date_value, fmt)
    
    return {
        'now': datetime.now(),
        'format_date': format_date,
        'current_year': datetime.now().year
    }

@app.route('/booking/invoice/<int:booking_id>')
@login_required
def generate_invoice(booking_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get booking details
    c.execute('''SELECT 
                 b.id, b.user_id, b.package_id, b.travel_date, b.guests, 
                 b.total_price, b.status, b.payment_status, b.booking_date,
                 p.name as package_name, p.destination, p.duration, 
                 u.name as user_name, u.email, u.id as user_id,
                 pay.transaction_id, pay.payment_method, pay.created_at as payment_date
                 FROM bookings b 
                 JOIN packages p ON b.package_id = p.id 
                 JOIN users u ON b.user_id = u.id
                 JOIN payments pay ON b.id = pay.booking_id 
                 WHERE b.id = ? AND b.user_id = ?''', (booking_id, current_user.id))
    
    booking_tuple = c.fetchone()
    conn.close()
    
    if not booking_tuple:
        flash('Booking not found!', 'error')
        return redirect(url_for('my_bookings'))
    
    # Convert tuple to dictionary
    booking_dict = {
        'id': booking_tuple[0],
        'user_id': booking_tuple[1],
        'package_id': booking_tuple[2],
        'travel_date': safe_format_date(booking_tuple[3]),
        'guests': booking_tuple[4],
        'total_price': float(booking_tuple[5]) if booking_tuple[5] else 0.0,
        'status': booking_tuple[6],
        'payment_status': booking_tuple[7],
        'booking_date': safe_format_date(booking_tuple[8]),
        'package_name': booking_tuple[9],
        'destination': booking_tuple[10],
        'duration': booking_tuple[11],
        'user_name': booking_tuple[12],
        'user_email': booking_tuple[13],
        'user_id': booking_tuple[14],
        'transaction_id': booking_tuple[15],
        'payment_method': booking_tuple[16],
        'payment_date': safe_format_date(booking_tuple[17])
    }
    
    # Create PDF buffer
    buffer = io.BytesIO()
    
    # Create PDF document
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                          topMargin=0.5*inch, bottomMargin=0.5*inch,
                          leftMargin=0.5*inch, rightMargin=0.5*inch)
    
    # Create story (content)
    story = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.darkblue,
        alignment=1,  # Center
        spaceAfter=30
    )
    story.append(Paragraph("INVOICE", title_style))
    
    # Company Info
    company_style = ParagraphStyle(
        'CompanyStyle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.gray
    )
    story.append(Paragraph("ExploreEase Travel Solutions", company_style))
    story.append(Paragraph("123 Travel Street, Kolkata, West Bengal", company_style))
    story.append(Paragraph("Phone: +91 9876543210 | Email: info@exploreease.com", company_style))
    story.append(Spacer(1, 20))
    
    # Invoice Details Table
    invoice_data = [
        ['Invoice Number:', f'INV-{booking_dict["id"]:06d}'],
        ['Invoice Date:', datetime.now().strftime('%Y-%m-%d')],
        ['Booking ID:', f'BK-{booking_dict["id"]:06d}'],
        ['Transaction ID:', booking_dict['transaction_id'] or 'N/A']
    ]
    
    invoice_table = Table(invoice_data, colWidths=[2*inch, 3*inch])
    invoice_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(invoice_table)
    story.append(Spacer(1, 20))
    
    # Customer and Package Details in two columns
    customer_data = [
        ['BILL TO:', 'PACKAGE DETAILS:'],
        [booking_dict['user_name'], booking_dict['package_name']],
        [booking_dict['user_email'], f"Destination: {booking_dict['destination']}"],
        [f"User ID: {booking_dict['user_id']}", f"Duration: {booking_dict['duration']}"],
        ['', f"Travel Date: {booking_dict['travel_date']}"],
        ['', f"Guests: {booking_dict['guests']}"]
    ]
    
    customer_table = Table(customer_data, colWidths=[2.5*inch, 3*inch])
    customer_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
        ('BACKGROUND', (0, 0), (0, 0), colors.darkblue),
        ('BACKGROUND', (1, 0), (1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 11),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(customer_table)
    story.append(Spacer(1, 30))
    
    # Payment Details
    payment_header_style = ParagraphStyle(
        'PaymentHeader',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.darkgreen,
        spaceAfter=10
    )
    story.append(Paragraph("Payment Details", payment_header_style))
    
    payment_data = [
        ['Description', 'Amount (₹)'],
        [f"Travel Package: {booking_dict['package_name']}", f"₹{booking_dict['total_price']:,.2f}"],
        ['Number of Guests', f"{booking_dict['guests']}"],
        ['', ''],
        ['TOTAL AMOUNT', f"₹{booking_dict['total_price']:,.2f}"]
    ]
    
    payment_table = Table(payment_data, colWidths=[3.5*inch, 1.5*inch])
    payment_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
        ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 11),
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LINEABOVE', (0, -1), (-1, -1), 2, colors.black),
        ('FONT', (0, -1), (-1, -1), 'Helvetica-Bold', 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -2), 1, colors.grey)
    ]))
    story.append(payment_table)
    story.append(Spacer(1, 30))
    
    # Payment Method and Status
    status_data = [
        ['Payment Method:', booking_dict['payment_method'].title()],
        ['Payment Status:', booking_dict['payment_status']],
        ['Payment Date:', booking_dict['payment_date']]
    ]
    
    status_table = Table(status_data, colWidths=[1.5*inch, 4*inch])
    status_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(status_table)
    story.append(Spacer(1, 40))
    
    # Terms and Conditions
    terms_style = ParagraphStyle(
        'TermsStyle',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=1  # Center
    )
    story.append(Paragraph("Thank you for choosing ExploreEase!", terms_style))
    story.append(Paragraph("This is a computer-generated invoice and does not require a signature.", terms_style))
    story.append(Paragraph("For any queries, contact: support@exploreease.com", terms_style))
    
    # Build PDF
    doc.build(story)
    
    # Get PDF value from buffer
    pdf = buffer.getvalue()
    buffer.close()
    
    # Return PDF as download
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=invoice_{booking_id}.pdf'
    return response

@app.route('/booking/e-ticket/<int:booking_id>')
@login_required
def generate_e_ticket(booking_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get booking details
    c.execute('''SELECT 
                 b.id, b.user_id, b.package_id, b.travel_date, b.guests, 
                 b.total_price, b.status, b.payment_status, b.booking_date,
                 p.name as package_name, p.destination, p.duration, p.image, 
                 p.itinerary, p.inclusions,
                 u.name as user_name, u.email, u.id as user_id,
                 pay.transaction_id, pay.payment_method, pay.created_at as payment_date
                 FROM bookings b 
                 JOIN packages p ON b.package_id = p.id 
                 JOIN users u ON b.user_id = u.id
                 JOIN payments pay ON b.id = pay.booking_id 
                 WHERE b.id = ? AND b.user_id = ?''', (booking_id, current_user.id))
    
    booking_tuple = c.fetchone()
    conn.close()
    
    if not booking_tuple:
        flash('Booking not found!', 'error')
        return redirect(url_for('my_bookings'))
    
    # Convert tuple to dictionary
    booking_dict = {
        'id': booking_tuple[0],
        'user_id': booking_tuple[1],
        'package_id': booking_tuple[2],
        'travel_date': safe_format_date(booking_tuple[3]),
        'guests': booking_tuple[4],
        'total_price': float(booking_tuple[5]) if booking_tuple[5] else 0.0,
        'status': booking_tuple[6],
        'payment_status': booking_tuple[7],
        'booking_date': safe_format_date(booking_tuple[8]),
        'package_name': booking_tuple[9],
        'destination': booking_tuple[10],
        'duration': booking_tuple[11],
        'image': booking_tuple[12],
        'itinerary': booking_tuple[13],
        'inclusions': booking_tuple[14],
        'user_name': booking_tuple[15],
        'user_email': booking_tuple[16],
        'user_id': booking_tuple[17],
        'transaction_id': booking_tuple[18],
        'payment_method': booking_tuple[19],
        'payment_date': safe_format_date(booking_tuple[20])
    }
    
    # Create PDF buffer
    buffer = io.BytesIO()
    
    # Create PDF document with smaller margins for ticket format
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                          topMargin=0.3*inch, bottomMargin=0.3*inch,
                          leftMargin=0.3*inch, rightMargin=0.3*inch)
    
    story = []
    styles = getSampleStyleSheet()
    
    # Header with company logo and title
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.darkblue,
        alignment=1,  # Center
        spaceAfter=20
    )
    story.append(Paragraph("EXPLOREEASE TRAVEL E-TICKET", header_style))
    
    # Ticket Border - create a table that acts as ticket border
    ticket_data = [
        ['E-TICKET DETAILS', ''],
        ['Booking Reference:', f'BK-{booking_dict["id"]:06d}'],
        ['Issue Date:', datetime.now().strftime('%Y-%m-%d %H:%M')],
        ['Status:', booking_dict['status']],
        ['', '']
    ]
    
    ticket_table = Table(ticket_data, colWidths=[2.5*inch, 3*inch])
    ticket_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
        ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 12),
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 2, colors.darkblue),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(ticket_table)
    story.append(Spacer(1, 20))
    
    # Passenger Details
    passenger_style = ParagraphStyle(
        'PassengerStyle',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.darkgreen,
        spaceAfter=10
    )
    story.append(Paragraph("PASSENGER INFORMATION", passenger_style))
    
    passenger_data = [
        ['Passenger Name:', booking_dict['user_name']],
        ['Email:', booking_dict['user_email']],
        ['User ID:', f'USR-{booking_dict["user_id"]:06d}'],
        ['Number of Guests:', str(booking_dict['guests'])]
    ]
    
    passenger_table = Table(passenger_data, colWidths=[1.5*inch, 4*inch])
    passenger_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(passenger_table)
    story.append(Spacer(1, 20))
    
    # Travel Details
    travel_style = ParagraphStyle(
        'TravelStyle',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.purple,
        spaceAfter=10
    )
    story.append(Paragraph("TRAVEL DETAILS", travel_style))
    
    travel_data = [
        ['Package:', booking_dict['package_name']],
        ['Destination:', booking_dict['destination']],
        ['Duration:', booking_dict['duration']],
        ['Travel Date:', booking_dict['travel_date']],
        ['Booking Date:', booking_dict['booking_date']]
    ]
    
    travel_table = Table(travel_data, colWidths=[1.5*inch, 4*inch])
    travel_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
        ('BACKGROUND', (0, 0), (0, -1), colors.lavender),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(travel_table)
    story.append(Spacer(1, 20))
    
    # Payment Information
    payment_style = ParagraphStyle(
        'PaymentStyle',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.darkred,
        spaceAfter=10
    )
    story.append(Paragraph("PAYMENT INFORMATION", payment_style))
    
    payment_data = [
        ['Total Amount:', f'₹{booking_dict["total_price"]:,.2f}'],
        ['Payment Method:', booking_dict['payment_method'].title()],
        ['Transaction ID:', booking_dict['transaction_id'] or 'N/A'],
        ['Payment Status:', booking_dict['payment_status']],
        ['Payment Date:', booking_dict['payment_date']]
    ]
    
    payment_table = Table(payment_data, colWidths=[1.5*inch, 4*inch])
    payment_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
        ('BACKGROUND', (0, 0), (0, -1), colors.mistyrose),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(payment_table)
    story.append(Spacer(1, 30))
    
    # Important Notes
    notes_style = ParagraphStyle(
        'NotesStyle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.red,
        alignment=0,  # Left
        spaceAfter=5
    )
    
    story.append(Paragraph("IMPORTANT NOTES:", notes_style))
    story.append(Paragraph("• Please carry a printed copy of this e-ticket and valid ID proof.", notes_style))
    story.append(Paragraph("• Check-in time: 2:00 PM | Check-out time: 11:00 AM", notes_style))
    story.append(Paragraph("• For any changes, contact us at least 48 hours before travel.", notes_style))
    story.append(Paragraph("• Emergency contact: +91 9876543210", notes_style))
    story.append(Spacer(1, 20))
    
    # Footer
    footer_style = ParagraphStyle(
        'FooterStyle',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=1  # Center
    )
    story.append(Paragraph("Thank you for choosing ExploreEase! Have a safe journey!", footer_style))
    story.append(Paragraph("Generated on: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'), footer_style))
    
    # Build PDF
    doc.build(story)
    
    # Get PDF value from buffer
    pdf = buffer.getvalue()
    buffer.close()
    
    # Return PDF as download
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=e_ticket_{booking_id}.pdf'
    return response

@app.route('/my-bookings')
@login_required
def my_bookings():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row  # This allows column access by name
    c = conn.cursor()
    c.execute('''SELECT b.*, p.name, p.destination, p.image 
                 FROM bookings b 
                 JOIN packages p ON b.package_id = p.id 
                 WHERE b.user_id = ? 
                 ORDER BY b.booking_date DESC''', (current_user.id,))
    bookings = c.fetchall()
    conn.close()
    return render_template('bookings.html', bookings=bookings)

def safe_format_date(date_value, format='%Y-%m-%d'):
    """
    Safely format dates for templates, handling various input types
    """
    if date_value is None:
        return "N/A"
    
    # If it's already a string, return as is
    if isinstance(date_value, str):
        return date_value
    
    # If it's a datetime object, format it
    if hasattr(date_value, 'strftime'):
        try:
            return date_value.strftime(format)
        except:
            return str(date_value)
    
    # If it's a float or int, try to convert to datetime
    try:
        from datetime import datetime
        if isinstance(date_value, (int, float)):
            # If it's a reasonable timestamp (after 2000)
            if date_value > 946684800:  # Jan 1, 2000
                return datetime.fromtimestamp(date_value).strftime(format)
        return str(date_value)
    except:
        return str(date_value)
    

@app.route('/booking/refund/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def request_refund(booking_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    # First, ensure the refund_amount column exists
    try:
        c.execute("PRAGMA table_info(bookings)")
        columns = [col[1] for col in c.fetchall()]
        if 'refund_amount' not in columns:
            c.execute("ALTER TABLE bookings ADD COLUMN refund_amount REAL DEFAULT 0.0")
            conn.commit()
    except Exception as e:
        print(f"Error ensuring refund_amount column: {e}")
    
    # Get booking details with proper column selection
    c.execute('''SELECT 
                 b.id, b.user_id, b.package_id, b.travel_date, b.guests, 
                 b.total_price, b.status, b.payment_status, b.booking_date,
                 p.name as package_name, p.destination, p.duration
                 FROM bookings b 
                 JOIN packages p ON b.package_id = p.id 
                 WHERE b.id = ? AND b.user_id = ?''', (booking_id, current_user.id))
    
    booking_tuple = c.fetchone()
    
    if not booking_tuple:
        flash('Booking not found!', 'error')
        conn.close()
        return redirect(url_for('my_bookings'))
    
    # Convert tuple to dictionary for template
    booking_dict = {
        'id': booking_tuple[0],
        'user_id': booking_tuple[1],
        'package_id': booking_tuple[2],
        'travel_date': safe_format_date(booking_tuple[3]),
        'guests': booking_tuple[4],
        'total_price': float(booking_tuple[5]) if booking_tuple[5] else 0.0,
        'status': booking_tuple[6],
        'payment_status': booking_tuple[7],
        'booking_date': safe_format_date(booking_tuple[8]),
        'package_name': booking_tuple[9],
        'destination': booking_tuple[10],
        'duration': booking_tuple[11]
    }
    
    if request.method == 'POST':
        reason = request.form['reason']
        
        # Calculate refund amount
        try:
            travel_date = datetime.strptime(booking_dict['travel_date'], '%Y-%m-%d').date()
            days_before = (travel_date - datetime.now().date()).days
            
            if days_before >= 7:
                refund_amount = booking_dict['total_price'] * 0.8  # 80% refund
            elif days_before >= 3:
                refund_amount = booking_dict['total_price'] * 0.5  # 50% refund
            else:
                refund_amount = 0  # No refund
        except:
            # Fallback if date parsing fails
            refund_amount = booking_dict['total_price'] * 0.5  # Default 50% refund
        
        # Create refund request
        c.execute('''INSERT INTO refund_requests 
                    (booking_id, user_id, reason, refund_amount, status)
                    VALUES (?, ?, ?, ?, 'Pending')''',
                  (booking_id, current_user.id, reason, refund_amount))
        
        # Update booking status - handle refund_amount column safely
        try:
            c.execute('UPDATE bookings SET status = "Cancelled", refund_amount = ? WHERE id = ?',
                      (refund_amount, booking_id))
        except sqlite3.OperationalError:
            # If refund_amount column doesn't exist, update without it
            c.execute('UPDATE bookings SET status = "Cancelled" WHERE id = ?',
                      (booking_id,))
        
        conn.commit()
        conn.close()
        
        flash('Refund request submitted! We will process it within 3-5 business days.', 'success')
        return redirect(url_for('my_bookings'))
    
    conn.close()
    return render_template('refund_request.html', booking=booking_dict)

@app.route('/admin/update-schema')
@login_required
def update_schema():
    """Manual trigger for schema updates"""
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    update_database_schema()
    flash('Database schema updated successfully!', 'success')
    return redirect(url_for('admin'))


# Admin functionality
@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT COUNT(*) FROM users')
    user_count = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM bookings')
    booking_count = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM packages')
    package_count = c.fetchone()[0]
    
    # FIXED QUERY - Get proper booking data with correct column mapping
    c.execute('''SELECT 
                 b.id, b.user_id, b.package_id, b.travel_date, b.guests, 
                 b.total_price, b.status, b.payment_status, b.booking_date,
                 u.name as user_name, p.name as package_name
                 FROM bookings b 
                 JOIN users u ON b.user_id = u.id 
                 JOIN packages p ON b.package_id = p.id 
                 ORDER BY b.booking_date DESC LIMIT 10''')
    recent_bookings = c.fetchall()
    
    conn.close()
    
    return render_template('admin.html', 
                         user_count=user_count,
                         booking_count=booking_count,
                         package_count=package_count,
                         recent_bookings=recent_bookings)

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT id, name, email, is_admin, created_at FROM users ORDER BY created_at DESC')
    users = c.fetchall()
    conn.close()
    
    return render_template('admin_users.html', users=users)

@app.route('/admin/user/toggle_admin/<int:user_id>')
@login_required
def toggle_user_admin(user_id):
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    # Prevent self-demotion
    if user_id == current_user.id:
        flash('You cannot change your own admin status!', 'error')
        return redirect(url_for('admin_users'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT is_admin FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    
    if user:
        new_status = not user[0]
        c.execute('UPDATE users SET is_admin = ? WHERE id = ?', (new_status, user_id))
        status_text = "granted admin privileges" if new_status else "removed from admin"
        flash(f'User {status_text}!', 'success')
    
    conn.commit()
    conn.close()
    return redirect(url_for('admin_users'))
    
@app.route('/admin/generate-report')
@login_required
def generate_report():
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    try:
        # Create PDF buffer
        buffer = io.BytesIO()
        
        # Create PDF document
        doc = SimpleDocTemplate(buffer, pagesize=A4, 
                              topMargin=0.5*inch, bottomMargin=0.5*inch,
                              leftMargin=0.5*inch, rightMargin=0.5*inch)
        
        # Create story (content)
        story = []
        styles = getSampleStyleSheet()
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.darkblue,
            alignment=1,
            spaceAfter=30
        )
        story.append(Paragraph("ExploreEase Business Report", title_style))
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Get current stats
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM users')
        user_count = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM bookings WHERE status = "Confirmed"')
        confirmed_bookings = c.fetchone()[0]
        
        c.execute('SELECT SUM(total_price) FROM bookings WHERE status = "Confirmed"')
        total_revenue = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM packages WHERE is_active = TRUE')
        active_packages = c.fetchone()[0]
        
        conn.close()
        
        # Statistics Table
        stats_data = [
            ['Metric', 'Value'],
            ['Total Users', str(user_count)],
            ['Confirmed Bookings', str(confirmed_bookings)],
            ['Active Packages', str(active_packages)],
            ['Total Revenue', f'₹{total_revenue:,.2f}'],
            ['Report Period', 'All Time'],
            ['Generated By', current_user.name]
        ]
        
        stats_table = Table(stats_data, colWidths=[3*inch, 2*inch])
        stats_table.setStyle(TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 12),
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(stats_table)
        story.append(Spacer(1, 30))
        
        # Recent Activity
        recent_style = ParagraphStyle(
            'RecentStyle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.darkgreen,
            spaceAfter=10
        )
        story.append(Paragraph("Recent Activity Summary", recent_style))
        
        activity_text = f"""
        This report summarizes the current state of the ExploreEase travel platform.
        The system is operating normally with {user_count} registered users and {active_packages} active travel packages.
        Total revenue generated: ₹{total_revenue:,.2f}
        """
        story.append(Paragraph(activity_text, styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Footer
        footer_style = ParagraphStyle(
            'FooterStyle',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=1
        )
        story.append(Paragraph("Confidential Business Report - ExploreEase Travel Solutions", footer_style))
        story.append(Paragraph("123 Travel Street, Kolkata, West Bengal | Phone: +91 9876543210", footer_style))
        
        # Build PDF
        doc.build(story)
        
        # Get PDF value from buffer
        pdf = buffer.getvalue()
        buffer.close()
        
        # Return PDF as download
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=exploreease_report_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf'
        
        flash('Report generated successfully!', 'success')
        return response
        
    except Exception as e:
        print(f"Error generating report: {e}")
        flash('Error generating report!', 'error')
        return redirect(url_for('admin'))
    

@app.route('/admin/refunds')
@login_required
def admin_refunds():
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT rr.*, u.name as user_name, p.name as package_name, b.total_price
                 FROM refund_requests rr
                 JOIN users u ON rr.user_id = u.id
                 JOIN bookings b ON rr.booking_id = b.id
                 JOIN packages p ON b.package_id = p.id
                 ORDER BY rr.requested_at DESC''')
    refund_requests_raw = c.fetchall()
    conn.close()
    
    # Convert numeric values to proper types
    refund_requests = []
    for request in refund_requests_raw:
        request_list = list(request)
        # Convert refund_amount (index 4) and total_price (index 9) to float
        if request_list[4] is not None:  # refund_amount
            request_list[4] = float(request_list[4]) if str(request_list[4]).replace('.', '').isdigit() else 0.0
        if request_list[9] is not None:  # total_price
            request_list[9] = float(request_list[9]) if str(request_list[9]).replace('.', '').isdigit() else 0.0
        refund_requests.append(tuple(request_list))
    
    return render_template('admin_refunds.html', refund_requests=refund_requests)

@app.route('/admin/refund/process/<int:refund_id>/<action>')
@login_required
def process_refund(refund_id, action):
    if not current_user.is_admin:
        flash('Access denied!', 'error')
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    if action == 'approve':
        c.execute('''UPDATE refund_requests SET status = 'Approved', processed_at = CURRENT_TIMESTAMP 
                     WHERE id = ?''', (refund_id,))
        # Update booking and payment status
        c.execute('''UPDATE bookings SET payment_status = 'Refunded' 
                     WHERE id = (SELECT booking_id FROM refund_requests WHERE id = ?)''', (refund_id,))
        flash('Refund approved and processed!', 'success')
    elif action == 'reject':
        c.execute('''UPDATE refund_requests SET status = 'Rejected', processed_at = CURRENT_TIMESTAMP 
                     WHERE id = ?''', (refund_id,))
        flash('Refund request rejected!', 'success')
    
    conn.commit()
    conn.close()
    return redirect(url_for('admin_refunds'))

# Package comparison
@app.route('/compare')
def compare_packages():
    # Get package IDs from URL parameters
    package_ids_param = request.args.get('package_ids')
    if package_ids_param:
        package_ids = [int(pid) for pid in package_ids_param.split(',') if pid.isdigit()]
    else:
        # Fallback to individual package_id parameters
        package_ids = [int(pid) for pid in request.args.getlist('package_id') if pid.isdigit()]
    
    packages = []
    
    if package_ids:
        conn = get_db_connection()
        c = conn.cursor()
        placeholders = ','.join('?' * len(package_ids))
        query = f'SELECT * FROM packages WHERE id IN ({placeholders}) AND is_active = TRUE'
        c.execute(query, package_ids)
        packages = c.fetchall()
        conn.close()
    
    return render_template('compare.html', packages=packages)

# Debug routes
@app.route('/debug/db-state')
def debug_db_state():
    """Debug route to check database state"""
    debug_database_state()
    return jsonify({"message": "Check console for debug output"})

@app.route('/test/payment/<int:booking_id>')
@login_required
def test_payment(booking_id):
    """Test payment creation for debugging"""
    test_amount = 1000.50
    payment_method = "test"
    
    print(f"TEST: Testing payment creation for booking {booking_id}")
    payment_id = create_payment_simple(booking_id, current_user.id, test_amount, payment_method)
    
    if payment_id:
        return jsonify({"success": True, "payment_id": payment_id})
    else:
        return jsonify({"success": False, "error": "Payment creation failed"})

if __name__ == '__main__':
    # Create upload folder if it doesn't exist
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
