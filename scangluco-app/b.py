import streamlit as st
import google.generativeai as genai
from PIL import Image
import io
import json
from datetime import datetime, timedelta, timezone
import pytz
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import sqlite3
import hashlib
import re
from pathlib import Path
import time

# Gemini API will be configured from session state

# Database setup
DB_PATH = "glucometer_app.db"

def get_db_connection():
    """Get a database connection with proper settings to avoid locking"""
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for better concurrency
    return conn

def init_database():
    """Initialize SQLite database with enhanced schema"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Set WAL mode for better concurrency (persists across connections)
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")  # Faster writes
    cursor.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
    
    # Enhanced Users table with additional security fields
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT DEFAULT 'doctor',
            phone TEXT,
            specialization TEXT,
            is_active INTEGER DEFAULT 1,
            failed_login_attempts INTEGER DEFAULT 0,
            last_failed_login TIMESTAMP,
            account_locked_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            profile_picture BLOB,
            two_factor_enabled INTEGER DEFAULT 0
        )
    ''')
    
    # Enhanced Patients table with more comprehensive data
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT,
            blood_group TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            emergency_contact TEXT,
            emergency_phone TEXT,
            medical_history TEXT,
            current_medications TEXT,
            allergies TEXT,
            diabetes_type TEXT,
            diagnosed_date DATE,
            height_cm REAL,
            weight_kg REAL,
            bmi REAL,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Enhanced Readings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            glucose_value REAL,
            unit TEXT,
            reading_type TEXT,
            date TEXT,
            time TEXT,
            meal_context TEXT,
            activity_level TEXT,
            medication_taken INTEGER,
            stress_level TEXT,
            additional_info TEXT,
            uploaded_by TEXT,
            notes TEXT,
            image_data BLOB,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    ''')
    
    # Appointments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            doctor_username TEXT NOT NULL,
            appointment_date DATE,
            appointment_time TIME,
            reason TEXT,
            status TEXT DEFAULT 'scheduled',
            notes TEXT,
            reminder_sent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    ''')
    
    # Enhanced Alerts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            alert_type TEXT,
            message TEXT,
            severity TEXT,
            is_read INTEGER DEFAULT 0,
            acknowledged_by TEXT,
            acknowledged_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    ''')
    
    # Login History table for security audit
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS login_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            success INTEGER,
            failure_reason TEXT
        )
    ''')
    
    # Activity Log table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            action TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Deletion Warnings table - track when warnings were sent to patients
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deletion_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            warning_type TEXT,
            days_remaining INTEGER,
            warning_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            email_sent INTEGER DEFAULT 0,
            FOREIGN KEY (username) REFERENCES users(username)
        )
    ''')
    
    # Add migration for existing databases - add missing columns individually
    
    # Migrate users table
    users_columns_to_add = [
        ("account_locked_until", "TIMESTAMP"),
        ("failed_login_attempts", "INTEGER DEFAULT 0"),
        ("last_failed_login", "TIMESTAMP"),
        ("is_active", "INTEGER DEFAULT 1"),
        ("two_factor_enabled", "INTEGER DEFAULT 0"),
        ("profile_picture", "BLOB"),
        ("last_login", "TIMESTAMP")
    ]
    
    for column_name, column_type in users_columns_to_add:
        try:
            cursor.execute(f"SELECT {column_name} FROM users LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
            conn.commit()
    
    # Migrate readings table
    readings_columns_to_add = [
        ("uploaded_by", "TEXT"),
    ]
    
    for column_name, column_type in readings_columns_to_add:
        try:
            cursor.execute(f"SELECT {column_name} FROM readings LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            cursor.execute(f"ALTER TABLE readings ADD COLUMN {column_name} {column_type}")
            conn.commit()
    
    # Migrate patients table
    patients_columns_to_add = [
        ("gender", "TEXT"),
        ("blood_group", "TEXT"),
        ("phone", "TEXT"),
        ("email", "TEXT"),
        ("address", "TEXT"),
        ("emergency_contact", "TEXT"),
        ("emergency_phone", "TEXT"),
        ("medical_history", "TEXT"),
        ("current_medications", "TEXT"),
        ("allergies", "TEXT"),
        ("diabetes_type", "TEXT"),
        ("diagnosed_date", "DATE"),
        ("height_cm", "REAL"),
        ("weight_kg", "REAL"),
        ("bmi", "REAL"),
        ("created_by", "TEXT"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("last_updated", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("is_active", "INTEGER DEFAULT 1")
    ]
    
    for column_name, column_type in patients_columns_to_add:
        try:
            cursor.execute(f"SELECT {column_name} FROM patients LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            cursor.execute(f"ALTER TABLE patients ADD COLUMN {column_name} {column_type}")
            conn.commit()
    
    # Migrate activity_log table
    try:
        cursor.execute("SELECT action FROM activity_log LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        cursor.execute("ALTER TABLE activity_log ADD COLUMN action TEXT")
        conn.commit()
    
    conn.commit()
    conn.close()

init_database()

def send_deletion_warning_notification(username, full_name, email, days_remaining):
    """
    Send warning notification to patient about upcoming account deletion.
    This creates an in-app alert and logs the warning.
    In production, this would also send an email.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if warning already sent today
        today = datetime.now().date().isoformat()
        cursor.execute('''
            SELECT id FROM deletion_warnings 
            WHERE username = ? 
            AND DATE(warning_sent_at) = ?
            AND days_remaining = ?
        ''', (username, today, days_remaining))
        
        if cursor.fetchone():
            conn.close()
            return  # Already sent today
        
        # Create warning message based on days remaining
        if days_remaining <= 0:
            warning_type = "CRITICAL"
            message = f"⚠️ CRITICAL: Your account will be deleted TODAY due to 30 days of inactivity. All your medical data will be permanently erased. Please log in immediately to prevent deletion."
        elif days_remaining <= 5:
            warning_type = "URGENT"
            message = f"⚠️ URGENT: Your account will be deleted in {days_remaining} day(s) due to inactivity. Please log in to keep your account and medical data."
        else:
            warning_type = "WARNING"
            message = f"⚠️ WARNING: Your account will be deleted in {days_remaining} day(s) if you don't log in. Your medical data will be permanently erased."
        
        # Log the warning in deletion_warnings table
        cursor.execute('''
            INSERT INTO deletion_warnings (username, warning_type, days_remaining, email_sent)
            VALUES (?, ?, ?, ?)
        ''', (username, warning_type, days_remaining, 0))
        
        # Create an in-app alert (if patient records exist)
        cursor.execute('SELECT patient_id FROM patients WHERE created_by = ? LIMIT 1', (username,))
        patient_record = cursor.fetchone()
        
        if patient_record:
            cursor.execute('''
                INSERT INTO alerts (patient_id, alert_type, message, severity)
                VALUES (?, ?, ?, ?)
            ''', (patient_record[0], "Account Deletion Warning", message, "high"))
        
        # Log activity
        cursor.execute('''
            INSERT INTO activity_log (username, action, details, timestamp)
            VALUES (?, ?, ?, ?)
        ''', ('SYSTEM', 'DELETION_WARNING_SENT', 
              f'Sent {warning_type} deletion warning to {username} ({full_name}, {email}) - {days_remaining} days remaining',
              datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        print(f"✉️ Sent {warning_type} warning to {username} - {days_remaining} days remaining")
        
        # In production, send actual email here:
        # send_email(email, f"Account Deletion Warning - {days_remaining} Days Remaining", message)
        
    except Exception as e:
        print(f"Error sending warning to {username}: {str(e)}")

def check_and_send_deletion_warnings():
    """
    Check all patient accounts and send warnings to those approaching deletion.
    Warnings sent at: 30, 15, 7, 5, 3, 2, 1 days before deletion.
    ONLY applies to PATIENT role - doctors, nurses, and admins are never deleted.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get all patient users (NOT doctors, nurses, or admins)
        cursor.execute('''
            SELECT username, full_name, email, last_login, created_at 
            FROM users 
            WHERE role = 'patient'
        ''')
        
        patients = cursor.fetchall()
        conn.close()
        
        warning_thresholds = [30, 15, 7, 5, 3, 2, 1, 0]  # Days before deletion to send warnings
        
        for patient in patients:
            username, full_name, email, last_login, created_at = patient
            
            # Calculate days of inactivity
            reference_date = last_login if last_login else created_at
            if reference_date:
                last_activity = datetime.fromisoformat(reference_date)
                days_inactive = (datetime.now() - last_activity).days
                days_remaining = 30 - days_inactive
                
                # Send warning if at a threshold
                if days_remaining in warning_thresholds and days_remaining <= 30:
                    send_deletion_warning_notification(username, full_name, email, days_remaining)
        
    except Exception as e:
        print(f"Error checking deletion warnings: {str(e)}")

def cleanup_inactive_patient_data():
    """
    Automatically delete ONLY PATIENT accounts and their associated data 
    if they haven't logged in for 30 days.
    
    IMPORTANT: This ONLY affects patients. Doctor, Nurse, and Admin accounts 
    are NEVER automatically deleted regardless of inactivity.
    
    This function should be called periodically (e.g., on app startup or login).
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Calculate the cutoff date (30 days ago)
        cutoff_date = (datetime.now() - timedelta(days=30)).isoformat()
        
        # Find ONLY patient users who haven't logged in for 30 days
        # Doctors, nurses, and admins are excluded by the role filter
        cursor.execute('''
            SELECT username, full_name, email 
            FROM users 
            WHERE role = 'patient' 
            AND (last_login IS NULL OR last_login < ?)
            AND created_at < ?
        ''', (cutoff_date, cutoff_date))
        
        inactive_patients = cursor.fetchall()
        
        if inactive_patients:
            for patient in inactive_patients:
                username = patient[0]
                full_name = patient[1]
                email = patient[2]
                
                # Find all patient records created by this user
                cursor.execute('''
                    SELECT patient_id FROM patients WHERE created_by = ?
                ''', (username,))
                
                patient_ids = [row[0] for row in cursor.fetchall()]
                
                # Delete associated data for each patient_id
                for patient_id in patient_ids:
                    # Delete readings
                    cursor.execute('DELETE FROM readings WHERE patient_id = ?', (patient_id,))
                    
                    # Delete appointments
                    cursor.execute('DELETE FROM appointments WHERE patient_id = ?', (patient_id,))
                    
                    # Delete alerts
                    cursor.execute('DELETE FROM alerts WHERE patient_id = ?', (patient_id,))
                    
                    # Delete patient record
                    cursor.execute('DELETE FROM patients WHERE patient_id = ?', (patient_id,))
                
                # Delete the user account
                cursor.execute('DELETE FROM users WHERE username = ?', (username,))
                
                # Log the cleanup action
                cursor.execute('''
                    INSERT INTO activity_log (username, action, details, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', ('SYSTEM', 'AUTO_CLEANUP', 
                      f'Deleted inactive patient account: {username} ({full_name}, {email}) and all associated data after 30 days of inactivity',
                      datetime.now().isoformat()))
                
                print(f"✓ Cleaned up inactive patient: {username} ({full_name})")
        
        conn.commit()
        conn.close()
        
        return len(inactive_patients) if inactive_patients else 0
        
    except Exception as e:
        print(f"Error during cleanup: {str(e)}")
        return 0

def check_patient_inactivity_warning():
    """
    Check if patient accounts are approaching 30 days of inactivity (e.g., 25 days)
    and return a warning message for the user.
    """
    try:
        if st.session_state.get('user_role') == 'patient':
            conn = get_db_connection()
            cursor = conn.cursor()
            
            username = st.session_state.get('username')
            
            # Get last login date
            cursor.execute('''
                SELECT last_login, created_at 
                FROM users 
                WHERE username = ? AND role = 'patient'
            ''', (username,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                last_login = result[0]
                created_at = result[1]
                
                # Use last_login if available, otherwise use created_at
                reference_date = last_login if last_login else created_at
                
                if reference_date:
                    last_activity = datetime.fromisoformat(reference_date)
                    days_inactive = (datetime.now() - last_activity).days
                    
                    # Warn if inactive for 25+ days (5 days before deletion)
                    if days_inactive >= 25:
                        days_remaining = 30 - days_inactive
                        return days_remaining, days_inactive
        
        return None, None
        
    except Exception as e:
        print(f"Error checking inactivity: {str(e)}")
        return None, None

# Run cleanup and warning checks on app initialization
# IMPORTANT: Only patient accounts are affected - doctors, nurses, and admins are never deleted
check_and_send_deletion_warnings()  # Send warnings first
cleanup_inactive_patient_data()      # Then cleanup accounts that reached 30 days

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = ""
if 'user_role' not in st.session_state:
    st.session_state.user_role = ""
if 'user_full_name' not in st.session_state:
    st.session_state.user_full_name = ""
if 'login_attempts' not in st.session_state:
    st.session_state.login_attempts = 0
if 'show_password_strength' not in st.session_state:
    st.session_state.show_password_strength = False
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""
if 'api_configured' not in st.session_state:
    st.session_state.api_configured = False

# Page configuration
st.set_page_config(
    page_title="Advanced Glucometer Detection System",
    page_icon="🩸",
    layout="centered",  # Better for mobile compatibility
    initial_sidebar_state="auto"  # Auto-collapse on mobile
)

# Enhanced CSS with modern design
def load_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');
    
    * {
        font-family: 'Poppins', sans-serif;
    }
    /* App background */
    .stApp {
        background: linear-gradient(180deg, #f8f5ff 0%, #efe8ff 100%);
        background-attachment: fixed;
    }
    /* Centered auth wrapper and card */
    .auth-wrap {
        min-height: 85vh;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px 16px;
    }
    .auth-card {
        width: 100%;
        max-width: 860px;
        background: rgba(255,255,255,0.75);
        border: 1px solid rgba(160, 123, 255, 0.15);
        border-radius: 16px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.08);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        padding: 24px 24px 28px 24px;
    }
    .auth-logo {
        display: block;
        margin: 4px auto 0 auto;
    }
    .header-section {
        margin-top: 40px;
        margin-bottom: 30px;
    }
    .header-section .main-header {
        padding: 16px 0 6px 0;
    }
    .auth-tagline {
        text-align: center;
        color: #8c77e0;
        font-weight: 500;
        margin: 4px 0 14px 0;
        font-size: 1rem;
    }
    
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #6B4CE6;
        text-align: center;
        padding: 16px 0 6px 0;
        letter-spacing: 0.5px;
        animation: fadeIn 1s ease-in;
    }
    .icon {
        color: #8c6ef0;
        font-size: 28px;
        vertical-align: middle;
        margin-right: 10px;
    }
    .tagline { /* alias class for tagline if used */
        font-size: 1rem;
        color: #8c77e0;
        font-weight: 500;
        margin-top: 8px;
    }
    /* Optional glow for logo image placed after a marker div */
    .logo-wrap + [data-testid="stImage"] img {
        display: block;
        margin: 0 auto;
        filter: drop-shadow(0 0 12px rgba(123, 74, 226, 0.3));
    }
    .logo-center { 
        text-align: center; 
        display: flex; 
        justify-content: center; 
        align-items: center;
        width: 100%;
    }
    .logo-center [data-testid="stImage"] { 
        display: inline-block !important; 
        margin: 0 auto !important; 
    }
    .logo-center [data-testid="stImage"] img {
        display: block !important; 
        margin: 0 auto !important; 
    }
    
    .login-container {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 3px;
        border-radius: 20px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        margin: 20px 0;
    }
    
    .login-inner {
        background: white;
        padding: 40px;
        border-radius: 18px;
    }
    
    .metric-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 25px;
        border-radius: 15px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        transition: all 0.2s ease;
    }
    
    .metric-card:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }
    
    .dashboard-card {
        background: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        transition: all 0.2s ease;
        margin-bottom: 10px;
    }
    
    .dashboard-card:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }
    
    .status-normal {
        color: #28a745;
        font-weight: 600;
    }
    
    .status-warning {
        color: #ffc107;
        font-weight: 600;
    }
    
    .status-danger {
        color: #dc3545;
        font-weight: 600;
    }
    
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        height: 3.5em;
        font-weight: 700;
        padding: 0 1.25rem;
        background: linear-gradient(135deg, #8B7FE8 0%, #A07BFF 100%);
        color: white;
        border: none;
        transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
    }
    
    .stButton>button:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 12px rgba(160, 123, 255, 0.3);
        background: linear-gradient(135deg, #9D8FED 0%, #B58FFF 100%);
    }

    /* Tabs styled as buttons (pills) with active underline */
    [data-baseweb="tab"] {
        position: relative;
        font-weight: 600;
        border: 1px solid #e6ebf2;
        border-radius: 9999px;
        padding: 6px 14px;
        background: #ffffff;
        margin-right: 10px;
        color: #2c3e50;
        transition: background 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }
    [data-baseweb="tab"]:hover {
        background: #f8f9ff;
        border-color: #dbe3f3;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }
    [data-baseweb="tab"]::after {
        content: "";
        position: absolute;
        left: 14px;
        right: 14px;
        bottom: -6px;
        height: 3px;
        background: linear-gradient(90deg, #8B7FE8, #A07BFF);
        border-radius: 3px;
        transform: scaleX(0);
        transform-origin: center;
        transition: transform 0.25s ease;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        font-weight: 700;
        background: linear-gradient(135deg, #f5f2ff 0%, #ffffff 100%);
        border-color: #d4cbff;
        box-shadow: 0 4px 12px rgba(160, 123, 255, 0.18);
    }
    [data-baseweb="tab"][aria-selected="true"]::after {
        transform: scaleX(1);
    }

    /* Mobile responsiveness - Enhanced */
    @media (max-width: 768px) {
        /* Layout adjustments */
        .form-card { 
            padding: 16px; 
            margin: 10px 0;
        }
        .login-inner { 
            padding: 20px 16px; 
        }
        .main-header { 
            font-size: 1.5rem !important; 
            padding: 12px 8px !important;
            line-height: 1.3;
        }
        .auth-card { 
            padding: 16px; 
            margin: 10px;
        }
        .auth-wrap {
            padding: 16px 8px;
            min-height: auto;
        }
        
        /* Header and tagline */
        .header-section {
            margin-top: 20px;
            margin-bottom: 20px;
        }
        .auth-tagline {
            font-size: 0.9rem;
            margin: 8px 0;
        }
        .icon {
            font-size: 22px;
            margin-right: 6px;
        }
        
        /* Buttons */
        .stButton>button {
            height: 3em;
            font-size: 0.95rem;
            padding: 0 1rem;
        }
        
        /* Dashboard cards */
        .dashboard-card {
            padding: 16px;
            margin-bottom: 12px;
        }
        .metric-card {
            padding: 18px;
            margin-bottom: 12px;
        }
        
        /* Welcome banner */
        .welcome-banner {
            padding: 16px;
            margin-bottom: 16px;
        }
        .welcome-banner h2 {
            font-size: 1.3rem;
        }
        .welcome-banner h3 {
            font-size: 1.1rem;
        }
        
        /* Info boxes */
        .info-box {
            padding: 14px 12px;
            margin-bottom: 12px;
        }
        .info-icon {
            width: 48px;
            height: 48px;
            font-size: 22px;
        }
        .info-text {
            font-size: 0.88rem;
        }
        
        /* Tabs */
        [data-baseweb="tab"] {
            padding: 8px 12px;
            font-size: 0.9rem;
            margin-right: 6px;
        }
        
        /* Sidebar adjustments */
        [data-testid="stSidebar"] {
            width: 280px !important;
        }
        [data-testid="stSidebar"] .welcome-banner h2 {
            font-size: 1.2rem;
        }
        [data-testid="stSidebar"] .welcome-banner h3 {
            font-size: 1rem;
        }
        
        /* Form inputs */
        [data-testid="stTextInput"] input,
        [data-testid="stPasswordInput"] input,
        [data-testid="stTextarea"] textarea {
            font-size: 16px !important; /* Prevents zoom on iOS */
            padding: 12px !important;
        }
        
        /* Image upload */
        [data-testid="stFileUploader"] {
            font-size: 0.9rem;
        }
        
        /* Tables */
        [data-testid="stDataFrame"] {
            font-size: 0.85rem;
        }
        
        /* Metrics */
        [data-testid="stMetric"] {
            font-size: 0.9rem;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.3rem;
        }
    }
    
    /* Extra small devices (phones in portrait, less than 576px) */
    @media (max-width: 576px) {
        .main-header {
            font-size: 1.3rem !important;
            padding: 10px 5px !important;
        }
        .auth-card {
            padding: 12px;
            border-radius: 12px;
        }
        .form-card {
            padding: 12px;
        }
        .login-inner {
            padding: 16px 12px;
        }
        .stButton>button {
            height: 2.8em;
            font-size: 0.9rem;
        }
        [data-baseweb="tab"] {
            padding: 6px 10px;
            font-size: 0.85rem;
            margin-right: 4px;
        }
        .dashboard-card,
        .metric-card {
            padding: 14px;
        }
        /* Stack columns on very small screens */
        [data-testid="column"] {
            min-width: 100% !important;
        }
    }
    
    /* Landscape orientation on mobile */
    @media (max-width: 768px) and (orientation: landscape) {
        .auth-wrap {
            min-height: auto;
            padding: 12px;
        }
        .header-section {
            margin-top: 10px;
            margin-bottom: 15px;
        }
        .main-header {
            font-size: 1.4rem !important;
            padding: 8px !important;
        }
    }
    
    /* Touch-friendly adjustments */
    @media (hover: none) and (pointer: coarse) {
        /* Increase tap targets for touch devices */
        .stButton>button {
            min-height: 44px;
            padding: 12px 16px;
        }
        [data-baseweb="tab"] {
            min-height: 40px;
            padding: 10px 14px;
        }
        /* Better spacing for touch */
        [data-testid="stSidebar"] button {
            margin-bottom: 10px;
        }
    }

    /* Sidebar nav buttons (Streamlit primary/secondary) */
    [data-testid="stSidebar"] button[data-testid="baseButton-secondary"] {
        width: 100%;
        border-radius: 10px;
        border: 1px solid rgba(0,0,0,0.06);
        background: #ffffff;
        color: #2c3e50;
        margin-bottom: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        transition: all 0.2s ease;
        font-weight: 500;
    }
    [data-testid="stSidebar"] button[data-testid="baseButton-secondary"]:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 10px rgba(0,0,0,0.08);
    }
    [data-testid="stSidebar"] button[data-testid="baseButton-primary"] {
        width: 100%;
        border-radius: 10px;
        border: none;
        background: linear-gradient(135deg, #8B7FE8 0%, #A07BFF 100%);
        color: #ffffff;
        margin-bottom: 8px;
        box-shadow: 0 6px 14px rgba(160, 123, 255, 0.25);
        transition: all 0.2s ease;
        font-weight: 600;
    }
    [data-testid="stSidebar"] button[data-testid="baseButton-primary"]:hover {
        transform: scale(1.02);
        box-shadow: 0 8px 18px rgba(160, 123, 255, 0.3);
    }
    
    .password-strength {
        height: 5px;
        border-radius: 5px;
        margin-top: 5px;
        transition: all 0.3s ease;
    }
    
    .strength-weak { background: #dc3545; width: 33%; }
    .strength-medium { background: #ffc107; width: 66%; }
    .strength-strong { background: #28a745; width: 100%; }
    
    .welcome-banner {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 15px;
        text-align: center;
        margin-bottom: 20px;
    }
    
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .info-card {
        background: #f8f9fa;
        border-left: 4px solid #667eea;
        padding: 15px;
        border-radius: 8px;
        margin: 10px 0;
    }
    
    .alert-badge {
        background: #dc3545;
        color: white;
        padding: 5px 10px;
        border-radius: 15px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    
    /* Login left info panel */
    .info-panel {
        background: #eaf5ff;
        border-radius: 12px;
        padding: 18px 14px;
    }
    .info-box {
        background: #eaf5ff;
        border-radius: 12px;
        padding: 18px 16px;
        text-align: center;
        margin-bottom: 16px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }
    .info-icon {
        width: 56px;
        height: 56px;
        border-radius: 50%;
        background: #1565c0;
        color: #ffffff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 26px;
        margin: 0 auto 10px auto;
        box-shadow: 0 4px 10px rgba(21,101,192,0.25);
    }
    .info-text {
        color: #1f2d3d;
        font-size: 0.95rem;
        line-height: 1.4rem;
        margin: 0;
    }

    /* Form card and input aesthetics */
    .form-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 8px 20px rgba(0,0,0,0.06);
        border: 1px solid #eef2f7;
    }
    [data-testid="stTextInput"] input,
    [data-testid="stPasswordInput"] input,
    [data-testid="stTextarea"] textarea {
        border: 1px solid #e6ebf2 !important;
        border-radius: 10px !important;
        padding: 10px 12px !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    }
    [data-testid="stTextInput"] input:hover,
    [data-testid="stPasswordInput"] input:hover,
    [data-testid="stTextarea"] textarea:hover {
        border-color: #cfd7e6 !important;
    }
    [data-testid="stTextInput"] input:focus,
    [data-testid="stPasswordInput"] input:focus,
    [data-testid="stTextarea"] textarea:focus {
        border-color: #8B7FE8 !important;
        box-shadow: 0 0 0 3px rgba(139, 127, 232, 0.15) !important;
        outline: none !important;
    }
    /* Selectbox focus ring */
    [data-baseweb="select"] {
        border-radius: 10px !important;
        border: 1px solid #e6ebf2 !important;
        padding: 2px !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;
    }
    [data-baseweb="select"]:focus-within {
        border-color: #8B7FE8 !important;
        box-shadow: 0 0 0 3px rgba(139, 127, 232, 0.15) !important;
    }
    </style>
    """, unsafe_allow_html=True)

load_css()

# Add mobile viewport meta tag for better mobile rendering
st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
""", unsafe_allow_html=True)

# Enhanced Helper Functions
def is_mobile():
    """Detect if user is on mobile device using JavaScript"""
    return st.session_state.get('is_mobile', False)

def detect_mobile():
    """JavaScript to detect mobile device"""
    st.markdown("""
        <script>
        const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent) || window.innerWidth <= 768;
        if (isMobile) {
            window.parent.postMessage({type: 'streamlit:setComponentValue', value: true}, '*');
        }
        </script>
    """, unsafe_allow_html=True)
def hash_password(password):
    """Enhanced password hashing with salt"""
    salt = "glucometer_secure_salt_2024"
    return hashlib.sha256((password + salt).encode()).hexdigest()

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone):
    """Validate phone number"""
    pattern = r'^\+?1?\d{9,15}$'
    return re.match(pattern, phone.replace(" ", "").replace("-", "")) is not None

def check_password_strength(password):
    """Check password strength and return score"""
    score = 0
    feedback = []
    
    if len(password) >= 8:
        score += 1
    else:
        feedback.append("At least 8 characters")
    
    if re.search(r"[a-z]", password) and re.search(r"[A-Z]", password):
        score += 1
    else:
        feedback.append("Mix of uppercase and lowercase")
    
    if re.search(r"\d", password):
        score += 1
    else:
        feedback.append("At least one number")
    
    if re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        score += 1
    else:
        feedback.append("At least one special character")
    
    strength = "Weak"
    color = "#dc3545"
    if score >= 3:
        strength = "Medium"
        color = "#ffc107"
    if score == 4:
        strength = "Strong"
        color = "#28a745"
    
    return strength, score, feedback, color

def check_account_locked(username):
    """Check if account is locked due to failed attempts"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT account_locked_until, failed_login_attempts 
        FROM users WHERE username = ?
    ''', (username,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result and result[0]:
        locked_until = datetime.fromisoformat(result[0])
        if datetime.now() < locked_until:
            remaining = (locked_until - datetime.now()).seconds // 60
            return True, remaining
        else:
            # Unlock account
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET failed_login_attempts = 0, account_locked_until = NULL 
                WHERE username = ?
            ''', (username,))
            conn.commit()
            conn.close()
    
    return False, 0

def log_login_attempt(username, success, failure_reason=None):
    """Log login attempt for security audit"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO login_history (username, success, failure_reason)
        VALUES (?, ?, ?)
    ''', (username, 1 if success else 0, failure_reason))
    
    conn.commit()
    conn.close()

def log_activity(username, action, details):
    """Log user activity with Bangalore timestamp"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get current time in Bangalore timezone
    bangalore_tz = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(bangalore_tz).isoformat()
    
    cursor.execute('''
        INSERT INTO activity_log (username, action, details, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (username, action, details, current_time))
    
    conn.commit()
    conn.close()

def register_user(username, password, email, full_name, role, phone, specialization):
    """Register new user with enhanced validation"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        hashed_pw = hash_password(password)
        cursor.execute('''
            INSERT INTO users (username, password, email, full_name, role, phone, specialization)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (username, hashed_pw, email, full_name, role, phone, specialization))
        
        conn.commit()
        conn.close()
        
        log_activity(username, "USER_REGISTERED", f"New user registered: {full_name}")
        return True, "Registration successful!"
    except sqlite3.IntegrityError:
        return False, "Username or email already exists!"
    except Exception as e:
        return False, f"Error: {str(e)}"

def login_user(username, password):
    """Enhanced authentication with account locking"""
    try:
        # Check if account is locked
        is_locked, remaining_minutes = check_account_locked(username)
        if is_locked:
            return False, None, f"Account locked. Try again in {remaining_minutes} minutes."
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        hashed_pw = hash_password(password)
        cursor.execute('''
            SELECT username, role, full_name, is_active, failed_login_attempts 
            FROM users 
            WHERE username = ? AND password = ?
        ''', (username, hashed_pw))
        
        result = cursor.fetchone()
        
        if result:
            if result[3] == 0:  # Check if account is active
                conn.close()
                log_login_attempt(username, False, "Account deactivated")
                return False, None, "Account is deactivated. Contact administrator."
            
            # Reset failed attempts and update last login
            cursor.execute('''
                UPDATE users 
                SET last_login = CURRENT_TIMESTAMP, 
                    failed_login_attempts = 0,
                    account_locked_until = NULL
                WHERE username = ?
            ''', (username,))
            conn.commit()
            conn.close()
            
            log_login_attempt(username, True)
            log_activity(username, "LOGIN", "User logged in successfully")
            return True, result, None
        else:
            # Increment failed attempts
            cursor.execute('''
                SELECT failed_login_attempts FROM users WHERE username = ?
            ''', (username,))
            
            user_exists = cursor.fetchone()
            
            if user_exists:
                failed_attempts = user_exists[0] + 1
                
                # Lock account after 5 failed attempts
                if failed_attempts >= 5:
                    lock_until = datetime.now() + timedelta(minutes=15)
                    cursor.execute('''
                        UPDATE users 
                        SET failed_login_attempts = ?,
                            last_failed_login = CURRENT_TIMESTAMP,
                            account_locked_until = ?
                        WHERE username = ?
                    ''', (failed_attempts, lock_until.isoformat(), username))
                    conn.commit()
                    conn.close()
                    log_login_attempt(username, False, "Account locked after 5 failed attempts")
                    return False, None, "Account locked due to multiple failed attempts. Try again in 15 minutes."
                else:
                    cursor.execute('''
                        UPDATE users 
                        SET failed_login_attempts = ?,
                            last_failed_login = CURRENT_TIMESTAMP
                        WHERE username = ?
                    ''', (failed_attempts, username))
                    conn.commit()
                    conn.close()
                    log_login_attempt(username, False, f"Failed attempt {failed_attempts}")
                    return False, None, f"Invalid credentials. {5 - failed_attempts} attempts remaining."
            
            conn.close()
            log_login_attempt(username, False, "Invalid username")
            return False, None, "Invalid username or password!"
    except Exception as e:
        return False, None, f"Error: {str(e)}"

def detect_glucose_reading(image):
    """Use Gemini API to detect glucose readings"""
    try:
        # Ensure API is configured from session state
        if st.session_state.api_configured and st.session_state.api_key:
            genai.configure(api_key=st.session_state.api_key)
        
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = """
        Analyze this glucometer/glucose meter image carefully and extract the following information:
        
        1. Primary glucose reading value (the large number displayed)
        2. Unit of measurement (mg/dL, mmol/L, or %)
        3. Type of reading (Blood Glucose, HbA1c, etc.)
        4. Date and time if visible
        5. Any additional readings or indicators shown
        
        Respond in the following JSON format only:
        {
            "glucose_value": "numerical value only",
            "unit": "unit of measurement",
            "reading_type": "type of glucose reading",
            "date": "date if visible, else null",
            "time": "time if visible, else null",
            "additional_info": "any other relevant information"
        }
        
        Be precise and only extract what is clearly visible.
        """
        
        response = model.generate_content([prompt, image])
        response_text = response.text.strip()
        
        if response_text.startswith('```json'):
            response_text = response_text[7:-3]
        elif response_text.startswith('```'):
            response_text = response_text[3:-3]
        
        result = json.loads(response_text)
        return result, None
        
    except Exception as e:
        return None, str(e)

def save_patient(patient_data, created_by):
    """Save or update comprehensive patient information"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT patient_id FROM patients WHERE patient_id = ?', (patient_data['patient_id'],))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute('''
                UPDATE patients 
                SET name=?, age=?, gender=?, blood_group=?, phone=?, email=?, 
                    address=?, emergency_contact=?, emergency_phone=?, medical_history=?,
                    current_medications=?, allergies=?, diabetes_type=?, diagnosed_date=?,
                    height_cm=?, weight_kg=?, bmi=?, last_updated=CURRENT_TIMESTAMP
                WHERE patient_id=?
            ''', (
                patient_data['name'], patient_data['age'], patient_data['gender'],
                patient_data['blood_group'], patient_data['phone'], patient_data['email'],
                patient_data['address'], patient_data.get('emergency_contact'),
                patient_data.get('emergency_phone'), patient_data.get('medical_history'),
                patient_data.get('current_medications'), patient_data.get('allergies'),
                patient_data.get('diabetes_type'), patient_data.get('diagnosed_date'),
                patient_data.get('height_cm'), patient_data.get('weight_kg'),
                patient_data.get('bmi'), patient_data['patient_id']
            ))
            action = "PATIENT_UPDATED"
        else:
            cursor.execute('''
                INSERT INTO patients (
                    patient_id, name, age, gender, blood_group, phone, email, address,
                    emergency_contact, emergency_phone, medical_history, current_medications,
                    allergies, diabetes_type, diagnosed_date, height_cm, weight_kg, bmi, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                patient_data['patient_id'], patient_data['name'], patient_data['age'],
                patient_data['gender'], patient_data['blood_group'], patient_data['phone'],
                patient_data['email'], patient_data['address'], patient_data.get('emergency_contact'),
                patient_data.get('emergency_phone'), patient_data.get('medical_history'),
                patient_data.get('current_medications'), patient_data.get('allergies'),
                patient_data.get('diabetes_type'), patient_data.get('diagnosed_date'),
                patient_data.get('height_cm'), patient_data.get('weight_kg'),
                patient_data.get('bmi'), created_by
            ))
            action = "PATIENT_CREATED"
        
        conn.commit()
        conn.close()
        
        # Log activity after closing connection to avoid nested DB connections
        log_activity(created_by, action, f"{action}: {patient_data['patient_id']}")
        
        return True, "Patient information saved successfully!"
    except Exception as e:
        return False, f"Error: {str(e)}"

def save_reading(patient_id, glucose_data, uploaded_by, notes, image_bytes=None, context_data=None):
    """Save enhanced glucose reading with context"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current time in Bangalore timezone
        bangalore_tz = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(bangalore_tz)
        
        # Format date and time for storage
        current_date = current_time.strftime('%Y-%m-%d')
        current_time_str = current_time.strftime('%H:%M:%S')
        
        # Ensure uploaded_by is set from session if not provided
        if not uploaded_by and 'username' in st.session_state:
            uploaded_by = st.session_state.username
        
        cursor.execute('''
            INSERT INTO readings (
                patient_id, glucose_value, unit, reading_type, date, time,
                meal_context, activity_level, medication_taken, stress_level,
                additional_info, uploaded_by, notes, image_data, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            glucose_data.get('glucose_value'),
            glucose_data.get('unit'),
            glucose_data.get('reading_type'),
            current_date,  # Use current date in Bangalore time
            current_time_str,  # Use current time in Bangalore time
            context_data.get('meal_context') if context_data else None,
            context_data.get('activity_level') if context_data else None,
            context_data.get('medication_taken') if context_data else None,
            context_data.get('stress_level') if context_data else None,
            glucose_data.get('additional_info'),
            uploaded_by,  # This will be set from the parameter or session
            notes,
            image_bytes,
            current_time.isoformat()  # Store full timestamp with timezone info
        ))
        
        # Create alerts for abnormal readings
        try:
            glucose_value = float(glucose_data.get('glucose_value', 0))
            if glucose_value < 70 or glucose_value > 180:
                severity = "high" if glucose_value < 70 or glucose_value > 250 else "medium"
                alert_msg = f"Abnormal glucose reading: {glucose_value} {glucose_data.get('unit')}"
                
                cursor.execute('''
                    INSERT INTO alerts (patient_id, alert_type, message, severity)
                    VALUES (?, ?, ?, ?)
                ''', (patient_id, "Abnormal Reading", alert_msg, severity))
        except:
            pass
        
        conn.commit()
        conn.close()
        
        log_activity(uploaded_by, "READING_SAVED", f"Reading saved for patient: {patient_id}")
        return True, "Reading saved successfully!"
    except Exception as e:
        return False, f"Error: {str(e)}"

def get_patient_readings(patient_id, current_user=None):
    """Get all readings for a patient with role-based access control"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # If current_user is provided, check their role
    if current_user and current_user.get('role') != 'doctor':
        # For non-doctor users, only show their own data
        cursor.execute('''
            SELECT * FROM readings 
            WHERE patient_id = ? AND uploaded_by = ?
            ORDER BY timestamp DESC
        ''', (patient_id, current_user['username']))
    else:
        # Doctors can see all patient data
        cursor.execute('''
            SELECT * FROM readings 
            WHERE patient_id = ?
            ORDER BY timestamp DESC
        ''', (patient_id,))
    
    columns = [description[0] for description in cursor.description]
    readings = [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    conn.close()
    return readings

def get_patient_info(patient_id, current_user=None):
    """Get patient information with role-based access control"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Base query
    query = 'SELECT * FROM patients WHERE patient_id = ? AND is_active = 1'
    params = [patient_id]
    
    # Add role-based filtering
    if current_user and current_user.get('role') != 'doctor':
        query += ' AND created_by = ?'
        params.append(current_user['username'])
    
    cursor.execute(query, tuple(params))
    result = cursor.fetchone()
    
    if result:
        columns = [description[0] for description in cursor.description]
        patient = dict(zip(columns, result))
        conn.close()
        return patient
    
    conn.close()
    return None

def get_all_patients(current_user=None):
    """Get all active patients with role-based access control"""
    conn = get_db_connection()
    
    # Base query
    query = "SELECT * FROM patients WHERE is_active = 1"
    params = []
    
    # Add role-based filtering
    if current_user and current_user.get('role') != 'doctor':
        query += " AND created_by = ?"
        params.append(current_user['username'])
    
    query += " ORDER BY created_at DESC"
    
    # Execute query with parameters
    if params:
        df = pd.read_sql_query(query, conn, params=params)
    else:
        df = pd.read_sql_query(query, conn)
    
    conn.close()
    return df

def get_health_status(glucose_value, reading_type):
    """Determine health status based on glucose value"""
    try:
        value = float(glucose_value)
        
        if reading_type and ("HbA1c" in reading_type or "A1c" in reading_type):
            if value < 5.7:
                return "Normal", "🟢", "Good diabetes control", "#28a745"
            elif value < 6.5:
                return "Prediabetes", "🟡", "Increased risk - consult doctor", "#ffc107"
            else:
                return "Diabetes", "🔴", "Requires medical attention", "#dc3545"
        else:
            if value < 70:
                return "Low (Hypoglycemia)", "🔴", "Immediate attention needed", "#dc3545"
            elif value <= 100:
                return "Normal (Fasting)", "🟢", "Healthy range", "#28a745"
            elif value <= 125:
                return "Prediabetes Range", "🟡", "Monitor closely", "#ffc107"
            else:
                return "High (Hyperglycemia)", "🔴", "Consult healthcare provider", "#dc3545"
    except:
        return "Unknown", "⚪", "Unable to determine", "#6c757d"

def get_unread_alerts():
    """Get unread alerts count"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM alerts WHERE is_read = 0')
    count = cursor.fetchone()[0]
    conn.close()
    return count

# Enhanced Login/Registration Page
def auth_page():
    st.markdown('<h1 class="main-header">Advanced Glucometer Detection System</h1>', unsafe_allow_html=True)
    # Benefits panel before login
    info_c1, info_c2, info_c3 = st.columns([1, 2, 1])
    with info_c2:
        st.markdown('<div class="info-panel">', unsafe_allow_html=True)
        st.markdown('<div class="info-box"><div class="info-icon">🔎</div><p class="info-text">Access your health records<br/>in one place</p></div>', unsafe_allow_html=True)
        st.markdown('<div class="info-box"><div class="info-icon">📅</div><p class="info-text">Keep track of appointments<br/>and doctor visits</p></div>', unsafe_allow_html=True)
        st.markdown('<div class="info-box"><div class="info-icon">🧪</div><p class="info-text">View your medical records,<br/>lab and test results</p></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown('<div class="login-container"><div class="login-inner">', unsafe_allow_html=True)
        
        tab1, tab2, tab3 = st.tabs(["🔑 Login", "📝 Register", "Forgot Password"])
        
        with tab1:
            st.markdown("### Welcome Back")
            st.markdown("Please sign in to your account")

            with st.form("login_form"):
                username = st.text_input("Username", placeholder="Enter your username", key="login_username")
                password = st.text_input("Password", type="password", placeholder="Enter your password", key="login_password")
                
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    remember = st.checkbox("Remember me")
                with col_b:
                    submit = st.form_submit_button("🔑 Login", use_container_width=True)
                
                if submit:
                    if username and password:
                        with st.spinner("Authenticating..."):
                            time.sleep(0.5)  # Simulate processing
                            success, result, error_msg = login_user(username, password)
                            
                            if success:
                                st.session_state.logged_in = True
                                st.session_state.username = username
                                st.session_state.user_role = result[1]
                                st.session_state.user_full_name = result[2]
                                
                                # Redirect based on user role
                                if result[1] == 'patient':
                                    st.session_state.active_tab = "Dashboard"
                                
                                st.success(f"Welcome back, {result[2]}!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.session_state.login_attempts += 1
                                st.error(error_msg or "Invalid username or password!")
                    else:
                        st.warning("Please enter both username and password")
            
            # Additional login options
            st.markdown("---")
            st.markdown("#### Quick Demo Credentials")
            st.info("**Username:** demo_doctor | **Password:** demo123")
        
        with tab2:
            # Modern Registration Form Container
            st.markdown("""
            <div style="background: #f8f9fa; border-radius: 10px; padding: 2rem; margin-bottom: 2rem;">
                <div style="background: linear-gradient(90deg, #E6E6FA 0%, #ffffff 100%); border-radius: 12px; padding: 18px 20px; display: flex; align-items: center; gap: 12px; margin-bottom: 1.5rem;">
                    <div style="width: 36px; height: 36px; display:flex; align-items:center; justify-content:center; border-radius: 8px; background: rgba(102, 126, 234, 0.15); font-size: 20px;">🩺</div>
                    <div>
                        <h2 style="color: #2c3e50; margin: 0; font-weight: 700; font-size: 1.8rem; letter-spacing: 0.3px;">Create New Account</h2>
                        <p style="color: #566573; margin: 6px 0 0 0; font-size: 0.95rem;">Please fill in the details to create your account</p>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            st.markdown('<div class="form-card">', unsafe_allow_html=True)
            with st.form("register_form"):
                # Personal Information Section
                st.markdown("<div style='margin-bottom: 1.5rem;'>", unsafe_allow_html=True)
                
                # Full Name
                st.markdown("<label style='color: #2c3e50; font-weight: 500; margin-bottom: 0.5rem; display: block;'>Full Name <span style='color: #e74c3c;'>*</span></label>", unsafe_allow_html=True)
                full_name = st.text_input("", placeholder="Enter your full name", label_visibility="collapsed", key="reg_full_name")
                
                # Email and Phone in one row
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("<label style='color: #2c3e50; font-weight: 500; margin-bottom: 0.5rem; display: block;'>Email <span style='color: #e74c3c;'>*</span></label>", unsafe_allow_html=True)
                    email = st.text_input("", placeholder="your.email@example.com", label_visibility="collapsed", key="reg_email")
                
                with col2:
                    st.markdown("<label style='color: #2c3e50; font-weight: 500; margin-bottom: 0.5rem; display: block;'>Phone <span style='color: #e74c3c;'>*</span></label>", unsafe_allow_html=True)
                    phone = st.text_input("", placeholder="+91 1234567890", label_visibility="collapsed", key="reg_phone")
                
                # Username and Role in one row
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("<label style='color: #2c3e50; font-weight: 500; margin-bottom: 0.5rem; display: block;'>Username <span style='color: #e74c3c;'>*</span></label>", unsafe_allow_html=True)
                    username = st.text_input("", placeholder="Choose a username", label_visibility="collapsed", key="reg_username")
                
                with col2:
                    st.markdown("<label style='color: #2c3e50; font-weight: 500; margin-bottom: 0.5rem; display: block;'>Role <span style='color: #e74c3c;'>*</span></label>", unsafe_allow_html=True)
                    
                    # Role selection with all options including Patient
                    role = st.selectbox(
                        "",
                        options=["Select Role", "Doctor", "Nurse", "Admin", "Patient"],
                        index=0,
                        label_visibility="collapsed",
                        key="role_select_v2"
                    )
                    
                    # Show/hide specialization field based on role
                    if role in ["Doctor", "Nurse"]:
                        st.markdown("<label style='color: #2c3e50; font-weight: 500; margin-bottom: 0.5rem; display: block;'>Specialization</label>", unsafe_allow_html=True)
                        specialization = st.text_input(
                            "",
                            placeholder="e.g., Endocrinology",
                            label_visibility="collapsed",
                            key="reg_specialization",
                            help="Specialization (Optional)"
                        )
                    else:
                        specialization = ""
                
                # Specialization field will be conditionally shown based on role
                
                # Passwords
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("<label style='color: #2c3e50; font-weight: 500; margin-bottom: 0.5rem; display: block;'>Password <span style='color: #e74c3c;'>*</span></label>", unsafe_allow_html=True)
                    password = st.text_input("", type="password", placeholder="••••••••", label_visibility="collapsed", key="reg_password")
                
                with col2:
                    st.markdown("<label style='color: #2c3e50; font-weight: 500; margin-bottom: 0.5rem; display: block;'>Confirm Password <span style='color: #e74c3c;'>*</span></label>", unsafe_allow_html=True)
                    confirm_password = st.text_input("", type="password", placeholder="••••••••", label_visibility="collapsed", key="confirm_pass")
                
                # Password Strength Meter
                if password:
                    strength, score, feedback, color = check_password_strength(password)
                    st.markdown(f"""
                    <div style="margin: 10px 0 20px 0;">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px; font-size: 0.85rem;">
                            <span style="color: #7f8c8d;">Password Strength:</span>
                            <span style="font-weight: 500; color: {color};">{strength}</span>
                        </div>
                        <div style="height: 4px; background: #ecf0f1; border-radius: 2px; overflow: hidden; margin-bottom: 5px;">
                            <div style="width: {25 * score}%; height: 100%; background: {color}; transition: all 0.3s;"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                # Registration Progress (auth_page register)
                try:
                    required_flags = [
                        bool(full_name.strip()),
                        validate_email(email),
                        validate_phone(phone),
                        bool(username.strip()),
                        role != "Select Role",
                        len(password) >= 8,
                        password == confirm_password,
                    ]
                    progress_value = sum(required_flags)
                    total_steps = len(required_flags)
                    progress_ratio = progress_value / total_steps if total_steps else 0
                    st.progress(progress_ratio)
                    st.caption(f"Registration progress: {int(progress_ratio * 100)}%")
                except Exception:
                    pass
                
                # Terms and Conditions
                st.markdown("""
                <div style="background: #f1f8ff; border-left: 4px solid #3498db; padding: 12px; margin: 15px 0; border-radius: 4px;">
                    <div style="display: flex; align-items: flex-start; gap: 10px;">
                        <input type="checkbox" id="terms_check" style="margin-top: 3px;">
                        <label for="terms_check" style="color: #2c3e50; font-size: 0.9rem;">
                            I agree to the <a href="#" style="color: #3498db; text-decoration: none;">Terms of Service</a> and 
                            <a href="#" style="color: #3498db; text-decoration: none;">Privacy Policy</a>
                        </label>
                    </div>
                    <div style="display: flex; align-items: flex-start; gap: 10px; margin-top: 8px;">
                        <input type="checkbox" id="hipaa_check" style="margin-top: 3px;">
                        <label for="hipaa_check" style="color: #2c3e50; font-size: 0.9rem;">
                            I understand and will comply with HIPAA regulations
                        </label>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Submit Button
                submit = st.form_submit_button("📝 Register", 
                                            use_container_width=True, 
                                            type="primary",
                                            help="Click to create your account")
                
                # Form Submission Handling
                if submit:
                    agree_terms = st.session_state.get('terms_check', False)
                    agree_hipaa = st.session_state.get('hipaa_check', False)
                    errors = []
                    
                    # Validation
                    if not all([full_name, email, username, password, confirm_password, phone]):
                        errors.append("Please fill in all required fields")
                    
                    if role == "Select Role":
                        st.error("Please select a valid role")
                        return False
                    
                    if role == "Patient":
                        specialization = ""
                    
                    if not validate_email(email):
                        errors.append("Please enter a valid email address")
                    
                    if not validate_phone(phone):
                        errors.append("Please enter a valid phone number")
                    
                    if len(password) < 8:
                        errors.append("Password must be at least 8 characters long")
                    
                    if password != confirm_password:
                        errors.append("Passwords do not match")
                    
                    if not agree_terms or not agree_hipaa:
                        errors.append("Please agree to all terms and conditions")
                    
                    # Display errors or proceed
                    if errors:
                        st.error("\n\n".join([f"• {error}" for error in errors]))
                    else:
                        with st.spinner("Creating your account..."):
                            success, message = register_user(
                                username, password, email, full_name, 
                                role.lower(), phone, specialization
                            )
                            if success:
                                st.success("✅ Account created successfully!")
                                st.balloons()
                                st.session_state.active_tab = "Login"
                                st.rerun()
                            else:
                                st.error(f"❌ {message}")
                
                st.markdown("""
                <div style="text-align: center; margin-top: 1.5rem; color: #7f8c8d; font-size: 0.9rem;">
                    Already have an account? <a href="#" style="color: #3498db; text-decoration: none; font-weight: 500;">Sign In</a>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("</div>", unsafe_allow_html=True)  # Close form container
            st.markdown('</div>', unsafe_allow_html=True)  # Close form-card
        
        with tab3:
            st.markdown("### Reset Password")
            st.markdown("Enter your email to receive reset instructions")
            
            with st.form("forgot_password_form"):
                email = st.text_input("Email Address", placeholder="your@email.com")
                submit = st.form_submit_button("Send Reset Link", use_container_width=True)
                
                if submit:
                    if email and validate_email(email):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("SELECT username FROM users WHERE email = ?", (email,))
                        result = cursor.fetchone()
                        conn.close()
                        
                        if result:
                            st.success("Password reset instructions sent to your email!")
                            st.info("(Demo: Check your email for reset link)")
                        else:
                            st.error("Email not found in our system")
                    else:
                        st.error("Please enter a valid email address")
        
        st.markdown('</div></div>', unsafe_allow_html=True)
    
    # System status footer
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**System Status:** 🟢 Online")
    with col2:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        conn.close()
        st.markdown(f"**Registered Users:** {user_count}")
    with col3:
        st.markdown("**Version:** 2.0.0")

# Main Application
def main_app():
    # Sidebar
    with st.sidebar:
        st.markdown(f"""
        <div class="welcome-banner">
            <h2> Welcome</h2>
            <h3>{st.session_state.user_full_name}</h3>
            <p>{st.session_state.user_role.title()}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Alert notifications
        unread_alerts = get_unread_alerts()
        if unread_alerts > 0:
            st.markdown(f'<div class="alert-badge">🔔 {unread_alerts} New Alerts</div>', unsafe_allow_html=True)
        
        # Inactivity warning for patient accounts
        days_remaining, days_inactive = check_patient_inactivity_warning()
        if days_remaining is not None:
            if days_remaining > 0:
                st.warning(f"⚠️ **Account Inactivity Warning**\n\nYour account and all data will be automatically deleted in **{days_remaining} day(s)** due to inactivity. Please log in regularly to keep your account active.")
            else:
                st.error(f"🚨 **Critical Warning**\n\nYour account is scheduled for deletion today due to 30 days of inactivity. All your data will be permanently erased.")
        
        st.markdown("### Navigation")
        if 'active_tab' not in st.session_state:
            st.session_state.active_tab = "Dashboard"

        nav_items = [
            ("Dashboard", ""),
            ("Upload Reading", ""),
            ("Patient Management", ""),
            ("Analytics", ""),
            ("Appointments", ""),
            ("Alerts", ""),
            ("Reports", ""),
            ("Settings", ""),
        ]

        for label, icon in nav_items:
            is_active = (st.session_state.active_tab == label)
            btn = st.button(f"{icon} {label}", use_container_width=True, key=f"nav_{label}",
                            type=("primary" if is_active else "secondary"))
            if btn and not is_active:
                st.session_state.active_tab = label
                st.rerun()
        
        st.markdown("---")
        
        # Quick Stats
        st.markdown("### Quick Stats")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM patients WHERE is_active = 1")
        total_patients = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM readings WHERE DATE(timestamp) = DATE('now')")
        today_readings = cursor.fetchone()[0]
        conn.close()
        
        st.metric("Active Patients", total_patients)
        st.metric("Today's Readings", today_readings)
        
        st.markdown("---")
        
        # API Configuration Status
        st.markdown("### 🔑 API Status")
        if st.session_state.api_configured:
            st.success("✅ API Configured")
            if st.button("🔄 Reconfigure API", use_container_width=True):
                st.session_state.api_configured = False
                st.session_state.api_key = ""
                st.rerun()
        else:
            st.warning("⚠️ API Not Configured")
        
        st.markdown("---")
        
        if st.button("Logout", use_container_width=True):
            log_activity(st.session_state.username, "LOGOUT", "User logged out")
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.session_state.user_role = ""
            st.session_state.user_full_name = ""
            st.rerun()
    
    # Main content routing
    page = st.session_state.get('active_tab', 'Dashboard')
    if page == "Dashboard":
        dashboard_home()
    elif page == "Upload Reading":
        upload_reading_page()
    elif page == "Patient Management":
        patient_management_page()
    elif page == "Analytics":
        analytics_page()
    elif page == "Appointments":
        appointments_page()
    elif page == "Alerts":
        alerts_page()
    elif page == "Reports":
        reports_page()
    elif page == "Settings":
        settings_page()

def dashboard_home():
    st.title(" Dashboard Overview")
    
    # Add custom CSS for dashboard
    st.markdown("""
    <style>
    /* Reduce spacing between sections */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 1rem;
    }
    
    div[data-testid="stHorizontalBlock"] {
        gap: 0.8rem;
    }
    
    div[data-testid="column"] {
        padding: 0.5rem;
    }
    
    /* Enhanced metric styling */
    div[data-testid="stMetric"] {
        background: white;
        padding: 1rem;
        border-radius: 10px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        transition: all 0.2s ease;
    }
    
    div[data-testid="stMetric"]:hover {
        transform: scale(1.02);
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }
    
    /* Chart container styling */
    div[data-testid="stPlotlyChart"] {
        background: white;
        padding: 1rem;
        border-radius: 12px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        transition: all 0.2s ease;
    }
    
    div[data-testid="stPlotlyChart"]:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }
    
    /* Expander styling */
    div[data-testid="stExpander"] {
        background: white;
        border-radius: 10px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        margin-bottom: 0.5rem;
        transition: all 0.2s ease;
    }
    
    div[data-testid="stExpander"]:hover {
        transform: scale(1.01);
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }
    
    /* Reduce markdown spacing */
    .element-container {
        margin-bottom: 0.5rem;
    }
    
    hr {
        margin: 1rem 0;
    }
    
    /* Subheader styling */
    h3 {
        margin-top: 0.5rem;
        margin-bottom: 1rem;
    }
    
    /* Subtle section separator */
    .section-sep {
        height: 1px;
        width: 100%;
        background: linear-gradient(to right, rgba(0,0,0,0.00), rgba(0,0,0,0.08), rgba(0,0,0,0.00));
        box-shadow: 0 1px 0 rgba(0,0,0,0.04);
        margin: 0.75rem 0 1rem 0;
        border-radius: 1px;
    }

    /* Smooth section transitions */
    @keyframes fadeIn {
        from { opacity: 0 }
        to { opacity: 1 }
    }
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(6px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @keyframes growIn {
        from { opacity: 0; transform: scale(0.98); }
        to { opacity: 1; transform: scale(1); }
    }
    
    /* Apply to common Streamlit blocks */
    div[data-testid="stMetric"] { animation: fadeInUp 0.35s ease both; }
    div[data-testid="stPlotlyChart"] { animation: growIn 0.45s ease both; }
    div[data-testid="stExpander"] { animation: fadeInUp 0.35s ease both; }
    .section-sep { animation: fadeIn 0.3s ease both; }
    
    /* Respect reduced motion preferences */
    @media (prefers-reduced-motion: reduce) {
        div[data-testid="stMetric"],
        div[data-testid="stPlotlyChart"],
        div[data-testid="stExpander"],
        .section-sep { animation: none !important; }
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Get current user info
    current_user = {
        'username': st.session_state.get('username'),
        'role': st.session_state.get('user_role')
    }
    
    # Add interactive filters in sidebar
    with st.sidebar:
        st.markdown("### 🔍 Dashboard Filters")
        # Dark mode toggle
        if 'dark_mode' not in st.session_state:
            st.session_state.dark_mode = False
        st.session_state.dark_mode = st.toggle("🌙 Dark mode", value=st.session_state.dark_mode)
        
        date_range = st.selectbox(
            "Time Period",
            ["Today", "Last 7 Days", "Last 30 Days", "Last 90 Days", "All Time"],
            index=2
        )
        
        # Calculate date filter
        if date_range == "Today":
            days_back = 0
        elif date_range == "Last 7 Days":
            days_back = 7
        elif date_range == "Last 30 Days":
            days_back = 30
        elif date_range == "Last 90 Days":
            days_back = 90
        else:
            days_back = None
        
        show_charts = st.checkbox("Show Advanced Charts", value=True)
        auto_refresh = st.checkbox("Auto Refresh (30s)", value=False)
        
        if auto_refresh:
            st.info("Dashboard will refresh in 30 seconds")
            time.sleep(30)
            st.rerun()
    
    # Dynamic chart template based on theme
    chart_template = 'plotly_dark' if st.session_state.get('dark_mode') else 'plotly_white'
    
    # Optional CSS overrides for dark mode
    if st.session_state.get('dark_mode'):
        st.markdown("""
        <style>
        body, .block-container {
            background-color: #0f1117 !important;
            color: #e6e6e6 !important;
        }
        div[data-testid="stMetric"],
        .dashboard-card,
        div[data-testid="stPlotlyChart"],
        div[data-testid="stExpander"] {
            background: #1b1f2a !important;
            color: #e6e6e6 !important;
        }
        h1, h2, h3, h4, h5, h6, p, span, label {
            color: #e6e6e6 !important;
        }
        </style>
        """, unsafe_allow_html=True)
    
    # Get database connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Base queries with role-based filtering
    patient_condition = ""
    reading_condition = ""
    alert_condition = ""
    params = []
    
    if current_user.get('role') != 'doctor':
        # For non-doctors, only show data they've created or are associated with
        patient_condition = " AND p.created_by = ?"
        reading_condition = " AND r.uploaded_by = ?"
        alert_condition = " AND a.acknowledged_by = ?"
        params = [current_user['username']] * 3
    
    # Get statistics with role-based filtering
    cursor.execute(f"""
        SELECT COUNT(*) 
        FROM patients p 
        WHERE p.is_active = 1 {patient_condition}
    """, params[:1] if params else [])
    total_patients = cursor.fetchone()[0]
    
    cursor.execute(f"""
        SELECT COUNT(*) 
        FROM readings r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE 1=1 {reading_condition}
    """, params[1:2] if params else [])
    total_readings = cursor.fetchone()[0]
    
    cursor.execute(f"""
        SELECT COUNT(*) 
        FROM readings r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE DATE(r.timestamp) = DATE('now') {reading_condition}
    """, params[1:2] if params else [])
    today_readings = cursor.fetchone()[0]
    
    cursor.execute(f"""
        SELECT COUNT(*) 
        FROM alerts a
        WHERE is_read = 0 {alert_condition}
    """, params[2:3] if params else [])
    unread_alerts = cursor.fetchone()[0]
    
    # Get today's readings with patient info and role-based filtering
    today_readings_query = """
        SELECT r.*, p.name as patient_name
        FROM readings r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE DATE(datetime(r.timestamp, 'localtime')) = DATE('now', 'localtime')
    """
    
    if current_user.get('role') != 'doctor':
        today_readings_query += " AND r.uploaded_by = ?"
        
    today_readings_query += " ORDER BY r.timestamp DESC"
    
    df_today_readings = pd.read_sql_query(
        today_readings_query,
        conn,
        params=([current_user['username']]) if current_user.get('role') != 'doctor' else []
    )
    
    # Convert timestamp to datetime with timezone
    if not df_today_readings.empty:
        df_today_readings['timestamp'] = pd.to_datetime(
            df_today_readings['timestamp'], 
            format='mixed',
            utc=True
        ).dt.tz_convert('Asia/Kolkata')
    
    # Get critical alerts with timezone handling and role-based filtering
    alerts_query = """
        SELECT a.*, p.name as patient_name 
        FROM alerts a
        LEFT JOIN patients p ON a.patient_id = p.patient_id
        WHERE a.severity = 'high' AND a.is_read = 0 
    """
    
    if current_user.get('role') != 'doctor':
        alerts_query += " AND a.acknowledged_by = ?"
        
    alerts_query += " ORDER BY a.created_at DESC LIMIT 5"
    
    df_alerts = pd.read_sql_query(
        alerts_query,
        conn,
        params=([current_user['username']]) if current_user.get('role') != 'doctor' else []
    )
    
    # Convert alert timestamps to datetime with timezone
    if not df_alerts.empty and 'created_at' in df_alerts.columns:
        df_alerts['created_at'] = pd.to_datetime(
            df_alerts['created_at'],
            format='mixed',
            utc=True,
            errors='coerce'  # Convert parsing errors to NaT
        )
        # Only convert timezone if the datetime is timezone-naive
        df_alerts['created_at'] = df_alerts['created_at'].apply(
            lambda x: x.tz_convert('Asia/Kolkata') if x.tz is not None 
                     else x.tz_localize('UTC').tz_convert('Asia/Kolkata') if pd.notna(x) 
                     else x
        )
    
    # Get recent readings with timezone handling and role-based filtering
    recent_readings_query = """
        SELECT r.id, r.patient_id, r.glucose_value, r.meal_context, 
               r.notes, r.timestamp, r.uploaded_by, r.image_data,
               p.name as patient_name
        FROM readings r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE p.is_active = 1
    """
    
    if current_user.get('role') != 'doctor':
        recent_readings_query += " AND r.uploaded_by = ?"
        
    recent_readings_query += " ORDER BY r.timestamp DESC LIMIT 10"
    
    df_recent = pd.read_sql_query(
        recent_readings_query,
        conn,
        params=([current_user['username']]) if current_user.get('role') != 'doctor' else []
    )
    
    # Convert timestamp to datetime with explicit format and handle timezone
    df_recent['timestamp'] = pd.to_datetime(
        df_recent['timestamp'], 
        format='mixed',  # Handle multiple timestamp formats
        utc=True        # Treat naive timestamps as UTC
    )
    # Convert to Bangalore timezone
    df_recent['timestamp'] = df_recent['timestamp'].dt.tz_convert('Asia/Kolkata')
    
    # Get glucose level distribution with role-based filtering
    glucose_dist_query = """
        SELECT 
            CASE 
                WHEN r.glucose_value < 70 THEN 'Low (<70)'
                WHEN r.glucose_value < 100 THEN 'Normal (70-99)'
                WHEN r.glucose_value < 126 THEN 'Prediabetes (100-125)'
                ELSE 'Diabetes (126+)' 
            END as glucose_range,
            COUNT(*) as count
        FROM readings r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE r.glucose_value IS NOT NULL
          AND DATE(r.timestamp) >= DATE('now', '-30 days')
    """
    
    if current_user.get('role') != 'doctor':
        glucose_dist_query += " AND r.uploaded_by = ?"
        
    glucose_dist_query += """
        GROUP BY glucose_range
        ORDER BY 
            CASE 
                WHEN glucose_range = 'Low (<70)' THEN 1
                WHEN glucose_range = 'Normal (70-99)' THEN 2
                WHEN glucose_range = 'Prediabetes (100-125)' THEN 3
                ELSE 4
            END
    """
    
    df_glucose_dist = pd.read_sql_query(
        glucose_dist_query,
        conn,
        params=([current_user['username']]) if current_user.get('role') != 'doctor' else []
    )
    
    # Enhanced Top Metrics Row with dynamic deltas
    st.markdown("### 📈 Key Metrics", unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)

    # Calculate previous period metrics for comparison
    cursor.execute(f"""
        SELECT COUNT(*) 
        FROM readings r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE DATE(r.timestamp) = DATE('now', '-1 day') {reading_condition}
    """, params[1:2] if params else [])
    yesterday_readings = cursor.fetchone()[0]
    
    # Calculate average glucose for the period
    cursor.execute(f"""
        SELECT AVG(r.glucose_value)
        FROM readings r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE r.glucose_value IS NOT NULL {reading_condition}
    """, params[1:2] if params else [])
    avg_glucose = cursor.fetchone()[0] or 0
    
    with col1:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.metric("👥 Total Patients", f"{total_patients:,}", 
                 delta=f"{total_patients}" if total_patients > 0 else "0",
                 delta_color="normal")
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col2:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.metric("📊 Total Readings", f"{total_readings:,}",
                 delta=f"+{today_readings} today" if today_readings > 0 else "0 today")
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col3:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        delta_readings = today_readings - yesterday_readings
        st.metric("📅 Today's Readings", today_readings, 
                 delta=f"{delta_readings:+d} from yesterday" if delta_readings != 0 else "Same as yesterday")
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col4:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.metric("⚠️ Unread Alerts", unread_alerts, 
                 delta="Needs attention" if unread_alerts > 0 else "All clear",
                 delta_color="inverse")
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Add secondary metrics row
    st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
    col5, col6, col7, col8 = st.columns(4)
    
    with col5:
        st.metric("🩸 Avg Glucose", f"{avg_glucose:.1f} mg/dL",
                 delta="Normal" if 70 <= avg_glucose <= 100 else "Check levels")
    
    with col6:
        # Calculate readings this week
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM readings r
            JOIN patients p ON r.patient_id = p.patient_id
            WHERE DATE(r.timestamp) >= DATE('now', '-7 days') {reading_condition}
        """, params[1:2] if params else [])
        week_readings = cursor.fetchone()[0]
        st.metric("📆 This Week", f"{week_readings:,} readings",
                 delta=f"{week_readings/7:.1f} per day")
    
    with col7:
        # Calculate high glucose readings
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM readings r
            JOIN patients p ON r.patient_id = p.patient_id
            WHERE r.glucose_value > 180 {reading_condition}
        """, params[1:2] if params else [])
        high_readings = cursor.fetchone()[0]
        st.metric("🔴 High Readings", high_readings,
                 delta="Above 180 mg/dL", delta_color="inverse")
    
    with col8:
        # Calculate low glucose readings
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM readings r
            JOIN patients p ON r.patient_id = p.patient_id
            WHERE r.glucose_value < 70 {reading_condition}
        """, params[1:2] if params else [])
        low_readings = cursor.fetchone()[0]
        st.metric("🔵 Low Readings", low_readings,
                 delta="Below 70 mg/dL", delta_color="inverse")
    
    st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
    
    # Interactive Charts Section
    if show_charts:
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.subheader(" Glucose Level Distribution")
            if not df_glucose_dist.empty:
                # Create interactive pie chart
                fig_pie = px.pie(
                    df_glucose_dist,
                    values='count',
                    names='glucose_range',
                    color='glucose_range',
                    color_discrete_map={
                        'Low (<70)': '#ff4b4b',
                        'Normal (70-99)': '#4caf50',
                        'Prediabetes (100-125)': '#ff9800',
                        'Diabetes (126+)': '#f44336'
                    },
                    hole=0.4,
                    template=chart_template
                )
                
                fig_pie.update_traces(
                    textposition='inside',
                    textinfo='percent+label',
                    hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>'
                )
                
                fig_pie.update_layout(
                    showlegend=True,
                    height=350,
                    margin=dict(l=20, r=20, t=30, b=20)
                )
                
                st.plotly_chart(fig_pie, use_container_width=True)
                st.caption("Based on last 30 days")
            else:
                st.info("No glucose distribution data available")
        
        with col_chart2:
            st.subheader(" Glucose Trend (Last 30 Days)")
            # Get glucose trend data
            trend_query = """
                SELECT DATE(r.timestamp) as date, 
                       AVG(r.glucose_value) as avg_glucose,
                       MIN(r.glucose_value) as min_glucose,
                       MAX(r.glucose_value) as max_glucose
                FROM readings r
                JOIN patients p ON r.patient_id = p.patient_id
                WHERE r.glucose_value IS NOT NULL
                AND DATE(r.timestamp) >= DATE('now', '-30 days')
            """
            
            if current_user.get('role') != 'doctor':
                trend_query += " AND r.uploaded_by = ?"
                
            trend_query += " GROUP BY DATE(r.timestamp) ORDER BY date"
            
            df_trend = pd.read_sql_query(
                trend_query,
                conn,
                params=([current_user['username']]) if current_user.get('role') != 'doctor' else []
            )
            
            if not df_trend.empty:
                fig_trend = go.Figure()
                
                # Add average line
                fig_trend.add_trace(go.Scatter(
                    x=df_trend['date'],
                    y=df_trend['avg_glucose'],
                    mode='lines+markers',
                    name='Average',
                    line=dict(color='#1f77b4', width=3),
                    marker=dict(size=8),
                    hovertemplate='%{x|%b %d}: Avg Glucose %{y:.0f} mg/dL<extra></extra>'
                ))
                
                # Add range area
                fig_trend.add_trace(go.Scatter(
                    x=df_trend['date'],
                    y=df_trend['max_glucose'],
                    mode='lines',
                    name='Max',
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo='skip'
                ))
                
                fig_trend.add_trace(go.Scatter(
                    x=df_trend['date'],
                    y=df_trend['min_glucose'],
                    mode='lines',
                    name='Range',
                    fill='tonexty',
                    fillcolor='rgba(31, 119, 180, 0.2)',
                    line=dict(width=0),
                    hoverinfo='skip'
                ))
                
                # Highlight anomalies on the average line
                df_high = df_trend[df_trend['avg_glucose'] > 180]
                if not df_high.empty:
                    fig_trend.add_trace(go.Scatter(
                        x=df_high['date'],
                        y=df_high['avg_glucose'],
                        mode='markers',
                        name='High (>180)',
                        marker=dict(color='red', size=10, symbol='circle'),
                        hovertemplate='%{x|%b %d}: Avg Glucose %{y:.0f} mg/dL<extra></extra>'
                    ))
                df_low = df_trend[df_trend['avg_glucose'] < 70]
                if not df_low.empty:
                    fig_trend.add_trace(go.Scatter(
                        x=df_low['date'],
                        y=df_low['avg_glucose'],
                        mode='markers',
                        name='Low (<70)',
                        marker=dict(color='blue', size=10, symbol='diamond'),
                        hovertemplate='%{x|%b %d}: Avg Glucose %{y:.0f} mg/dL<extra></extra>'
                    ))

                # Add target range lines
                fig_trend.add_hline(y=70, line_dash="dash", line_color="red", 
                                   annotation_text="Low (70)", annotation_position="right")
                fig_trend.add_hline(y=180, line_dash="dash", line_color="orange", 
                                   annotation_text="High (180)", annotation_position="right")
                
                # Light grid background for readability
                fig_trend.update_xaxes(showgrid=True, gridcolor='rgba(0,0,0,0.05)')
                fig_trend.update_yaxes(showgrid=True, gridcolor='rgba(0,0,0,0.05)', title='Glucose (mg/dL)')

                fig_trend.update_layout(
                    height=350,
                    margin=dict(l=20, r=20, t=30, b=20),
                    xaxis_title="Date",
                    hovermode='x unified',
                    template=chart_template
                )
                
                st.plotly_chart(fig_trend, use_container_width=True)
            else:
                st.info("No trend data available")
        
        st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
        
        # Additional interactive charts
        col_chart3, col_chart4 = st.columns(2)
        
        with col_chart3:
            st.subheader(" Readings by Time of Day")
            # Get readings by hour
            hour_query = """
                SELECT 
                    CAST(strftime('%H', r.timestamp) AS INTEGER) as hour,
                    COUNT(*) as count,
                    AVG(r.glucose_value) as avg_glucose
                FROM readings r
                JOIN patients p ON r.patient_id = p.patient_id
                WHERE r.glucose_value IS NOT NULL
            """
            
            if current_user.get('role') != 'doctor':
                hour_query += " AND r.uploaded_by = ?"
                
            hour_query += " GROUP BY hour ORDER BY hour"
            
            df_hour = pd.read_sql_query(
                hour_query,
                conn,
                params=([current_user['username']]) if current_user.get('role') != 'doctor' else []
            )
            
            if not df_hour.empty:
                fig_hour = go.Figure()
                
                fig_hour.add_trace(go.Bar(
                    x=df_hour['hour'],
                    y=df_hour['count'],
                    name='Reading Count',
                    marker_color='lightblue',
                    yaxis='y',
                    hovertemplate='Hour: %{x}:00<br>Readings: %{y}<extra></extra>'
                ))
                
                fig_hour.add_trace(go.Scatter(
                    x=df_hour['hour'],
                    y=df_hour['avg_glucose'],
                    name='Avg Glucose',
                    mode='lines+markers',
                    marker_color='red',
                    yaxis='y2',
                    hovertemplate='Hour: %{x}:00<br>Avg: %{y:.1f} mg/dL<extra></extra>'
                ))
                
                fig_hour.update_layout(
                    height=350,
                    margin=dict(l=20, r=20, t=30, b=20),
                    xaxis_title="Hour of Day",
                    yaxis=dict(title="Number of Readings", side='left'),
                    yaxis2=dict(title="Avg Glucose (mg/dL)", side='right', overlaying='y'),
                    hovermode='x unified',
                    template='plotly_white',
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                
                st.plotly_chart(fig_hour, use_container_width=True)
            else:
                st.info("No hourly data available")
        
        with col_chart4:
            st.subheader(" Readings by Meal Context")
            # Get readings by meal context
            meal_query = """
                SELECT 
                    COALESCE(r.meal_context, 'Unknown') as meal_context,
                    COUNT(*) as count,
                    AVG(r.glucose_value) as avg_glucose
                FROM readings r
                JOIN patients p ON r.patient_id = p.patient_id
                WHERE r.glucose_value IS NOT NULL
            """
            
            if current_user.get('role') != 'doctor':
                meal_query += " AND r.uploaded_by = ?"
                
            meal_query += " GROUP BY meal_context ORDER BY count DESC"
            
            df_meal = pd.read_sql_query(
                meal_query,
                conn,
                params=([current_user['username']]) if current_user.get('role') != 'doctor' else []
            )
            
            if not df_meal.empty:
                fig_meal = px.bar(
                    df_meal,
                    x='meal_context',
                    y='count',
                    color='avg_glucose',
                    color_continuous_scale='RdYlGn_r',
                    labels={'count': 'Number of Readings', 'meal_context': 'Meal Context', 
                           'avg_glucose': 'Avg Glucose'},
                    template='plotly_white',
                    text='count'
                )
                
                fig_meal.update_traces(
                    textposition='outside',
                    hovertemplate='<b>%{x}</b><br>Readings: %{y}<br>Avg Glucose: %{marker.color:.1f} mg/dL<extra></extra>'
                )
                
                fig_meal.update_layout(
                    height=350,
                    margin=dict(l=20, r=20, t=30, b=20),
                    xaxis_title="Meal Context",
                    yaxis_title="Number of Readings",
                    showlegend=False
                )
                
                st.plotly_chart(fig_meal, use_container_width=True)
            else:
                st.info("No meal context data available")
    
    st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
    
    # Quick Patient Overview
    col_action1, = st.columns([1])
    
    with col_action1:
        st.subheader("📋 Quick Patient Overview")
        # Get patient summary
        patient_summary_query = """
            SELECT 
                p.patient_id,
                p.name,
                COUNT(r.id) as reading_count,
                MAX(r.timestamp) as last_reading,
                AVG(r.glucose_value) as avg_glucose
            FROM patients p
            LEFT JOIN readings r ON p.patient_id = r.patient_id
            WHERE p.is_active = 1
        """
        
        if current_user.get('role') != 'doctor':
            patient_summary_query += " AND p.created_by = ?"
            
        patient_summary_query += " GROUP BY p.patient_id, p.name ORDER BY last_reading DESC LIMIT 5"
        
        df_patient_summary = pd.read_sql_query(
            patient_summary_query,
            conn,
            params=([current_user['username']]) if current_user.get('role') != 'doctor' else []
        )
        
        if not df_patient_summary.empty:
            for _, patient in df_patient_summary.iterrows():
                status_color = "#4caf50" if 70 <= (patient['avg_glucose'] or 0) <= 100 else "#ff9800"
                last_reading_str = pd.to_datetime(patient['last_reading']).strftime('%b %d, %H:%M') if pd.notna(patient['last_reading']) else 'No readings'
                
                with st.expander(f"👤 {patient['name']} ({patient['patient_id']})", expanded=False):
                    col_p1, col_p2, col_p3 = st.columns(3)
                    with col_p1:
                        st.metric("Total Readings", patient['reading_count'])
                    with col_p2:
                        st.metric("Avg Glucose", f"{patient['avg_glucose']:.1f} mg/dL" if pd.notna(patient['avg_glucose']) else "N/A")
                    with col_p3:
                        st.write(f"**Last Reading:**")
                        st.write(last_reading_str)
        else:
            st.info("No patients found")
    
    
    st.markdown('<div class="section-sep"></div>', unsafe_allow_html=True)
    st.subheader(" Today's Glucose Readings")
    
    if not df_today_readings.empty:
        # Add status and color based on glucose value
        status_info = df_today_readings['glucose_value'].apply(
            lambda x: get_health_status(x, 'fasting') if pd.notna(x) else ("Unknown", "⚪", "", "#6c757d")
        )
        df_today_readings[['status', 'status_icon', 'status_text', 'status_color']] = pd.DataFrame(
            status_info.tolist(), index=df_today_readings.index
        )
        
        # Display each reading in a card
        for _, reading in df_today_readings.iterrows():
            time_str = reading['timestamp'].strftime('%H:%M')
            html_content = f"""
            <div style="margin-bottom: 15px; padding: 15px; border-radius: 8px; 
                        background-color: #f8f9fa; border-left: 4px solid {reading['status_color']};">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div>
                        <span style="font-size: 1.1em; font-weight: 600;">{reading['patient_name']}</span>
                        <span style="margin-left: 10px; font-size: 0.9em; color: #6c757d;">
                        {reading['timestamp'].strftime('%b %d, %H:%M')}
                    </span>
                    </div>
                    <div style="font-size: 1.2em; font-weight: 700; color: {reading['status_color']};">
                        {reading['glucose_value']} mg/dL
                    </div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="background-color: {reading['status_color']}15; 
                                     color: {reading['status_color']}; 
                                     padding: 3px 8px; 
                                     border-radius: 12px;
                                     font-size: 0.85em;">
                            {reading['status_icon']} {reading['status']}
                        </span>
                    </div>
                    <div style="font-size: 0.9em; color: #6c757d;">
                        {reading.get('meal_context', 'No context').title()}
                    </div>
                </div>
            </div>
            """
            st.markdown(html_content, unsafe_allow_html=True)
    else:
        st.info("No glucose readings recorded today")
    
    # Add a divider before critical alerts
    st.markdown("---")
    
    # Critical Alerts Section
    st.subheader("Critical Alerts")
    if not df_alerts.empty:
        for _, alert in df_alerts.iterrows():
            patient_name = alert.get('patient_name', alert['patient_id'])
            alert_html = f"""
            <div style="padding: 12px; border-radius: 5px; margin-bottom: 10px; 
                        background-color: #f8d7da; border-left: 4px solid #dc3545;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                    <strong style="color: #721c24;">{patient_name}</strong>
                    <span style="font-size: 0.9em; color: #721c24;">
                        {alert['created_at'].strftime('%b %d, %H:%M') if pd.notna(alert['created_at']) else 'N/A'}
                    </span>
                </div>
                <div style="color: #721c24;">{alert['message']}</div>
            </div>
            """
            st.markdown(alert_html, unsafe_allow_html=True)
    else:
        st.success("No critical alerts")
    
    # Display recent readings in a clean format
    st.markdown("---")
    st.subheader("Recent Readings")
    
    if not df_recent.empty:
        # Format the already timezone-aware timestamp
        df_recent['time_ago'] = df_recent['timestamp'].dt.strftime('%b %d, %H:%M')
        
        for _, row in df_recent.iterrows():
            st.markdown(f"""
            <div style="margin-bottom: 15px; padding: 10px; background: #f8f9fa; border-radius: 5px;">
                <div style="display: flex; justify-content: space-between;">
                    <strong>{row['patient_name']}</strong>
                    <span style="color: #6c757d; font-size: 0.9em;">{row['time_ago']}</span>
                </div>
                <div>Glucose: <strong>{row['glucose_value']} mg/dL</strong> • {row['meal_context']}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No recent readings available")
    
    # Close the database connection
    conn.close()
    
def upload_reading_page():
    st.title("Upload Glucometer Reading")
    
    # Get current user info
    current_user = {
        'username': st.session_state.get('username'),
        'role': st.session_state.get('user_role')
    }
    
    # Patient selection
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Select Patient")
        
        df_patients = get_all_patients(current_user)
        patient_options = ["Add New Patient"] + df_patients['patient_id'].tolist() if not df_patients.empty else ["Add New Patient"]
        
        selected_patient = st.selectbox("Patient ID", patient_options)
        
        if selected_patient == "Add New Patient":
            with st.expander("Add New Patient", expanded=True):
                with st.form("new_patient_form"):
                    patient_id = st.text_input("Patient ID*", placeholder="P001")
                    patient_name = st.text_input("Name*")
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        age = st.number_input("Age*", 1, 120, 30)
                        gender = st.selectbox("Gender", ["Male", "Female", "Other"])
                    with col_b:
                        blood_group = st.selectbox("Blood Group", ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"])
                        diabetes_type = st.selectbox("Diabetes Type", ["Type 1", "Type 2", "Gestational", "Prediabetes"])
                    
                    phone = st.text_input("Phone*")
                    email = st.text_input("Email")
                    
                    col_c, col_d = st.columns(2)
                    with col_c:
                        height = st.number_input("Height (cm)", 0.0, 300.0, 170.0)
                        weight = st.number_input("Weight (kg)", 0.0, 300.0, 70.0)
                    with col_d:
                        if height > 0 and weight > 0:
                            bmi = weight / ((height/100) ** 2)
                            st.metric("BMI", f"{bmi:.1f}")
                    
                    emergency_contact = st.text_input("Emergency Contact Name")
                    emergency_phone = st.text_input("Emergency Phone")
                    
                    address = st.text_area("Address")
                    medical_history = st.text_area("Medical History")
                    current_medications = st.text_area("Current Medications")
                    allergies = st.text_area("Allergies")
                    
                    diagnosed_date = st.date_input("Diabetes Diagnosed Date")
                    
                    submit = st.form_submit_button("Save Patient")
                    
                    if submit:
                        if patient_id and patient_name and phone:
                            patient_data = {
                                'patient_id': patient_id,
                                'name': patient_name,
                                'age': age,
                                'gender': gender,
                                'blood_group': blood_group,
                                'phone': phone,
                                'email': email,
                                'address': address,
                                'emergency_contact': emergency_contact,
                                'emergency_phone': emergency_phone,
                                'medical_history': medical_history,
                                'current_medications': current_medications,
                                'allergies': allergies,
                                'diabetes_type': diabetes_type,
                                'diagnosed_date': diagnosed_date,
                                'height_cm': height,
                                'weight_kg': weight,
                                'bmi': bmi if height > 0 and weight > 0 else None
                            }
                            
                            success, msg = save_patient(patient_data, st.session_state.username)
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                        else:
                            st.error("Please fill required fields")
        else:
            patient_id = selected_patient
            patient_info = get_patient_info(patient_id)
            if patient_info:
                st.markdown(f"""
                <div class="info-card">
                <strong>{patient_info['name']}</strong><br>
                Age: {patient_info['age']} | Gender: {patient_info['gender']}<br>
                Blood Group: {patient_info['blood_group']} | Type: {patient_info.get('diabetes_type', 'N/A')}
                </div>
                """, unsafe_allow_html=True)
    
    with col2:
        st.subheader("Upload Image")
        
        upload_method = st.radio("Method:", ["Upload Image", "Camera Capture"], horizontal=True)
        
        image = None
        image_bytes = None
        
        if upload_method == "Upload Image":
            st.info("📱 **Mobile users:** You can select from your camera roll or take a new photo!")
            uploaded_file = st.file_uploader(
                "Choose image", 
                type=['png', 'jpg', 'jpeg'],
                help="Select a glucometer image from your device. Mobile users can use camera or gallery."
            )
            if uploaded_file:
                image = Image.open(uploaded_file)
                image_bytes = uploaded_file.getvalue()
        else:
            st.info("📸 **Camera mode:** Take a clear photo of your glucometer display")
            camera_image = st.camera_input("Take picture")
            if camera_image:
                image = Image.open(camera_image)
                image_bytes = camera_image.getvalue()
    
    if image:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.image(image, caption="Glucometer Image", use_container_width=True)
        
        with col2:
            # Context information
            st.subheader("Reading Context")
            
            with st.form("context_form"):
                meal_context = st.selectbox("Meal Context", ["Fasting", "Before Meal", "After Meal", "Random"])
                activity_level = st.selectbox("Activity Level", ["Resting", "Light Activity", "Moderate Activity", "Intense Activity"])
                medication_taken = st.checkbox("Medication Taken")
                stress_level = st.selectbox("Stress Level", ["Low", "Normal", "High"])
                notes = st.text_area("Notes")
                
                submit = st.form_submit_button("Detect & Save", type="primary", use_container_width=True)
                
                if submit:
                    if selected_patient == "Add New Patient":
                        st.error("Please save patient first!")
                    else:
                        with st.spinner("Analyzing with AI..."):
                            result, error = detect_glucose_reading(image)
                            
                            if error:
                                st.error(f"Error: {error}")
                            elif result:
                                st.success("Reading detected!")
                                
                                glucose_value = result.get('glucose_value', 'N/A')
                                unit = result.get('unit', 'N/A')
                                reading_type = result.get('reading_type', 'Blood Glucose')
                                
                                st.metric(reading_type, f"{glucose_value} {unit}")
                                
                                status, emoji, message, color = get_health_status(glucose_value, reading_type)
                                st.markdown(f"**{emoji} Status:** <span style='color:{color}'>{status}</span>", unsafe_allow_html=True)
                                st.info(message)
                                
                                context_data = {
                                    'meal_context': meal_context,
                                    'activity_level': activity_level,
                                    'medication_taken': 1 if medication_taken else 0,
                                    'stress_level': stress_level
                                }
                                
                                success, msg = save_reading(
                                    patient_id,
                                    result,
                                    st.session_state.username,
                                    notes,
                                    image_bytes,
                                    context_data
                                )
                                
                                if success:
                                    st.success(msg)
                                    st.balloons()
                                else:
                                    st.error(msg)

def patient_management_page():
    st.title("Patient Management")
    
    # Get current user info from session state
    current_user = {
        'username': st.session_state.get('username'),
        'role': st.session_state.get('user_role')
    }
    
    # For non-doctors, show a message if they try to access patient management
    if current_user.get('role') not in ['doctor', 'admin']:
        st.warning("You don't have permission to access patient management.")
        return
        
    tab1, tab2, tab3 = st.tabs(["All Patients", "Search Patient", "Patient Details"])
    
    with tab1:
        st.subheader("All Registered Patients")
        df_patients = get_all_patients(current_user)
        
        if not df_patients.empty:
            col1, col2, col3 = st.columns(3)
            with col1:
                search = st.text_input("Search by Name/ID")
            with col2:
                gender_filter = st.multiselect("Gender", df_patients['gender'].unique())
            with col3:
                diabetes_filter = st.multiselect("Diabetes Type", df_patients['diabetes_type'].unique())
            
            filtered_df = df_patients.copy()
            if search:
                filtered_df = filtered_df[
                    filtered_df['name'].str.contains(search, case=False) |
                    filtered_df['patient_id'].str.contains(search, case=False)
                ]
            if gender_filter:
                filtered_df = filtered_df[filtered_df['gender'].isin(gender_filter)]
            if diabetes_filter:
                filtered_df = filtered_df[filtered_df['diabetes_type'].isin(diabetes_filter)]
            
            st.dataframe(
                filtered_df[['patient_id', 'name', 'age', 'gender', 'diabetes_type', 'phone', 'created_at']],
                use_container_width=True,
                hide_index=True
            )
            
            csv = filtered_df.to_csv(index=False)
            st.download_button("Download List", csv, "patients.csv", "text/csv")
        else:
            st.info("No patients registered")
    
    with tab2:
        st.subheader("Search Patient")
        patient_id = st.text_input("Patient ID")
        
        if st.button("Search"):
            if patient_id:
                patient = get_patient_info(patient_id, current_user)
                if patient:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"""
                        **ID:** {patient['patient_id']}  
                        **Name:** {patient['name']}  
                        **Age:** {patient['age']}  
                        **Gender:** {patient['gender']}  
                        **Blood Group:** {patient['blood_group']}  
                        **Diabetes Type:** {patient.get('diabetes_type', 'N/A')}
                        """)
                    with col2:
                        st.markdown(f"""
                        **Phone:** {patient['phone']}  
                        **Email:** {patient['email']}  
                        **Height:** {patient.get('height_cm', 'N/A')} cm  
                        **Weight:** {patient.get('weight_kg', 'N/A')} kg  
                        **BMI:** {patient.get('bmi', 'N/A')}
                        """)
                    
                    if patient.get('medical_history'):
                        st.text_area("Medical History", patient['medical_history'], disabled=True)
                else:
                    st.warning("Patient not found!")
    
    with tab3:
        st.subheader("Patient Analysis")
        patient_id = st.text_input("Patient ID for Analysis", key="analysis_id")
        
        if patient_id:
            patient = get_patient_info(patient_id)
            if patient:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Name", patient['name'])
                with col2:
                    st.metric("Age", patient['age'])
                with col3:
                    st.metric("Diabetes Type", patient.get('diabetes_type', 'N/A'))
                with col4:
                    st.metric("BMI", f"{patient.get('bmi', 0):.1f}" if patient.get('bmi') else "N/A")
                
                st.markdown("---")
                
                readings = get_patient_readings(patient_id, current_user)
                
                if readings:
                    df_readings = pd.DataFrame(readings)
                    
                    latest = readings[0]
                    st.subheader("Latest Reading")
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Glucose", f"{latest['glucose_value']} {latest['unit']}")
                    with col2:
                        st.metric("Type", latest['reading_type'])
                    with col3:
                        st.metric("Meal Context", latest.get('meal_context', 'N/A'))
                    with col4:
                        st.metric("Activity", latest.get('activity_level', 'N/A'))
                    
                    status, emoji, message, color = get_health_status(latest['glucose_value'], latest['reading_type'])
                    st.markdown(f"### {emoji} Status: <span style='color:{color}'>{status}</span>", unsafe_allow_html=True)
                    
                    st.markdown("---")
                    st.subheader("Glucose Trend")
                    
                    df_readings['glucose_numeric'] = pd.to_numeric(df_readings['glucose_value'], errors='coerce')
                    # Robust timestamp parsing: support mixed formats and naive datetimes
                    df_readings['timestamp'] = pd.to_datetime(
                        df_readings['timestamp'],
                        format='mixed',
                        errors='coerce',
                        utc=True
                    )
                    # Convert to Asia/Kolkata timezone for display
                    df_readings['timestamp'] = df_readings['timestamp'].dt.tz_convert('Asia/Kolkata')
                    
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=df_readings['timestamp'],
                        y=df_readings['glucose_numeric'],
                        mode='lines+markers',
                        name='Glucose Level',
                        line=dict(color='#667eea', width=3),
                        marker=dict(size=10)
                    ))
                    
                    fig.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Low")
                    fig.add_hline(y=180, line_dash="dash", line_color="red", annotation_text="High")
                    
                    fig.update_layout(
                        title="Glucose Levels Over Time",
                        xaxis_title="Date",
                        yaxis_title=f"Glucose ({df_readings['unit'].iloc[0]})",
                        height=400
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                    
                    st.subheader("Statistics")
                    col1, col2, col3, col4, col5 = st.columns(5)
                    with col1:
                        st.metric("Average", f"{df_readings['glucose_numeric'].mean():.1f}")
                    with col2:
                        st.metric("Min", f"{df_readings['glucose_numeric'].min():.1f}")
                    with col3:
                        st.metric("Max", f"{df_readings['glucose_numeric'].max():.1f}")
                    with col4:
                        st.metric("Std Dev", f"{df_readings['glucose_numeric'].std():.1f}")
                    with col5:
                        st.metric("Total", len(readings))
                else:
                    st.info("No readings available")

def analytics_page():
    st.title("Analytics & Insights")
    
    # Get current user info
    current_user = {
        'username': st.session_state.get('username'),
        'role': st.session_state.get('user_role')
    }
    
    # Show info banner for patients and nurses
    if current_user.get('role') == 'patient':
        st.info("📊 Viewing your personal analytics and reports")
    elif current_user.get('role') == 'nurse':
        st.info("📊 Viewing analytics for your assigned patients only")
    else:
        st.success(f"📊 Viewing analytics for all patients (Role: {current_user.get('role', 'N/A').title()})")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build role-based filters
    patient_filter = ""
    reading_filter = ""
    params = []
    
    if current_user.get('role') in ['patient', 'nurse']:
        # Patients and nurses see only their own data
        patient_filter = " WHERE p.created_by = ?"
        reading_filter = " WHERE r.uploaded_by = ?"
        params = [current_user['username']]
    
    st.subheader("Overall Statistics")
    col1, col2, col3, col4 = st.columns(4)
    
    # Total patients with role-based filtering
    if current_user.get('role') in ['patient', 'nurse']:
        cursor.execute(f"SELECT COUNT(*) FROM patients p{patient_filter}", params)
    else:
        cursor.execute("SELECT COUNT(*) FROM patients")
    total_patients = cursor.fetchone()[0]
    
    # Total readings with role-based filtering
    if current_user.get('role') in ['patient', 'nurse']:
        cursor.execute(f"SELECT COUNT(*) FROM readings r{reading_filter}", params)
    else:
        cursor.execute("SELECT COUNT(*) FROM readings")
    total_readings = cursor.fetchone()[0]
    
    # Average glucose with role-based filtering
    if current_user.get('role') in ['patient', 'nurse']:
        cursor.execute(f"SELECT AVG(glucose_value) FROM readings r{reading_filter} AND glucose_value IS NOT NULL", params)
    else:
        cursor.execute("SELECT AVG(glucose_value) FROM readings WHERE glucose_value IS NOT NULL")
    avg_glucose = cursor.fetchone()[0] or 0
    
    # Abnormal readings with role-based filtering
    if current_user.get('role') in ['patient', 'nurse']:
        cursor.execute(f"SELECT COUNT(*) FROM readings r{reading_filter} AND (glucose_value < 70 OR glucose_value > 180)", params)
    else:
        cursor.execute("SELECT COUNT(*) FROM readings WHERE glucose_value < 70 OR glucose_value > 180")
    abnormal = cursor.fetchone()[0]
    
    with col1:
        st.metric("Patients", total_patients)
    with col2:
        st.metric("Readings", total_readings)
    with col3:
        st.metric("Avg Glucose", f"{avg_glucose:.1f}")
    with col4:
        st.metric("Abnormal", abnormal)
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Status Distribution")
        
        # Role-based query for status distribution
        if current_user.get('role') in ['patient', 'nurse']:
            df_readings = pd.read_sql_query(
                "SELECT glucose_value, reading_type FROM readings WHERE glucose_value IS NOT NULL AND uploaded_by = ?", 
                conn, params=params)
        else:
            df_readings = pd.read_sql_query(
                "SELECT glucose_value, reading_type FROM readings WHERE glucose_value IS NOT NULL", 
                conn)
        
        if not df_readings.empty:
            df_readings['status'] = df_readings.apply(lambda row: get_health_status(row['glucose_value'], row['reading_type'])[0], axis=1)
            status_counts = df_readings['status'].value_counts()
            
            fig = px.pie(values=status_counts.values, names=status_counts.index, title="Reading Status")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data available")
    
    with col2:
        st.subheader("Readings Timeline")
        
        # Role-based query for timeline
        if current_user.get('role') in ['patient', 'nurse']:
            df_timeline = pd.read_sql_query("""
                SELECT DATE(timestamp) as date, COUNT(*) as count
                FROM readings
                WHERE uploaded_by = ?
                GROUP BY DATE(timestamp)
                ORDER BY date DESC
                LIMIT 30
            """, conn, params=params)
        else:
            df_timeline = pd.read_sql_query("""
                SELECT DATE(timestamp) as date, COUNT(*) as count
                FROM readings
                GROUP BY DATE(timestamp)
                ORDER BY date DESC
                LIMIT 30
            """, conn)
        
        if not df_timeline.empty:
            fig = px.bar(df_timeline, x='date', y='count', title="Daily Readings (Last 30 Days)")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data available")
    
    conn.close()

def appointments_page():
    st.title("Appointments")
    
    # Get current user info
    current_user = {
        'username': st.session_state.get('username'),
        'role': st.session_state.get('user_role')
    }
    
    tab1, tab2 = st.tabs(["All Appointments", "Schedule New"])
    
    with tab1:
        conn = get_db_connection()
        
        # Base query with role-based filtering
        query = """
            SELECT a.*, p.name as patient_name
            FROM appointments a
            JOIN patients p ON a.patient_id = p.patient_id
        """
        
        # Add role-based filtering for non-doctors
        if current_user.get('role') != 'doctor':
            query += " WHERE p.created_by = ?"
            df = pd.read_sql_query(query, conn, params=(current_user['username'],))
        else:
            df = pd.read_sql_query(query, conn)
            
        conn.close()
        
        if not df.empty:
            st.dataframe(df[['patient_id', 'patient_name', 'appointment_date', 'appointment_time', 'reason', 'status']], 
                        use_container_width=True, 
                        hide_index=True)
        else:
            st.info("No appointments")
    
    with tab2:
        with st.form("appointment_form"):
            df_patients = get_all_patients(current_user)
            patient_id = st.selectbox("Patient", df_patients['patient_id'].tolist() if not df_patients.empty else [])
            
            col1, col2 = st.columns(2)
            with col1:
                date = st.date_input("Date", min_value=datetime.now().date())
            with col2:
                time = st.time_input("Time")
            
            reason = st.text_area("Reason")
            notes = st.text_area("Notes")
            
            if st.form_submit_button("Schedule"):
                if patient_id and reason:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO appointments (patient_id, doctor_username, appointment_date, appointment_time, reason, notes)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (patient_id, st.session_state.username, str(date), str(time), reason, notes))
                    conn.commit()
                    conn.close()
                    st.success("Appointment scheduled!")
                    st.balloons()

def alerts_page():
    st.title("Alerts & Notifications")
    
    # Get current user info
    current_user = {
        'username': st.session_state.get('username'),
        'role': st.session_state.get('user_role')
    }
    
    # Show info banner for patients
    if current_user.get('role') == 'patient':
        st.info("🔔 Viewing your personal alerts only")
    else:
        st.success(f"🔔 Viewing alerts for all patients (Role: {current_user.get('role', 'N/A').title()})")
    
    conn = get_db_connection()
    
    tab1, tab2 = st.tabs(["Unread", "All"])
    
    with tab1:
        # Role-based query for unread alerts
        if current_user.get('role') == 'patient':
            df = pd.read_sql_query("""
                SELECT a.*, p.name as patient_name
                FROM alerts a
                JOIN patients p ON a.patient_id = p.patient_id
                WHERE a.is_read = 0 AND p.created_by = ?
                ORDER BY a.created_at DESC
            """, conn, params=(current_user['username'],))
        else:
            df = pd.read_sql_query("""
                SELECT a.*, p.name as patient_name
                FROM alerts a
                JOIN patients p ON a.patient_id = p.patient_id
                WHERE a.is_read = 0
                ORDER BY a.created_at DESC
            """, conn)
        
        if not df.empty:
            for _, alert in df.iterrows():
                severity_icon = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
                
                with st.expander(f"{severity_icon.get(alert['severity'], '⚪')} {alert['alert_type']} - {alert['patient_name']}"):
                    st.write(f"**Message:** {alert['message']}")
                    st.write(f"**Time:** {alert['created_at']}")
                    
                    if st.button("Mark Read", key=f"read_{alert['id']}"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE alerts SET is_read = 1 WHERE id = ?", (alert['id'],))
                        conn.commit()
                        st.rerun()
        else:
            st.success("No unread alerts!")
    
    with tab2:
        # Role-based query for all alerts
        if current_user.get('role') == 'patient':
            df = pd.read_sql_query("""
                SELECT a.*, p.name as patient_name
                FROM alerts a
                JOIN patients p ON a.patient_id = p.patient_id
                WHERE p.created_by = ?
                ORDER BY a.created_at DESC
                LIMIT 50
            """, conn, params=(current_user['username'],))
        else:
            df = pd.read_sql_query("""
                SELECT a.*, p.name as patient_name
                FROM alerts a
                JOIN patients p ON a.patient_id = p.patient_id
                ORDER BY a.created_at DESC
                LIMIT 50
            """, conn)
        
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No alert history found.")
    
    conn.close()

def reports_page():
    st.title("Reports & Export")
    
    # Get current user info
    current_user = {
        'username': st.session_state.get('username'),
        'role': st.session_state.get('user_role')
    }
    
    # Show info banner for patients
    if current_user.get('role') == 'patient':
        st.info("📄 Viewing your personal reports only")
    else:
        st.success(f"📄 Viewing reports for all patients (Role: {current_user.get('role', 'N/A').title()})")
    
    conn = get_db_connection()
    
    st.subheader("Generate Report")
    
    col1, col2 = st.columns(2)
    with col1:
        # Limit report types for patients
        if current_user.get('role') == 'patient':
            report_type = st.selectbox("Report Type", [
                "My Summary",
                "My Glucose Trends",
                "My Alert History"
            ])
        else:
            report_type = st.selectbox("Report Type", [
                "Patient Summary",
                "Glucose Trends",
                "Alert History",
                "Appointment Log",
                "System Activity"
            ])
    with col2:
        date_range = st.selectbox("Date Range", [
            "Last 7 Days",
            "Last 30 Days",
            "Last 3 Months",
            "All Time"
        ])
    
    if st.button("Generate Report"):
        st.info(f"Generating {report_type} for {date_range}...")
        
        if report_type in ["Patient Summary", "My Summary"]:
            # Role-based query
            if current_user.get('role') == 'patient':
                df = pd.read_sql_query("""
                    SELECT p.patient_id, p.name, p.age, p.diabetes_type,
                           COUNT(r.id) as total_readings,
                           AVG(r.glucose_value) as avg_glucose
                    FROM patients p
                    LEFT JOIN readings r ON p.patient_id = r.patient_id
                    WHERE p.created_by = ?
                    GROUP BY p.patient_id
                """, conn, params=(current_user['username'],))
            else:
                df = pd.read_sql_query("""
                    SELECT p.patient_id, p.name, p.age, p.diabetes_type,
                           COUNT(r.id) as total_readings,
                           AVG(r.glucose_value) as avg_glucose
                    FROM patients p
                    LEFT JOIN readings r ON p.patient_id = r.patient_id
                    GROUP BY p.patient_id
                """, conn)
            
            if not df.empty:
                st.dataframe(df, use_container_width=True)
                csv = df.to_csv(index=False)
                st.download_button("Download CSV", csv, "patient_summary.csv", "text/csv")
            else:
                st.warning("No data available")
        
        elif report_type in ["Alert History", "My Alert History"]:
            # Role-based query
            if current_user.get('role') == 'patient':
                df = pd.read_sql_query("""
                    SELECT a.*, p.name as patient_name
                    FROM alerts a
                    JOIN patients p ON a.patient_id = p.patient_id
                    WHERE p.created_by = ?
                    ORDER BY a.created_at DESC
                """, conn, params=(current_user['username'],))
            else:
                df = pd.read_sql_query("""
                    SELECT a.*, p.name as patient_name
                    FROM alerts a
                    JOIN patients p ON a.patient_id = p.patient_id
                    ORDER BY a.created_at DESC
                """, conn)
            
            if not df.empty:
                st.dataframe(df, use_container_width=True)
                csv = df.to_csv(index=False)
                st.download_button("Download CSV", csv, "alert_history.csv", "text/csv")
            else:
                st.warning("No alerts found")
        
        elif report_type in ["Glucose Trends", "My Glucose Trends"]:
            # Role-based query for glucose trends
            if current_user.get('role') == 'patient':
                df = pd.read_sql_query("""
                    SELECT r.date, r.time, r.glucose_value, r.unit, r.reading_type, p.name as patient_name
                    FROM readings r
                    JOIN patients p ON r.patient_id = p.patient_id
                    WHERE r.uploaded_by = ?
                    ORDER BY r.date DESC, r.time DESC
                """, conn, params=(current_user['username'],))
            else:
                df = pd.read_sql_query("""
                    SELECT r.date, r.time, r.glucose_value, r.unit, r.reading_type, p.name as patient_name
                    FROM readings r
                    JOIN patients p ON r.patient_id = p.patient_id
                    ORDER BY r.date DESC, r.time DESC
                """, conn)
            
            if not df.empty:
                st.dataframe(df, use_container_width=True)
                csv = df.to_csv(index=False)
                st.download_button("Download CSV", csv, "glucose_trends.csv", "text/csv")
            else:
                st.warning("No readings found")
    
    conn.close()

def settings_page():
    st.title("Settings")
    
    # Create tabs - System tab only for doctors and admins
    if st.session_state.get('user_role') in ['doctor', 'admin']:
        tab1, tab2, tab3 = st.tabs(["Profile", "Security", "System"])
    else:
        tab1, tab2 = st.tabs(["Profile", "Security"])
    
    with tab1:
        st.subheader("Profile Settings")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT full_name, email, phone, specialization 
            FROM users WHERE username = ?
        """, (st.session_state.username,))
        user_data = cursor.fetchone()
        conn.close()
        
        if user_data:
            full_name = st.text_input("Full Name", value=user_data[0])
            email = st.text_input("Email", value=user_data[1])
            phone = st.text_input("Phone", value=user_data[2] or "")
            specialization = st.text_input("Specialization", value=user_data[3] or "")
            
            if st.button("Update Profile"):
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users 
                    SET full_name = ?, email = ?, phone = ?, specialization = ?
                    WHERE username = ?
                """, (full_name, email, phone, specialization, st.session_state.username))
                conn.commit()
                conn.close()
                st.success("Profile updated successfully!")
    
    with tab2:
        st.subheader("Change Password")
        
        current_password = st.text_input("Current Password", type="password", key="current_pw")
        new_password = st.text_input("New Password", type="password", key="new_pw")
        confirm_password = st.text_input("Confirm New Password", type="password", key="confirm_pw")
        
        if st.button("Change Password"):
            if current_password and new_password and confirm_password:
                if new_password != confirm_password:
                    st.error("New passwords do not match!")
                else:
                    # Verify current password
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    hashed_current = hash_password(current_password)
                    cursor.execute("SELECT username FROM users WHERE username = ? AND password = ?",
                                 (st.session_state.username, hashed_current))
                    if cursor.fetchone():
                        # Update password
                        hashed_new = hash_password(new_password)
                        cursor.execute("UPDATE users SET password = ? WHERE username = ?",
                                     (hashed_new, st.session_state.username))
                        conn.commit()
                        conn.close()
                        st.success("Password changed successfully!")
                        log_activity(st.session_state.username, "PASSWORD_CHANGED", "User changed password")
                    else:
                        conn.close()
                        st.error("Current password is incorrect!")
            else:
                st.warning("Please fill in all fields")
    
    # Only show System tab for doctors and admins
    if st.session_state.get('user_role') in ['doctor', 'admin']:
        with tab3:
            st.subheader("System Settings")
            
            st.info("System version: 2.0.0")
            st.info(f"Database: {DB_PATH}")
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM patients")
            total_patients = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM readings")
            total_readings = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            conn.close()
            
            st.metric("Total Patients", total_patients)
            st.metric("Total Readings", total_readings)
            st.metric("Total Users", total_users)
            
            st.markdown("---")
            st.subheader("🗑️ Inactive Patient Data Management")
            st.info("**Auto-Cleanup Policy**: ONLY PATIENT accounts and their data are automatically deleted after 30 days of inactivity (no login).\n\n⚠️ **Doctor, Nurse, and Admin accounts are NEVER automatically deleted** - they are stored indefinitely regardless of inactivity.")
            st.success("✅ Automatic notifications are sent to patients at: 30, 15, 7, 5, 3, 2, 1, and 0 days before deletion.")
            
            # Show inactive patients approaching deletion
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cutoff_date_25 = (datetime.now() - timedelta(days=25)).isoformat()
            cutoff_date_30 = (datetime.now() - timedelta(days=30)).isoformat()
            
            # Get patients approaching deletion (25-29 days)
            cursor.execute('''
                SELECT username, full_name, email, last_login, created_at 
                FROM users 
                WHERE role = 'patient' 
                AND (last_login IS NULL OR last_login < ?)
                AND created_at < ?
                AND (last_login >= ? OR (last_login IS NULL AND created_at >= ?))
            ''', (cutoff_date_25, cutoff_date_25, cutoff_date_30, cutoff_date_30))
            
            approaching_deletion = cursor.fetchall()
            
            # Get patients ready for deletion (30+ days)
            cursor.execute('''
                SELECT username, full_name, email, last_login, created_at 
                FROM users 
                WHERE role = 'patient' 
                AND (last_login IS NULL OR last_login < ?)
                AND created_at < ?
            ''', (cutoff_date_30, cutoff_date_30))
            
            ready_for_deletion = cursor.fetchall()
            conn.close()
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("⚠️ Approaching Deletion (25-29 days)", len(approaching_deletion))
            with col2:
                st.metric("🚨 Ready for Deletion (30+ days)", len(ready_for_deletion))
            
            if approaching_deletion:
                st.warning("**Patients Approaching Deletion (25-29 days inactive):**")
                for patient in approaching_deletion:
                    username, full_name, email, last_login, created_at = patient
                    ref_date = last_login if last_login else created_at
                    days_inactive = (datetime.now() - datetime.fromisoformat(ref_date)).days
                    st.text(f"• {full_name} ({username}) - {days_inactive} days inactive")
            
            if ready_for_deletion:
                st.error("**Patients Ready for Deletion (30+ days inactive):**")
                for patient in ready_for_deletion:
                    username, full_name, email, last_login, created_at = patient
                    ref_date = last_login if last_login else created_at
                    days_inactive = (datetime.now() - datetime.fromisoformat(ref_date)).days
                    st.text(f"• {full_name} ({username}) - {days_inactive} days inactive")
            
            st.markdown("---")
            
            # Show recent warnings sent
            st.subheader("📧 Recent Deletion Warnings Sent")
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT dw.username, u.full_name, dw.warning_type, dw.days_remaining, dw.warning_sent_at
                FROM deletion_warnings dw
                JOIN users u ON dw.username = u.username
                ORDER BY dw.warning_sent_at DESC
                LIMIT 10
            ''')
            recent_warnings = cursor.fetchall()
            conn.close()
            
            if recent_warnings:
                for warning in recent_warnings:
                    username, full_name, warning_type, days_remaining, sent_at = warning
                    sent_time = datetime.fromisoformat(sent_at).strftime('%Y-%m-%d %H:%M')
                    
                    if warning_type == "CRITICAL":
                        st.error(f"🚨 {full_name} ({username}) - {warning_type} - {days_remaining} days - {sent_time}")
                    elif warning_type == "URGENT":
                        st.warning(f"⚠️ {full_name} ({username}) - {warning_type} - {days_remaining} days - {sent_time}")
                    else:
                        st.info(f"ℹ️ {full_name} ({username}) - {warning_type} - {days_remaining} days - {sent_time}")
            else:
                st.info("No warnings sent yet.")
            
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 Run Manual Cleanup Now", type="primary", use_container_width=True):
                    with st.spinner("Running cleanup..."):
                        deleted_count = cleanup_inactive_patient_data()
                        if deleted_count > 0:
                            st.success(f"✅ Successfully deleted {deleted_count} inactive patient account(s) and their data.")
                            log_activity(st.session_state.username, "MANUAL_CLEANUP", f"Manually triggered cleanup, deleted {deleted_count} accounts")
                            time.sleep(2)
                            st.rerun()
                        else:
                            st.info("No inactive patient accounts found for deletion.")
            
            with col2:
                if st.button("📧 Send Warnings Now", type="secondary", use_container_width=True):
                    with st.spinner("Checking and sending warnings..."):
                        check_and_send_deletion_warnings()
                        st.success("✅ Warning check completed! Notifications sent to patients approaching deletion.")
                        time.sleep(2)
                        st.rerun()
            
            st.markdown("---")
            st.subheader("Activity Logs")
            if st.button("Clear All Activity Logs", type="secondary"):
                if st.checkbox("I understand this will delete ALL activity logs for ALL users"):
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM activity_log")
                    conn.commit()
                    conn.close()
                    log_activity(st.session_state.username, "CLEARED_ALL_LOGS", "All activity logs were cleared")
                    st.success("All activity logs have been cleared!")

# Main execution flow
def main():
    load_css()
    
    # First, check if API key is configured
    if not st.session_state.api_configured:
        # Header block with logo, title and tagline
        logo_path = Path(r"C:\\Users\\tejan\\OneDrive\\Desktop\\OCR\\imge.png")
        if not logo_path.exists():
            fallback = Path("imge.png")
            if fallback.exists():
                logo_path = fallback
        if logo_path.exists():
            st.markdown('<div class="logo-center"><div class="logo-wrap"></div>', unsafe_allow_html=True)
            st.image(str(logo_path), width=120)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.markdown("<div style='height: 8px'></div>", unsafe_allow_html=True)
        
        st.markdown(
            """
            <div class=\"header-section\"> 
                <h1 class=\"main-header\"><span class=\"icon\">🩸</span> Advanced Glucometer Detection System</h1>
                <div class=\"auth-tagline\">Smart Glucose Scanning Made Simple</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        st.markdown("---")
        st.markdown("### 🔑 Configure Google Gemini API")
        st.info("Please enter your Google Gemini API key to use the OCR functionality. You can get your API key from [Google AI Studio](https://makersuite.google.com/app/apikey).")
        
        api_key_input = st.text_input(
            "Google Gemini API Key",
            type="password",
            placeholder="Enter your API key here...",
            help="Your API key will be stored securely in the session and not saved permanently."
        )
        
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("🚀 Configure API", use_container_width=True):
                if api_key_input and len(api_key_input.strip()) > 0:
                    try:
                        # Test the API key by configuring genai
                        genai.configure(api_key=api_key_input.strip())
                        st.session_state.api_key = api_key_input.strip()
                        st.session_state.api_configured = True
                        st.success("✅ API key configured successfully!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Invalid API key or configuration error: {str(e)}")
                else:
                    st.warning("⚠️ Please enter a valid API key")
        
        st.markdown("---")
        st.markdown(
            """
            <div style="text-align: center; color: #666; font-size: 0.9rem; margin-top: 2rem;">
                <p>🔒 Your API key is stored securely in the session and will not be saved to disk.</p>
                <p>Need help? Visit the <a href="https://ai.google.dev/tutorials/setup" target="_blank">Google AI Setup Guide</a></p>
            </div>
            """,
            unsafe_allow_html=True
        )
        return
    
    # API is configured, now check login status
    if not st.session_state.logged_in:
        # Header block with logo, title and tagline
        logo_path = Path(r"C:\\Users\\tejan\\OneDrive\\Desktop\\OCR\\imge.png")
        if not logo_path.exists():
            fallback = Path("imge.png")
            if fallback.exists():
                logo_path = fallback
        if logo_path.exists():
            st.markdown('<div class="logo-center"><div class="logo-wrap"></div>', unsafe_allow_html=True)
            st.image(str(logo_path), width=120)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.markdown("<div style='height: 8px'></div>", unsafe_allow_html=True)
        st.markdown(
            """
            <div class=\"header-section\"> 
                <h1 class=\"main-header\"><span class=\"icon\">🩸</span> Advanced Glucometer Detection System</h1>
                <div class=\"auth-tagline\">Smart Glucose Scanning Made Simple</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        
        tab1, tab2 = st.tabs([" 👤 Login", " 📝 Register"])
        
        with tab1:
            st.subheader("Login to Your Account")
            
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button(" Login", use_container_width=True):
                    if username and password:
                        success, result, message = login_user(username, password)
                        if success:
                            st.session_state.logged_in = True
                            st.session_state.username = username
                            
                            # Extract user details from result
                            if result:
                                st.session_state.user_full_name = result[2]  # full_name
                                st.session_state.user_role = result[1]  # role
                            
                            st.success("Login successful!")
                            st.rerun()
                        else:
                            st.error(message)
                    else:
                        st.warning("Please enter both username and password")
            
        
        with tab2:
            st.markdown(
                """
                <div style="background: linear-gradient(90deg, #E6E6FA 0%, #ffffff 100%); border-radius: 12px; padding: 18px 20px; display: flex; align-items: center; gap: 12px; margin-bottom: 1.25rem;">
                    <div style="width: 36px; height: 36px; display:flex; align-items:center; justify-content:center; border-radius: 8px; background: rgba(102, 126, 234, 0.15); font-size: 20px;">🩺</div>
                    <h2 style="color: #2c3e50; margin: 0; font-weight: 700; font-size: 1.8rem; letter-spacing: 0.3px;">Create New Account</h2>
                </div>
                """,
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            with c1:
                new_username = st.text_input("Username", key="reg_username")
            with c2:
                new_email = st.text_input("Email", key="reg_email")

            c3, c4 = st.columns(2)
            with c3:
                new_full_name = st.text_input("Full Name", key="reg_full_name")
            with c4:
                new_phone = st.text_input("Phone (Optional)", key="reg_phone")

            c5, c6 = st.columns(2)
            with c5:
                new_password = st.text_input("Password", type="password", key="reg_password")
            with c6:
                new_password_confirm = st.text_input("Confirm Password", type="password", key="reg_password_confirm")

            c7, c8 = st.columns(2)
            with c7:
                new_role = st.selectbox("Role", ["doctor", "nurse", "admin", "patient"], key="reg_role", help="Select your role")
            with c8:
                new_specialization = st.text_input("Specialization (Optional)", key="reg_specialization", help="Specialization is optional and applies to medical staff")

            # Registration Progress (main register)
            try:
                required_flags_main = [
                    bool(new_full_name.strip()),
                    validate_email(new_email),
                    bool(new_username.strip()),
                    len(new_password) >= 8,
                    new_password == new_password_confirm,
                ]
                # Phone and role contribute as well
                if new_phone:
                    required_flags_main.append(validate_phone(new_phone))
                required_flags_main.append(new_role in ["doctor", "nurse", "admin", "patient"])
                progress_val_main = sum(required_flags_main)
                total_steps_main = len(required_flags_main)
                progress_ratio_main = progress_val_main / total_steps_main if total_steps_main else 0
                st.progress(progress_ratio_main)
                st.caption(f"Registration progress: {int(progress_ratio_main * 100)}%")
            except Exception:
                pass

            if st.button(" Register", use_container_width=True):
                if new_username and new_email and new_full_name and new_password:
                    if new_password != new_password_confirm:
                        st.error("Passwords do not match!")
                    else:
                        success, message = register_user(
                            new_username, new_password, new_email, 
                            new_full_name, new_role, new_phone, new_specialization
                        )
                        if success:
                            st.success("Registration successful! Please login.")
                        else:
                            st.error(message)
                else:
                    st.warning("Please fill in all required fields")
            
    
    else:
        # User is logged in, show main app
        main_app()

# Run the application
if __name__ == "__main__":
    main()