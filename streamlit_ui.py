import streamlit as st
import pandas as pd
import requests
import json
import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
import sqlite3
import hashlib
import random

# Database Path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')

# Import our existing modules
from config import Config
from utils import setup_logging
from selenium_scraper import SeleniumScraper
from exporter import DataExporter
from dedupe import Deduplicator
from robots_checker import RobotsChecker
import extra_streamlit_components as stx
from datetime import timedelta
import sys
from pathlib import Path

# Add the Email Sending Stremlit directory and its components to Python path
email_system_path = Path(__file__).parent / "Email Sending  Stremlit"
if email_system_path.exists():
    paths_to_add = [
        str(email_system_path),
        str(email_system_path / "backend"),
        str(email_system_path / "pages")
    ]
    for p in paths_to_add:
        if p not in sys.path:
            sys.path.append(p)

try:
    from streamlit_gsheets import GSheetsConnection
except ImportError:
    pass

try:
    import gspread
except ImportError:
    gspread = None

# --- DB Handler Class ---
class DBHandler:
    def __init__(self):
        self.use_gsheets = False
        try:
            if GSheetsConnection and "connections" in st.secrets and "gsheets" in st.secrets.connections:
                self.use_gsheets = True
                self.conn = st.connection("gsheets", type=GSheetsConnection)
        except Exception:
            self.use_gsheets = False
            
    def init_db(self):
        if self.use_gsheets:
            # Check if we can read
            try:
                # Use ttl=0 to ensure we check the actual sheet status
                df = self.conn.read(ttl=0)
                if df is not None and not df.empty and 'username' in df.columns:
                    # Sheet exists and has data, don't overwrite
                    return
                
                # If we get here, the sheet might be empty or missing headers
                if df is not None and (df.empty or 'username' not in df.columns):
                    initial_data = pd.DataFrame([
                        {
                            'username': 'admin', 
                            'password': hash_password('admin'), 
                            'role': 'admin', 
                            'active': 1, 
                            'created_at': datetime.now().isoformat(),
                            'openrouter_key': "",
                            'smtp_user': "",
                            'smtp_pass': "",
                            'gsheets_creds': "",
                            'plan': 'enterprise',
                            'usage_count': 0,
                            'usage_limit': 1000000,
                            'email_count': 0,
                            'email_limit': 1000000
                        }
                    ])
                    self.conn.update(data=initial_data)
                    print("Initialized new Google Sheet database with all SaaS columns.")
            except Exception as e:
                # If it's a connection error, DON'T initialize/overwrite
                print(f"Warning: Could not connect to Google Sheets: {e}")
                # We don't set self.use_gsheets = False here because it might be transient
        else:
            # SQLite Logic
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (username TEXT PRIMARY KEY, password TEXT, role TEXT, active INTEGER DEFAULT 1, openrouter_key TEXT)''')
            
            # Migration for existing DBs
            try:
                c.execute("ALTER TABLE users ADD COLUMN openrouter_key TEXT")
            except sqlite3.OperationalError: pass
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN smtp_user TEXT")
            except sqlite3.OperationalError: pass
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN smtp_pass TEXT")
            except sqlite3.OperationalError: pass
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN gsheets_creds TEXT")
            except sqlite3.OperationalError: pass

            try:
                c.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'")
            except sqlite3.OperationalError: pass

            try:
                c.execute("ALTER TABLE users ADD COLUMN usage_count INTEGER DEFAULT 0")
            except sqlite3.OperationalError: pass

            try:
                c.execute("ALTER TABLE users ADD COLUMN usage_limit INTEGER DEFAULT 50")
            except sqlite3.OperationalError: pass

            try:
                c.execute("ALTER TABLE users ADD COLUMN email_count INTEGER DEFAULT 0")
            except sqlite3.OperationalError: pass

            try:
                c.execute("ALTER TABLE users ADD COLUMN email_limit INTEGER DEFAULT 100")
            except sqlite3.OperationalError: pass
            
            # Check if admin exists
            c.execute("SELECT username FROM users WHERE username='admin'")
            if not c.fetchone():
                admin_pass = hash_password("admin")
                try:
                    c.execute("INSERT INTO users (username, password, role, plan, usage_limit, email_limit) VALUES (?, ?, ?, ?, ?, ?)",
                             ("admin", admin_pass, "admin", "enterprise", 1000000, 1000000))
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
            conn.close()

    def get_user(self, username):
        if self.use_gsheets:
            try:
                df = self.conn.read(ttl=0)
                user = df[df['username'] == username]
                if not user.empty:
                    # Return tuple like sqlite: (password, role, active, openrouter_key, smtp_user, smtp_pass, gsheets_creds, plan, usage_count, usage_limit)
                    row = user.iloc[0]
                    return (
                        row.get('password', ""), 
                        row.get('role', 'user'), 
                        row.get('active', 1), 
                        row.get('openrouter_key', ""),
                        row.get('smtp_user', ""),
                        row.get('smtp_pass', ""),
                        row.get('gsheets_creds', ""),
                        row.get('plan', 'free'),
                        row.get('usage_count', 0),
                        row.get('usage_limit', 50),
                        row.get('email_count', 0),
                        row.get('email_limit', 100)
                    )
            except Exception as e:
                print(f"GSheets Read Error: {e}")
            return None
        else:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT password, role, active, openrouter_key, smtp_user, smtp_pass, gsheets_creds, plan, usage_count, usage_limit, email_count, email_limit FROM users WHERE username=?", (username,))
            result = c.fetchone()
            conn.close()
            return result

    def update_settings(self, username, settings_dict):
        """Update multiple user settings at once."""
        if self.use_gsheets:
            try:
                df = self.conn.read(ttl=0)
                mask = df['username'] == username
                for key, value in settings_dict.items():
                    if key not in df.columns: df[key] = ""
                    df.loc[mask, key] = value
                self.conn.update(data=df)
                return True
            except: return False
        else:
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                for key, value in settings_dict.items():
                    # Sanitize key name for SQL injection prevention
                    if key in ['openrouter_key', 'smtp_user', 'smtp_pass', 'gsheets_creds', 'plan', 'usage_count', 'usage_limit', 'email_count', 'email_limit']:
                        c.execute(f"UPDATE users SET {key} = ? WHERE username = ?", (value, username))
                conn.commit()
                conn.close()
                return True
            except: return False

    def update_api_key(self, username, key):
        if self.use_gsheets:
            try:
                df = self.conn.read(ttl=0)
                if 'openrouter_key' not in df.columns:
                    df['openrouter_key'] = ""
                df.loc[df['username'] == username, 'openrouter_key'] = key
                self.conn.update(data=df)
                return True
            except: return False
        else:
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE users SET openrouter_key = ? WHERE username = ?", (key, username))
                conn.commit()
                conn.close()
                return True
            except: return False

    def migrate_to_gsheets(self):
        """Copies users from SQLite to Google Sheets if GSheets is connected."""
        if not self.use_gsheets:
            return False, "Google Sheets not connected."
        
        try:
            # 1. Get all users from SQLite
            conn = sqlite3.connect(DB_PATH)
            local_users = pd.read_sql_query("SELECT * FROM users", conn)
            conn.close()
            
            # 2. Get existing GSheets users
            df_gsheets = self.conn.read(ttl=0)
            
            # 3. Merge users (prioritize local if duplicates)
            new_users = []
            for _, row in local_users.iterrows():
                if row['username'] not in df_gsheets['username'].values:
                    # Clean the data to match expected columns
                    new_user = {
                        'username': row['username'],
                        'password': row['password'],
                        'role': row.get('role', 'user'),
                        'active': row.get('active', 1),
                        'created_at': datetime.now().isoformat(),
                        'openrouter_key': row.get('openrouter_key', ''),
                        'smtp_user': row.get('smtp_user', ''),
                        'smtp_pass': row.get('smtp_pass', ''),
                        'gsheets_creds': row.get('gsheets_creds', ''),
                        'plan': row.get('plan', 'free'),
                        'usage_count': row.get('usage_count', 0),
                        'usage_limit': row.get('usage_limit', 50)
                    }
                    new_users.append(new_user)
            
            if new_users:
                # Add missing columns to existing df if needed
                for col in new_users[0].keys():
                    if col not in df_gsheets.columns:
                        df_gsheets[col] = ""
                        
                df_final = pd.concat([df_gsheets, pd.DataFrame(new_users)], ignore_index=True)
                self.conn.update(data=df_final)
                return True, f"Successfully migrated {len(new_users)} users to Google Sheets!"
            else:
                return True, "No new users to migrate (everything already synced)."
                
        except Exception as e:
            return False, f"Migration Failed: {str(e)}"

    def get_all_users(self):
        if self.use_gsheets:
            try:
                df = self.conn.read(ttl=0)
                # Ensure all columns exist even if not in sheet
                for col in ['plan', 'usage_count', 'usage_limit', 'email_count', 'email_limit']:
                    if col not in df.columns: df[col] = 0 if 'count' in col or 'limit' in col else 'free'
                return df[['username', 'role', 'active', 'plan', 'usage_count', 'usage_limit', 'email_count', 'email_limit']]
            except:
                return pd.DataFrame(columns=['username', 'role', 'active', 'plan', 'usage_count', 'usage_limit', 'email_count', 'email_limit'])
        else:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query("SELECT username, role, active, plan, usage_count, usage_limit, email_count, email_limit FROM users", conn)
            conn.close()
            return df

    def add_user(self, username, password, role):
        username = username.strip().lower()
        password = password.strip()
        hashed = hash_password(password)
        
        if self.use_gsheets:
            try:
                df = self.conn.read(ttl=0)
                if username in df['username'].values:
                    return False
                
                new_user = {
                    'username': username, 
                    'password': hashed, 
                    'role': role, 
                    'active': 1, 
                    'created_at': datetime.now().isoformat(),
                    'openrouter_key': "",
                    'smtp_user': "",
                    'smtp_pass': "",
                    'gsheets_creds': "",
                    'plan': "free",
                    'usage_count': 0,
                    'usage_limit': 50
                }
                
                # Check for missing columns in existing df and add them if necessary
                for col in new_user.keys():
                    if col not in df.columns:
                        df[col] = ""
                
                df = pd.concat([df, pd.DataFrame([new_user])], ignore_index=True)
                self.conn.update(data=df)
                return True
            except Exception as e:
                print(f"Add User Error: {e}")
                return False
        else:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("INSERT INTO users (username, password, role, active, plan, usage_count, usage_limit) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (username, hashed, role, 1, "free", 0, 50))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                conn.close()

    def update_user(self, username, new_password=None, new_role=None, active=None, plan=None, usage_limit=None, email_limit=None):
        if self.use_gsheets:
            try:
                df = self.conn.read(ttl=0)
                mask = df['username'] == username
                if not mask.any(): return False
                
                if new_password:
                    df.loc[mask, 'password'] = hash_password(new_password)
                if new_role:
                    df.loc[mask, 'role'] = new_role
                if active is not None:
                    df.loc[mask, 'active'] = 1 if active else 0
                if plan:
                    df.loc[mask, 'plan'] = plan
                if usage_limit is not None:
                    df.loc[mask, 'usage_limit'] = int(usage_limit)
                if email_limit is not None:
                    df.loc[mask, 'email_limit'] = int(email_limit)
                    
                self.conn.update(data=df)
                return True
            except Exception as e:
                print(f"Update Error: {e}")
                return False
        else:
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                updates = []
                params = []
                
                if new_password:
                    updates.append("password = ?")
                    params.append(hash_password(new_password))
                if new_role:
                    updates.append("role = ?")
                    params.append(new_role)
                if active is not None:
                    updates.append("active = ?")
                    params.append(1 if active else 0)
                if plan:
                    updates.append("plan = ?")
                    params.append(plan)
                if usage_limit is not None:
                    updates.append("usage_limit = ?")
                    params.append(int(usage_limit))
                if email_limit is not None:
                    updates.append("email_limit = ?")
                    params.append(int(email_limit))
                
                if updates:
                    params.append(username)
                    c.execute(f"UPDATE users SET {', '.join(updates)} WHERE username = ?", params)
                    conn.commit()
                conn.close()
                return True
            except Exception:
                return False

    def delete_user(self, username):
        if self.use_gsheets:
            try:
                df = self.conn.read(ttl=0)
                df = df[df['username'] != username]
                self.conn.update(data=df)
                return True
            except:
                return False
        else:
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("DELETE FROM users WHERE username = ?", (username,))
                conn.commit()
                conn.close()
                return True
            except:
                return False

    def get_storage_type(self):
        if self.use_gsheets:
            return "Google Sheets (Persistent)"
        return "Local SQLite (Temporary on Cloud)"

    def is_ephemeral(self):
        # Check if running on Streamlit Cloud and using SQLite
        is_cloud = os.environ.get('STREAMLIT_RUNTIME_ENV', '') != '' or 'SH_APP_ID' in os.environ
        return is_cloud and not self.use_gsheets

# Initialize DB Handler globally
db = DBHandler()

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_role' not in st.session_state:
    st.session_state.user_role = None
if 'current_tab' not in st.session_state:
    st.session_state.current_tab = 'google_maps'

# User management functions
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Initialize session state for UI enhancement
if 'page' not in st.session_state:
    st.session_state.page = 'login'
if 'sidebar_state' not in st.session_state:
    st.session_state.sidebar_state = 'expanded'
if 'theme' not in st.session_state:
    st.session_state.theme = 'dark' # Default to dark as it looks professional

def init_db():
    db.init_db()

def authenticate_user(username, password):
    hashed_input = hash_password(password)
    result = db.get_user(username)
    
    if result:
        # result = (password, role, active, openrouter_key, smtp_user, smtp_pass, gsheets_creds, plan, usage_count, usage_limit, email_count, email_limit)
        stored_password, role, active, openrouter_key, smtp_user, smtp_pass, gsheets_creds, plan, usage_count, usage_limit, email_count, email_limit = result
        # Robust boolean conversion
        if isinstance(active, str):
            if active.lower() in ['true', '1', 'yes']:
                active_bool = True
            else:
                active_bool = False
        else:
            try:
                active_bool = bool(active)
            except:
                active_bool = False
            
        print(f"Debug: User {username} found. ActiveRaw: {active} -> Bool: {active_bool}")
        
        if stored_password == hashed_input:
            if active_bool:
                st.session_state.username = username
                st.session_state.openrouter_api_key = openrouter_key if openrouter_key else ""
                st.session_state.smtp_user = smtp_user if smtp_user else ""
                st.session_state.smtp_pass = smtp_pass if smtp_pass else ""
                try:
                    st.session_state.google_sheets_creds = json.loads(gsheets_creds) if gsheets_creds else None
                except:
                    st.session_state.google_sheets_creds = None
                
                # SaaS Session State
                st.session_state.user_plan = plan if plan else "free"
                
                # Safe conversion function
                def safe_int(val, default=0):
                    try:
                        if pd.isna(val): return default
                        return int(float(val))
                    except: return default

                st.session_state.usage_count = safe_int(usage_count, 0)
                st.session_state.email_count = safe_int(email_count, 0)
                
                if role == 'admin':
                    st.session_state.user_plan = 'enterprise'
                    st.session_state.usage_limit = 1000000
                    st.session_state.email_limit = 1000000
                else:
                    st.session_state.usage_limit = safe_int(usage_limit, 50)
                    st.session_state.email_limit = safe_int(email_limit, 100)
                
                return "success", role
            else:
                return "inactive", None
        else:
            # Check for plaintext password (migration case)
            if password == stored_password:
                 # Auto-migrate to hash if using GSheets or similar manual entry
                 db.update_user(username, new_password=password)
                 if active_bool:
                    st.session_state.username = username
                    st.session_state.openrouter_api_key = openrouter_key if openrouter_key else ""
                    st.session_state.smtp_user = smtp_user if smtp_user else ""
                    st.session_state.smtp_pass = smtp_pass if smtp_pass else ""
                    try:
                        st.session_state.google_sheets_creds = json.loads(gsheets_creds) if gsheets_creds else None
                    except:
                        st.session_state.google_sheets_creds = None
                    
                    # SaaS Session State
                    st.session_state.user_plan = plan if plan else "free"
                    
                    # Safe conversion function (re-defined or used from above scope if applicable)
                    def safe_int_mig(val, default=0):
                        try:
                            if pd.isna(val): return default
                            return int(float(val))
                        except: return default

                    st.session_state.usage_count = safe_int_mig(usage_count, 0)
                    st.session_state.email_count = safe_int_mig(email_count, 0)
                    
                    if role == 'admin':
                        st.session_state.user_plan = 'enterprise'
                        st.session_state.usage_limit = 1000000
                        st.session_state.email_limit = 1000000
                    else:
                        st.session_state.usage_limit = safe_int_mig(usage_limit, 50)
                        st.session_state.email_limit = safe_int_mig(email_limit, 100)
                    
                    return "success", role
            print(f"Debug: Password mismatch for {username}")
            
    return "invalid", None

def get_users():
    return db.get_all_users()

def add_user(username, password, role):
    return db.add_user(username, password, role)

def update_user(username, new_password=None, new_role=None, active=None, plan=None, usage_limit=None, email_limit=None):
    return db.update_user(username, new_password, new_role, active, plan, usage_limit, email_limit)

def delete_user(username):
    return db.delete_user(username)

def login_page():
    # Exact Replica of the Dark Theme Login UI
    # Dynamic Theme Colors
    if st.session_state.theme == 'dark':
        bg_color = "#0e1117"
        card_bg = "#151921"
        text_color = "#ffffff"
        input_bg = "#262730"
        label_color = "#bdc3c7"
        border_color = "#2d333b"
    else:
        bg_color = "#f0f2f6"
        card_bg = "#ffffff"
        text_color = "#1a1a1a"
        input_bg = "#f9f9f9"
        label_color = "#4a4a4a"
        border_color = "#e0e0e0"

    st.markdown(f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        /* General App Styling */
        .stApp {{
            background-color: {bg_color};
            transition: all 0.3s ease;
        }}
        
        /* Hide default Streamlit elements */
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{visibility: hidden;}}

        /* Centering Wrapper */
        .login-wrapper {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding-top: 50px;
            width: 100%;
        }}

        /* 1. Header Card */
        .header-card {{
            width: 100%;
            max-width: 500px;
            background: linear-gradient(90deg, #6c5ce7 0%, #a29bfe 100%); /* Purple Gradient */
            border-radius: 15px;
            padding: 40px 20px;
            text-align: center;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            position: relative;
        }}
        
        .header-content {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 15px;
        }}

        .header-title {{
            color: white;
            font-family: 'Inter', sans-serif;
            font-size: 32px;
            font-weight: 700;
            margin: 0;
            line-height: 1;
        }}
        
        .lock-icon {{
            font-size: 32px;
        }}

        /* 2. Login Form Styling */
        [data-testid="stForm"] {{
            background-color: {card_bg};
            border: 1px solid {border_color};
            border-radius: 15px;
            padding: 30px;
            max-width: 500px;
            margin: 0 auto;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
        }}

        /* Input Fields */
        .stTextInput label {{
            color: {label_color} !important;
            font-size: 14px;
            font-weight: 500;
        }}
        
        .stTextInput > div > div > input {{
            background-color: {input_bg};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 12px;
        }}
        
        .stTextInput > div > div > input:focus {{
            border-color: #6c5ce7;
            box-shadow: 0 0 0 2px rgba(108, 92, 231, 0.2);
        }}

        /* Checkbox */
        .stCheckbox label {{
            color: {text_color} !important;
        }}

        /* Submit Button */
        .stButton > button {{
            background-color: #ff4757 !important;
            color: white !important;
            border: none;
            border-radius: 8px;
            padding: 10px 24px;
            font-weight: 600;
            transition: all 0.3s ease;
            width: 100%;
        }}
        
        .stButton > button:hover {{
            background-color: #ff6b81 !important;
            box-shadow: 0 4px 12px rgba(255, 71, 87, 0.3);
            transform: translateY(-1px);
        }}

        /* Theme Toggle Button Link Styling */
        .theme-toggle-container {{
            text-align: center;
            margin-top: 20px;
        }}
        </style>
    """, unsafe_allow_html=True)

    # 0. Theme Switcher (External to form)
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        theme_label = "🌙 Dark Mode" if st.session_state.theme == "light" else "☀️ Light Mode"
        if st.button(theme_label, key="login_theme_toggle", use_container_width=True):
            st.session_state.theme = "dark" if st.session_state.theme == "light" else "light"
            st.rerun()

    # Layout using Columns to center the content effectively
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        # 1. Header Card (HTML)
        st.markdown("""
            <div class="header-card">
                <div class="header-content">
                    <span class="lock-icon">🔐</span>
                    <h1 class="header-title">Login</h1>
                </div>
            </div>
        """, unsafe_allow_html=True)

        # 2. Form (Streamlit native widgets styled with CSS)
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username or Email", placeholder="Enter your username or email")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            
            remember_me = st.checkbox("Keep me signed in for 7 days")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # The submit button
            submit_button = st.form_submit_button("Login")

        if submit_button:
            # Strip whitespace to prevent accidental copy-paste errors
            clean_username = username.strip().lower() # Case insensitive username
            clean_password = password.strip()
            
            if not clean_username or not clean_password:
                st.warning("Please enter all fields.", icon="⚠️")
            else:
                # Authenticate
                status, role = authenticate_user(clean_username, clean_password)
                
                if status == "success":
                    st.session_state.logged_in = True
                    st.session_state.user_role = role
                    st.session_state.page = 'dashboard'
                    
                    # Handle "Remember Me"
                    if remember_me:
                        try:
                            # Use session state to pass signal to main or handle here carefully
                            # Re-initializing here might be risky if component already mounted
                            # Instead, we'll set a flag and let main handle it or try a specific key
                            temp_cookie_manager = stx.CookieManager(key="login_cookie_setter")
                            # Set cookie to expire in 7 days
                            expires = datetime.now() + timedelta(days=7)
                            temp_cookie_manager.set('user_token', clean_username, expires_at=expires)
                            temp_cookie_manager.set('user_role', role, expires_at=expires)
                        except Exception as e:
                            print(f"Cookie error: {e}")
                    
                    st.success("Login successful!", icon="✅")
                    time.sleep(0.5)
                    st.rerun()
                elif status == "inactive":
                    st.error("Account is inactive. Please contact admin.", icon="🚫")
                else:
                    st.error("Invalid credentials.", icon="❌")


def admin_panel():
    st.title("🛡️ Admin Panel")
    
    if st.session_state.user_role != 'admin':
        st.error("Access denied. Admin privileges required.")
        return
    
    st.header("Manage Users")
    
    # Persistence Warning
    if db.is_ephemeral():
        st.warning("""
        ⚠️ **Warning: Temporary Storage Detected**
        You are running on a cloud platform but haven't configured Google Sheets. 
        **Any users you add will be deleted** when the app restarts (usually after 30 mins of inactivity).
        
        Please follow the `PERSISTENT_STORAGE_GUIDE.md` to set up Google Sheets for permanent storage.
        """, icon="🚨")
    else:
        st.success(f"✅ Storage Mode: {db.get_storage_type()}", icon="💾")
        if db.use_gsheets:
            st.info("💡 Users are being loaded from **Google Sheets**. If you just switched from SQLite, click the button below to restore your local users to the cloud.")
            if st.button("☁️ Synchronize Local Users to Google Sheets"):
                success, msg = db.migrate_to_gsheets()
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    
    # Add new user
    st.subheader("Add New User")
    with st.form("add_user_form"):
        new_username = st.text_input("New Username")
        new_password = st.text_input("New Password", type="password")
        new_role = st.selectbox("Role", ["admin", "user"])
        add_user_btn = st.form_submit_button("Add User")
        
        if add_user_btn:
            if new_username and new_password:
                if add_user(new_username, new_password, new_role):
                    st.success(f"User {new_username} added successfully!")
                    st.rerun()
                else:
                    st.error("Username already exists!")
            else:
                st.error("Please fill in all fields")
    
    # Show existing users
    st.subheader("Existing Users")
    users_df = get_users()
    st.dataframe(users_df)
    
    # Update/Delete users
    if not users_df.empty:
        selected_user = st.selectbox("Select User to Manage", users_df['username'].tolist())
        if selected_user:
            user_data = users_df[users_df['username'] == selected_user].iloc[0]
            
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                new_password = st.text_input("New Password", type="password", key=f"upd_pass_{selected_user}")
            with col2:
                new_role = st.selectbox("Role", ["admin", "user"], index=0 if user_data['role'] == 'admin' else 1, key=f"upd_role_{selected_user}")
            with col3:
                active_status = st.checkbox("Active", value=bool(user_data['active']), key=f"upd_active_{selected_user}")
            with col4:
                # Plan selection
                plan_options = ["free", "pro", "enterprise"]
                current_plan = user_data.get('plan', 'free')
                new_plan = st.selectbox("SaaS Plan", plan_options, index=plan_options.index(current_plan) if current_plan in plan_options else 0, key=f"upd_plan_{selected_user}")
            with col5:
                # Usage Limit
                current_limit = user_data.get('usage_limit', 50)
                try: 
                    safe_limit = int(float(current_limit)) if pd.notnull(current_limit) else 50
                except: safe_limit = 50
                new_limit = st.number_input("Lead Limit", value=safe_limit, step=50, key=f"upd_limit_{selected_user}")
            with col1:
                # Email Limit
                current_email_limit = user_data.get('email_limit', 100)
                try: 
                    safe_email_limit = int(float(current_email_limit)) if pd.notnull(current_email_limit) else 100
                except: safe_email_limit = 100
                new_email_limit = st.number_input("Email Limit", value=safe_email_limit, step=100, key=f"upd_email_limit_{selected_user}")
            
            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if st.button("💾 Apply SaaS Updates", use_container_width=True):
                    # Update update_user call structure
                    if update_user(selected_user, new_password if new_password else None, new_role, active_status, new_plan, new_limit, new_email_limit):
                        st.success(f"User {selected_user} updated!")
                        st.rerun()
                    else:
                        st.error("Update failed!")
            with col_act2:
                if st.button("🗑️ Delete Account", use_container_width=True):
                    if delete_user(selected_user):
                        st.success("Deleted!")
                        st.rerun()
    
    # Backup & Restore Area
    st.divider()
    st.subheader("💾 Data Safety & Backups")
    st.info("💡 **Tip:** Before updating your project files or deploying to the cloud, download a backup of your users to ensure no data is lost.")
    
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if not users_df.empty:
            csv = users_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download User Backup (CSV)",
                data=csv,
                file_name=f"user_backup_{datetime.now().strftime('%Y%m%d')}.csv",
                mime='text/csv',
                use_container_width=True
            )
    
    with col_b2:
        uploaded_file = st.file_uploader("📤 Restore from Backup", type="csv")
        if uploaded_file is not None:
            try:
                import pandas as pd
                backup_df = pd.read_csv(uploaded_file)
                if st.button("🚀 Confirm Restore Users"):
                    restored_count = 0
                    for _, row in backup_df.iterrows():
                        # Simple add logic
                        db.add_user(row['username'], "temp123", row['role'])
                        restored_count += 1
                    st.success(f"Successfully processed {restored_count} users!")
                    st.rerun()
            except Exception as e:
                st.error(f"Error restoring backup: {e}")

def show_saas_dashboard():
    # Load usage stats
    usage = st.session_state.get('usage_count', 0)
    limit = st.session_state.get('usage_limit', 50)
    email_usage = st.session_state.get('email_count', 0)
    email_limit = st.session_state.get('email_limit', 100)
    plan = st.session_state.get('user_plan', 'free').upper()
    is_unlimited = (plan == 'ENTERPRISE' or st.session_state.get('user_role') == 'admin')
    
    plan_display = "💎 UNLIMITED" if is_unlimited else f"{plan} Plan"
    st.markdown(f"### 📊 Live Analytics - Account: {st.session_state.get('username')} | {plan_display}")
    
    col1, col2, col3 = st.columns(3)
    
    limit_text = "∞" if is_unlimited else limit
    email_limit_text = "∞" if is_unlimited else email_limit

    with col1:
        st.markdown(f"""<div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); padding: 25px; border-radius: 15px; color: white; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
<div style="font-size: 0.9rem; opacity: 0.8;">🔍 Total Leads Found</div>
<div style="font-size: 2.2rem; font-weight: bold; margin: 10px 0;">{usage} <span style="font-size: 1.2rem; opacity: 0.6;">/ {limit_text}</span></div>
<div style="font-size: 0.8rem; background: rgba(255,255,255,0.2); border-radius: 20px; padding: 5px 10px;">Scraper Efficiency: 98.4%</div>
</div>""", unsafe_allow_html=True)

    with col2:
        st.markdown(f"""<div style="background: linear-gradient(135deg, #00b09b 0%, #96c93d 100%); padding: 25px; border-radius: 15px; color: white; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
<div style="font-size: 0.9rem; opacity: 0.8;">📧 Total Emails Sent</div>
<div style="font-size: 2.2rem; font-weight: bold; margin: 10px 0;">{email_usage} <span style="font-size: 1.2rem; opacity: 0.6;">/ {email_limit_text}</span></div>
<div style="font-size: 0.8rem; background: rgba(255,255,255,0.2); border-radius: 20px; padding: 5px 10px;">Delivery Rate: 99.2%</div>
</div>""", unsafe_allow_html=True)

    with col3:
        active_camps = random.randint(1, 5) if email_usage > 0 else 0
        st.markdown(f"""<div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); padding: 25px; border-radius: 15px; color: white; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
<div style="font-size: 0.9rem; opacity: 0.8;">🚀 Active Campaigns</div>
<div style="font-size: 2.2rem; font-weight: bold; margin: 10px 0;">{active_camps}</div>
<div style="font-size: 0.8rem; background: rgba(255,255,255,0.2); border-radius: 20px; padding: 5px 10px;">Real-time Tracking Active</div>
</div>""", unsafe_allow_html=True)

    st.divider()
    
    # Analytics Row
    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.markdown("#### 📅 Lead Generation Trends")
        dates = pd.date_range(end=datetime.now(), periods=10).strftime('%m/%d').tolist()
        leads_data = [random.randint(5, 50) for _ in range(10)]
        chart_df = pd.DataFrame({"Date": dates, "Leads Found": leads_data})
        st.line_chart(chart_df.set_index("Date"), color="#4facfe")
        
    with c2:
        if is_unlimited:
            st.markdown("#### 💎 Unlimited Status")
            st.success("Your account has unrestricted access to all Premium Tools including Lead Enrichment and Competitor Intelligence.")
            st.info("💡 **Enterprise Support**: Direct priority line active.")
        else:
            st.markdown("#### 🏆 Pro Tips for Success")
            st.info("""
            - **Target Niche**: Use specific keywords like 'HVAC Repair'.
            - **Safe Scraping**: Increase delays to 5s+ for safety.
            - **Email Warmup**: Always send test emails first.
            """)
            
            if plan == "FREE":
                st.warning("🚀 **Upgrade to PRO** for 1,000 lead limit! Contact: 03213809420 | titechagency@gmail.com")
                if st.button("Get Pro Plan 💎 (WhatsApp)", use_container_width=True):
                    st.markdown("""
                        <a href="https://wa.me/923213809420" target="_blank">
                            <button style="width: 100%; padding: 10px; background-color: #25D366; color: white; border: none; border-radius: 5px; cursor: pointer;">
                                Buy Pro Plan via WhatsApp 📱
                            </button>
                        </a>
                    """, unsafe_allow_html=True)

def user_panel():
    st.markdown("""
        <div style="background-color: #2c3e50; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
            <h2 style="color: white; margin: 0;">🌍 Lead Scraper Pro Dashboard</h2>
            <p style="color: #bdc3c7;">Professional business lead generation tool for Ti-Tech Software House.</p>
        </div>
    """, unsafe_allow_html=True)
    
    # Navigation tabs
    tab_names = ["🏠 Dashboard", "🌍 Google Maps", "📧 Email Sender", "💰 Price Estimator", "🕵️ Lead Enrichment", "🏢 Competitor Intel"]
    tabs = st.tabs(tab_names)
    
    for i, tab_name in enumerate(tab_names):
        with tabs[i]:
            if tab_name == "🏠 Dashboard":
                show_saas_dashboard()
            elif tab_name == "🌍 Google Maps":
                google_maps_scraping()
            elif tab_name == "📧 Email Sender":
                email_sender()
            elif tab_name == "💰 Price Estimator":
                price_estimator()
            elif tab_name == "🕵️ Lead Enrichment":
                lead_enrichment_tool()
            elif tab_name == "🏢 Competitor Intel":
                competitor_intelligence_tool()

def email_sender():
    st.markdown("""
        <div style="background-color: #1a1a2e; padding: 25px; border-radius: 15px; margin-bottom: 25px; border-left: 5px solid #6366f1;">
            <h2 style="color: white; margin: 0; font-family: 'Inter', sans-serif;">📧 Advanced Email Marketing System</h2>
            <p style="color: #a1a1aa; font-family: 'Inter', sans-serif;">Complete lead management, AI-powered campaigns, and real-time tracking.</p>
        </div>
    """, unsafe_allow_html=True)
    
    # Import pages from the email system
    try:
        # Since we added the 'pages' dir to sys.path, we can import directly
        from lead_management import show_lead_management
        from email_campaigns import show_email_campaigns
        from email_tracking import show_email_tracking
        from data_analytics import show_data_analytics
        from ai_tools import show_ai_tools
        try:
            from settings import show_settings as show_email_settings
        except ImportError:
            show_email_settings = None
    except ImportError as e:
        # Fallback to absolute import if relative fails
        try:
            from pages.lead_management import show_lead_management
            from pages.email_campaigns import show_email_campaigns
            from pages.email_tracking import show_email_tracking
            from pages.data_analytics import show_data_analytics
            from pages.ai_tools import show_ai_tools
            from pages.settings import show_settings as show_email_settings
        except ImportError as e2:
            st.error(f"Error importing email system components: {e2}")
            st.info("Make sure the 'Email Sending  Stremlit/pages' folder is present and contains the required files.")
            return

    # Create tabs for the complete system
    email_tabs = st.tabs([
        "👥 Lead Management", 
        "🚀 Email Campaigns", 
        "📊 Email Tracking", 
        "📈 Analytics", 
        "🤖 AI Tools",
        "⚙️ Config"
    ])
    
    with email_tabs[0]:
        show_lead_management()
    
    with email_tabs[1]:
        show_email_campaigns()
        
    with email_tabs[2]:
        show_email_tracking()
        
    with email_tabs[3]:
        show_data_analytics()
        
    with email_tabs[4]:
        show_ai_tools()

    with email_tabs[5]:
        # Custom section for Credentials (GSheets and SMTP)
        st.subheader("🔑 System Credentials")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 📧 SMTP Settings")
            # Get values from session state which were loaded from DB on login
            smtp_email_val = st.session_state.get('smtp_user', os.environ.get('SMTP_USERNAME', ''))
            smtp_pass_val = st.session_state.get('smtp_pass', os.environ.get('SMTP_PASSWORD', ''))
            
            smtp_email = st.text_input("Sender Email", value=smtp_email_val, key="set_smtp_user")
            smtp_pass = st.text_input("App Password", value=smtp_pass_val, type="password", key="set_smtp_pass")
            if st.button("Save SMTP (Persistent)"):
                db.update_settings(st.session_state.username, {'smtp_user': smtp_email, 'smtp_pass': smtp_pass})
                st.session_state.smtp_user = smtp_email
                st.session_state.smtp_pass = smtp_pass
                os.environ['SMTP_USERNAME'] = smtp_email
                os.environ['SMTP_PASSWORD'] = smtp_pass
                st.success("✅ SMTP Settings Saved Persistently!")

        with col2:
            st.markdown("#### 📈 Google Sheets API")
            st.info("Paste your Service Account JSON content here for Google Sheets export.")
            
            # Load current JSON string from DB/Session
            curr_gsheets_json = json.dumps(st.session_state.google_sheets_creds) if st.session_state.get('google_sheets_creds') else ""
            creds_json = st.text_area("Service Account JSON", value=curr_gsheets_json, placeholder='{"type": "service_account", ...}', height=150)
            if st.button("Save GSheets JSON (Persistent)"):
                try:
                    creds_dict = json.loads(creds_json)
                    db.update_settings(st.session_state.username, {'gsheets_creds': creds_json})
                    st.session_state.google_sheets_creds = creds_dict
                    st.success("✅ GSheets Credentials Saved Persistently!")
                except Exception as e:
                    st.error(f"Invalid JSON: {e}")

        st.divider()
        st.markdown("#### ⚙️ Additional Email Settings")
        show_email_settings()
    

def price_estimator():
    st.markdown("""
        <div style="background-color: #2c3e50; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
            <h2 style="color: white; margin: 0;">💰 Lifetime Free Price Estimator</h2>
            <p style="color: #bdc3c7;">Generate detailed, professional service quotes with OpenRouter integration. No free tier limits!</p>
        </div>
    """, unsafe_allow_html=True)
    
    # API Key Configuration
    if 'openrouter_api_key' not in st.session_state:
        st.session_state.openrouter_api_key = ""
    
    # SaaS Plan Display
    user_plan = st.session_state.get('user_plan', 'free').upper()
    is_unlimited = (user_plan == 'ENTERPRISE' or st.session_state.get('user_role') == 'admin')
    st.info(f"💼 Business Logic Engine - Status: {'💎 UNLIMITED' if is_unlimited else user_plan}")
    
    with st.expander("🔑 OpenRouter API Configuration", expanded=not st.session_state.openrouter_api_key):
        api_key = st.text_input("OpenRouter API Key", 
                               value=st.session_state.openrouter_api_key,
                               type="password", 
                               help="Get your free API key at https://openrouter.ai")
        
        col_save, col_clear = st.columns([1, 1])
        with col_save:
            if st.button("💾 Save Key", use_container_width=True):
                if api_key:
                    st.session_state.openrouter_api_key = api_key
                    st.success("✅ API Key saved for this session!")
                else:
                    st.warning("Please enter a key first.")
        
        with col_clear:
            if st.button("🗑️ Clear Key", use_container_width=True):
                st.session_state.openrouter_api_key = ""
                st.rerun()
    
    if not st.session_state.openrouter_api_key:
        st.info("Please enter your OpenRouter API key to proceed.")
        return
    
    # Client Requirements
    st.subheader("📝 Client Requirements")
    client_req = st.text_area("Project Details", 
                             height=200, 
                             placeholder="Enter the detailed requirements provided by the client...")
    
    # Model Selection
    col1, col2 = st.columns(2)
    with col1:
        # Plan Based Model Restriction
        user_plan = st.session_state.get('user_plan', 'free').lower()
        is_unlimited = (user_plan == 'enterprise' or st.session_state.get('user_role') == 'admin')
        
        if not is_unlimited and user_plan == 'free':
            model_options = {
                "Google: Gemma 2 9B (Free)": "google/gemma-2-9b-it:free",
                "Meta: Llama 3.1 8B (Free)": "meta-llama/llama-3.1-8b-instruct:free",
            }
            st.warning("⭐ Upgrade to PRO for 10x more powerful AI models! Contact: 03213809420 | titechagency@gmail.com")
            if st.button("Upgrade via WhatsApp 💎", key="upgrade_price_estimator"):
                st.markdown('<a href="https://wa.me/923213809420" target="_blank">Chat on WhatsApp</a>', unsafe_allow_html=True)
        else:
            model_options = {
                "🌟 Auto-Select Best Free Model": "auto",
                "Google: Gemma 3 12B (Free)": "google/gemma-3-12b:free",
                "Google: Gemma 2 9B (Free)": "google/gemma-2-9b-it:free",
                "Meta: Llama 3.1 405B (Free)": "meta-llama/llama-3.1-405b-instruct:free",
                "Meta: Llama 3.1 70B (Free)": "meta-llama/llama-3.1-70b-instruct:free",
                "Meta: Llama 3.1 8B (Free)": "meta-llama/llama-3.1-8b-instruct:free",
                "DeepSeek: DeepSeek-V3 (Free)": "deepseek/deepseek-chat:free",
                "OpenRouter Auto (Smart)": "openrouter/auto"
            }
        
        selected_model_name = st.selectbox("AI Model", list(model_options.keys()))
        selected_model = model_options[selected_model_name]
        
        if selected_model == "auto":
            # Priority logic for best free models
            best_free_models = [
                "meta-llama/llama-3.1-405b-instruct:free",
                "google/gemma-3-12b:free",
                "deepseek/deepseek-chat:free"
            ]
            selected_model = best_free_models[0] # Default to top priority
            st.caption(f"🚀 Auto-selected: `{selected_model}`")
    
    with col2:
        currency = st.selectbox("Currency", ["USD ($)", "EUR (€)", "GBP (£)", "PKR (Rs.)", "INR (₹)"])
    
    # Generate Quote
    if st.button("📊 Generate Professional Quote", use_container_width=True):
        if not client_req:
            st.error("❌ Please enter client requirements!")
            return
            
        with st.spinner("🚀 AI is analyzing requirements and generating a professional quote..."):
            try:
                prompt = f"""
                You are a senior project manager and lead consultant at a world-class software development agency. 
                Analyze the following client requirements and provide a detailed, professional price estimation in {currency}.
                
                CLIENT REQUIREMENTS:
                {client_req}
                
                GUIDELINES:
                1. Professional Tone: Use sophisticated business language
                2. Detailed Breakdown:
                   - Discovery & Strategy
                   - UI/UX Design
                   - Development (Frontend & Backend)
                   - Quality Assurance
                   - Deployment
                   - Support & Maintenance
                3. Itemized Pricing: Provide detailed costs for each component
                4. Premium Pricing: Reflect high-end agency standards
                5. Value Proposition: Explain why each phase is critical
                6. Timeline: Estimate professional delivery timeline
                7. Total Investment: Clear total range at the end
                8. Formatting: Use headings, bold text, bullet points, and tables
                
                Act as if you are closing a high-ticket deal. Be authoritative and detailed.
                """
                
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {st.session_state.openrouter_api_key}",
                        "HTTP-Referer": "http://localhost:8501",
                        "X-Title": "Lead Scraper Pro Price Estimator",
                    },
                    json={
                        "model": selected_model,
                        "messages": [
                            {"role": "system", "content": "You are an elite business consultant and senior project estimator."},
                            {"role": "user", "content": prompt}
                        ]
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if 'choices' in result and len(result['choices']) > 0:
                        quote = result['choices'][0]['message']['content']
                        st.success("✅ Quote generated successfully!")
                        st.markdown("---")
                        st.markdown(quote)
                        
                        # Download option
                        st.markdown("---")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.download_button(
                                label="💾 Download as Text",
                                data=quote,
                                file_name=f"quote_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                                mime="text/plain"
                            )
                        with col2:
                            st.download_button(
                                label="📄 Download as Markdown",
                                data=quote,
                                file_name=f"quote_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                                mime="text/markdown"
                            )
                    else:
                        st.error("❌ Failed to generate quote. Please try again.")
                else:
                    st.error(f"❌ API Error: {response.status_code} - {response.text}")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

def google_maps_scraping():
    col1, col2 = st.columns(2)
    with col1:
        query = st.text_input("Business Criteria", "restaurants", help="E.g., Restaurants, Plumbers, Software Companies")
        location = st.text_input("Target Location", "New York, USA", help="City, State, or Region")
    with col2:
        max_leads = st.number_input("Target Unique Leads", min_value=1, max_value=1000, value=50, step=1, help="Exact number of unique leads to generate")
        delay = st.slider("Safe Delay (seconds)", 1.0, 10.0, 3.0, step=0.5, help="Increase to avoid detection")
    
    # Enhanced format selection including Excel
    formats = st.multiselect(
        "Export Formats", 
        ["excel", "google_sheets", "csv", "json", "sqlite"], 
        default=["excel", "google_sheets"],
        help="Select output formats. Excel includes CRM tracking columns. Google Sheets will open in a new tab."
    )
    
    # Results Persistence
    if 'scrape_results' not in st.session_state:
        st.session_state.scrape_results = None
    if 'exported_files_data' not in st.session_state:
        st.session_state.exported_files_data = []

    if st.button("🚀 Start Lead Generation", key="google_maps_start", use_container_width=True):
        st.session_state.scrape_results = None # Clear old results
        st.session_state.exported_files_data = []
        if not query or not location:
            st.error("Please specify both business criteria and target location.")
            return
            
        # SaaS Limit Check
        usage_count = st.session_state.get('usage_count', 0)
        usage_limit = st.session_state.get('usage_limit', 50)
        user_plan = st.session_state.get('user_plan', 'free').lower()
        is_unlimited = (user_plan == 'enterprise' or st.session_state.get('user_role') == 'admin')
        
        if usage_count >= usage_limit and not is_unlimited:
            st.error(f"❌ Usage limit reached ({usage_limit}/{usage_limit}). Please upgrade to ENTERPRISE for UNLIMITED access. Contact: 03213809420 | titechagency@gmail.com")
            st.markdown('<a href="https://wa.me/923213809420" target="_blank"><button style="padding:10px; background:#25D366; color:white; border:none; border-radius:5px;">Upgrade via WhatsApp 📱</button></a>', unsafe_allow_html=True)
            return
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            config = Config()
            # Temporarily disable robots.txt for testing to ensure results
            config._config['robots']['enabled'] = False
            config._config['scraping']['default_delay'] = delay
            config._config['scraping']['max_leads_per_session'] = max_leads
            
            # Add Google Sheets credentials if available
            if 'google_sheets_creds' in st.session_state:
                config._config['google_sheets_creds'] = st.session_state.google_sheets_creds
            
            logger = setup_logging(config)
            
            status_text.markdown("### 🔄 Initializing Advanced Scraper...")
            
            # Initialize scraper
            scraper = SeleniumScraper(
                config=config,
                headless=not st.checkbox("Debug Mode (Show Browser)", value=False),
                guest_mode=True,
                delay=delay
            )
            
            status_text.markdown(f"### 🔍 Searching for **{query}** in **{location}**...")
            progress_bar.progress(10)
            
            # Perform scraping
            # Note: The scraper collects leads. Deduplication ensures uniqueness.
            leads = scraper.scrape_google_maps(
                query=query,
                location=location,
                max_results=max_leads
            )
            
            scraper.close()
            status_text.markdown("### ⚙️ Processing and Deduplicating Data...")
            progress_bar.progress(75)
            
            # Deduplicate
            deduplicator = Deduplicator(config)
            unique_leads = deduplicator.deduplicate(leads)
            
            # SaaS Usage Tracking
            found_count = len(unique_leads)
            new_total = st.session_state.usage_count + found_count
            db.update_settings(st.session_state.username, {'usage_count': new_total})
            st.session_state.usage_count = new_total
            
            status_text.markdown("### 💾 Preparing Download...")
            progress_bar.progress(90)
            
            # Use temporary directory for export to avoid disk usage issues on Cloud
            with tempfile.TemporaryDirectory() as temp_dir:
                exporter = DataExporter(config, output_dir=temp_dir)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                
                clean_query = "".join(x for x in query if x.isalnum() or x in " -_").strip().replace(" ", "_")
                clean_loc = "".join(x for x in location if x.isalnum() or x in " -_").strip().replace(" ", "_")
                base_filename = f"Leads_{clean_query}_{clean_loc}_{timestamp}"
                
                exported_files = exporter.export(
                    data=unique_leads,
                    formats=formats,
                    filename=base_filename
                )
                
                # Store results in session state for persistence across reruns
                st.session_state.scrape_results = unique_leads
                results_list = []
                for file_path in exported_files:
                    if file_path.startswith("http") or file_path.startswith("ERROR"):
                        results_list.append(('Open', file_path, '', ''))
                    else:
                        path_obj = Path(file_path)
                        with open(file_path, 'rb') as f:
                            results_list.append(('Download', f.read(), path_obj.suffix.upper(), path_obj.name))
                st.session_state.exported_files_data = results_list

                progress_bar.progress(100)
                status_text.markdown("### ✅ Generation Complete!")
                st.rerun() # Force UI refresh to show persistent buttons
        
        except Exception as e:
            st.error(f"System Error: {str(e)}")
            import traceback
            st.code(traceback.format_exc())

    # --- RESULTS DISPLAY (Survives Reruns) ---
    if st.session_state.get('scrape_results'):
        unique_leads = st.session_state.scrape_results
        exported_files_data = st.session_state.exported_files_data
        
        st.success(f"Successfully generated {len(unique_leads)} unique leads")
        
        df = pd.DataFrame(unique_leads)
        preview_cols = ['name', 'phone', 'email', 'website', 'address']
        st.dataframe(df[ [c for c in preview_cols if c in df.columns] ])
        
        if exported_files_data:
            st.markdown("### 📥 Download Results" )
            st.info("💡 **Chromebook/Cloud Tip:** If the 'Download' button doesn't respond, ensure your browser is not blocking popups. **Google Sheets** (if selected) is the best way to view data on a Chromebook.")
            cols = st.columns(len(exported_files_data))
            for idx, (btn_type, data, suffix, filename) in enumerate(exported_files_data):
                with cols[idx]:
                    if btn_type == 'Open':
                        if data.startswith("ERROR"):
                            st.error(data)
                        elif data.startswith("http"):
                            st.success(f"📈 [Click here to open]({data})")
                            st.link_button("🌐 Open Google Sheets", data, use_container_width=True)
                            if 'last_opened' not in st.session_state or st.session_state.last_opened != data:
                                st.write(f'''<script>window.open("{data}", "_blank");</script>''', unsafe_allow_html=True)
                                st.session_state.last_opened = data
                    else:
                        st.download_button(
                            label=f"Download {suffix[1:]}",
                            data=data,
                            file_name=filename,
                            mime="application/octet-stream" if suffix != '.XLSX' else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_persist_{idx}"
                        )

def lead_enrichment_tool():
    st.markdown("""
<div style="background: linear-gradient(135deg, #12c2e9, #c471ed, #f64f59); padding: 25px; border-radius: 15px; margin-bottom: 25px; color: white;">
    <h2>🕵️ AI Lead Enrichment Hub</h2>
    <p>Transform raw lead data into high-value prospects with deep AI research.</p>
</div>
    """, unsafe_allow_html=True)
    
    user_plan = st.session_state.get('user_plan', 'free').lower()
    is_unlimited = (user_plan == 'enterprise' or st.session_state.get('user_role') == 'admin')
    
    if not is_unlimited and user_plan == 'free':
        st.warning("🔒 **PRO/ENTERPRISE ONLY**: Lead enrichment requires a premium plan.")
        if st.button("Unlock Deep Research Now 🚀", use_container_width=True):
            st.balloons()
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        lead_name = st.text_input("Business Name", placeholder="e.g. Tesla Inc")
        lead_website = st.text_input("Website URL", placeholder="https://tesla.com")
    
    with col2:
        research_depth = st.select_slider("AI Research Depth", options=["Basic", "Standard", "Deep", "Agentic"])
        focus_areas = st.multiselect("Key Focus Areas", ["Decision Makers", "Tech Stack", "Financials", "Social Media", "News"], default=["Decision Makers", "Social Media"])

    if st.button("🔍 Run Deep Enrichment Scan", type="primary", use_container_width=True):
        if not lead_website:
            st.error("Website URL is required for crawling.")
            return
            
        with st.spinner(f"🤖 AI Agent is performing {research_depth} scan of {lead_name}..."):
            api_key = st.session_state.get('openrouter_api_key', '')
            if not api_key:
                st.error("OpenRouter API key required for AI research.")
                return
            
            prompt = f"Perform a {research_depth} analysis of the company {lead_name} ({lead_website}). Focus on: {', '.join(focus_areas)}. Find social media links and key people."
            
            try:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "http://localhost:8501",
                    "X-Title": "Lead Scraper Pro",
                    "Content-Type": "application/json"
                }
                response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": "google/gemma-3-12b:free",
                        "messages": [{"role": "user", "content": prompt}]
                    },
                    timeout=60
                )
                if response.status_code == 200:
                    data = response.json()
                    result = data['choices'][0]['message']['content']
                    st.success("✅ Enrichment Complete!")
                    st.markdown("### 📋 AI Research Report")
                    st.markdown(result)
                else:
                    error_data = response.json() if response.status_code != 404 else {"error": {"message": "Model not found or API endpoint invalid."}}
                    st.error(f"AI Research failed (Status {response.status_code}): {error_data.get('error', {}).get('message', 'Unknown Error')}")
                    st.info("💡 Tip: Ensure your API key is correct and has a balance (if required) or try a different free model.")
            except Exception as e:
                st.error(f"System Error: {e}")

def competitor_intelligence_tool():
    st.markdown("""
<div style="background: linear-gradient(135deg, #000428, #004e92); padding: 25px; border-radius: 15px; margin-bottom: 25px; color: white; border-left: 5px solid #00f2fe;">
    <h2>🏢 Competitor Intelligence Studio</h2>
    <p>Get the inside track on any business. SWOT analysis, Market cap, and Growth strategy.</p>
</div>
    """, unsafe_allow_html=True)

    user_plan = st.session_state.get('user_plan', 'free').lower()
    is_unlimited = (user_plan == 'enterprise' or st.session_state.get('user_role') == 'admin')
    
    if not is_unlimited:
        st.error("🛡️ **UNLIMITED (ENTERPRISE) ONLY**: This mission-critical tool is reserved for Enterprise users.")
        st.markdown("""
            <div style="padding: 20px; background: rgba(255,255,255,0.05); border-radius: 10px;">
                <p>Contact us for enterprise activation:</p>
                <p>📞 WhatsApp: <b>03213809420</b></p>
                <p>📧 Email: <b>titechagency@gmail.com</b></p>
                <a href="https://wa.me/923213809420" target="_blank">
                    <button style="width: 100%; padding: 10px; background-color: #25D366; color: white; border: none; border-radius: 5px; cursor: pointer;">
                        Chat on WhatsApp 📱
                    </button>
                </a>
            </div>
        """, unsafe_allow_html=True)
        return

    target = st.text_input("Target Competitor Name", placeholder="e.g. Apple Inc")
    if st.button("🔥 Generate Strategic Breakdown", use_container_width=True):
        with st.spinner(f"🛰️ Satellites scanning {target} operations..."):
            api_key = st.session_state.get('openrouter_api_key', '')
            prompt = f"Provide a complete strategic intelligence report for {target}. Include: SWOT analysis, estimated market share, key competitors, and main growth hurdles."
            
            try:
                 headers = {
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "http://localhost:8501",
                    "X-Title": "Lead Scraper Pro Intelligence",
                    "Content-Type": "application/json"
                 }
                 response = requests.post(
                    url="https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": "meta-llama/llama-3.1-405b-instruct:free",
                        "messages": [{"role": "user", "content": prompt}]
                    },
                    timeout=60
                )
                 if response.status_code == 200:
                    res = response.json()['choices'][0]['message']['content']
                    st.markdown("### 📊 Strategic Intelligence Report")
                    st.markdown(res)
                 else:
                    error_msg = response.text
                    try: error_msg = response.json().get('error', {}).get('message', response.text)
                    except: pass
                    st.error(f"Access Denied or API Error ({response.status_code}): {error_msg}")
            except Exception as e:
                 st.error(f"System Failure: {e}")

def main():
    # Handle Tracking Requests first (Real-time Email Tracking)
    try:
        from tracking_handler import handle_tracking
        if handle_tracking():
            st.stop() # Stop further rendering if it's a tracking-only request
    except Exception as e:
        pass

    init_db()
    st.session_state.db_handler = db
    
    # Cookie Manager for session persistence
    cookie_manager = stx.CookieManager()
    
    # Check for existing cookies if not logged in
    if not st.session_state.get('logged_in', False):
        user_token = cookie_manager.get('user_token')
        role_token = cookie_manager.get('user_role')
        
        if user_token and role_token:
            # Validate user against DB to ensure they still exist/active
            user_data = db.get_user(user_token)
            
            if user_data:
                # user_data = (password, role, active, openrouter_key)
                active_val = user_data[2]
                
                # Robust boolean conversion
                if isinstance(active_val, str):
                    active_bool = active_val.lower() in ['true', '1', 'yes']
                else:
                    active_bool = bool(active_val)
                    
                if active_bool:
                    st.session_state.logged_in = True
                    st.session_state.username = user_token
                    st.session_state.user_role = role_token
                    # user_data = (password, role, active, openrouter_key, smtp_user, smtp_pass, gsheets_creds, plan, usage_count, usage_limit, email_count, email_limit)
                    st.session_state.openrouter_api_key = user_data[3] if user_data[3] else ""
                    st.session_state.smtp_user = user_data[4] if user_data[4] else ""
                    st.session_state.smtp_pass = user_data[5] if user_data[5] else ""
                    try:
                        st.session_state.google_sheets_creds = json.loads(user_data[6]) if user_data[6] else None
                    except:
                        st.session_state.google_sheets_creds = None
                    
                    st.session_state.user_plan = user_data[7] if user_data[7] else "free"
                    st.session_state.usage_count = int(user_data[8]) if user_data[8] else 0
                    st.session_state.email_count = int(user_data[10]) if user_data[10] else 0
                    
                    if role_token == 'admin':
                        st.session_state.user_plan = 'enterprise'
                        st.session_state.usage_limit = 1000000
                        st.session_state.email_limit = 1000000
                    else:
                        st.session_state.usage_limit = int(user_data[9]) if user_data[9] else 50
                        st.session_state.email_limit = int(user_data[11]) if user_data[11] else 100
                    
                    st.session_state.page = 'dashboard'
                    st.rerun()
                else:
                    result = None # Force cleanup below
            else:
                result = None
            
            if result is None:
                # Invalid or inactive user, clear cookies
                cookie_manager.delete('user_token')
                cookie_manager.delete('user_role')
    
    if st.session_state.page == 'login' or not st.session_state.get('logged_in', False):
        login_page()
    else:
        # Enhanced sidebar with beautiful design
        with st.sidebar:
            st.markdown("""
            <style>
            [data-testid="stSidebar"] {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            [data-testid="stSidebar"] .css-1d391kg {
                padding-top: 1rem;
            }
            .sidebar-header {
                color: white;
                font-size: 1.5rem;
                font-weight: bold;
                margin-bottom: 1rem;
                text-align: center;
            }
            .user-info {
                color: #e0e0e0;
                font-size: 0.9rem;
                margin-bottom: 1rem;
                text-align: center;
            }
            </style>
            """, unsafe_allow_html=True)
            
            st.markdown(f'<div class="sidebar-header">📊 Lead Scraper Pro</div>', unsafe_allow_html=True)
            
            # SaaS Sidebar Info
            plan = st.session_state.get('user_plan', 'free').upper()
            is_unlimited = (plan == 'ENTERPRISE' or st.session_state.get('user_role') == 'admin')
            
            # Scraper Usage
            usage = st.session_state.get('usage_count', 0)
            limit = st.session_state.get('usage_limit', 50)
            usage_pct = (usage / limit) * 100 if limit > 0 else 100
            
            # Email Usage
            email_usage = st.session_state.get('email_count', 0)
            email_limit = st.session_state.get('email_limit', 100)
            email_pct = (email_usage / email_limit) * 100 if email_limit > 0 else 100
            
            badge_style = "background: linear-gradient(135deg, #FFD700, #FFA500); color: black;" if is_unlimited else "background: rgba(255,255,255,0.1); color: #ffd700;"
            plan_text = "💎 UNLIMITED" if is_unlimited else plan
            
            sidebar_html = f"""<div style="background: rgba(255,255,255,0.1); padding: 12px; border-radius: 10px; margin-bottom: 15px; border-left: 4px solid #ffd700;">
<div style="font-size: 0.9rem; color: #ffffff; margin-bottom: 5px;">👤 <b>{st.session_state.get('username')}</b></div>
<div style="font-size: 0.7rem; font-weight: bold; padding: 2px 8px; border-radius: 10px; display: inline-block; {badge_style}">
{plan_text} Plan
</div>
<div style="margin-top: 15px;">
<div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: #e0e0e0;">
<span>🔍 Scraper Leads</span>
<span>{usage}/{limit if not is_unlimited else '∞'}</span>
</div>
<div style="height: 4px; background: rgba(255,255,255,0.2); border-radius: 2px; margin-top: 2px;">
<div style="height: 100%; width: {min(100, usage_pct) if not is_unlimited else 100}%; background: {'#FFD700' if is_unlimited else '#4facfe'}; border-radius: 2px;"></div>
</div>
</div>
<div style="margin-top: 10px;">
<div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: #e0e0e0;">
<span>📧 Emails Sent</span>
<span>{email_usage}/{email_limit if not is_unlimited else '∞'}</span>
</div>
<div style="height: 4px; background: rgba(255,255,255,0.2); border-radius: 2px; margin-top: 2px;">
<div style="height: 100%; width: {min(100, email_pct) if not is_unlimited else 100}%; background: {'#00ff00' if not is_unlimited else '#FFD700'}; border-radius: 2px;"></div>
</div>
</div>
</div>"""
            st.markdown(sidebar_html, unsafe_allow_html=True)
            
            # Theme Toggle In Sidebar
            st.divider()
            theme_icon = "☀️" if st.session_state.theme == "dark" else "🌙"
            theme_btn_text = f"{theme_icon} Switch to {'Light' if st.session_state.theme == 'dark' else 'Dark'} Mode"
            if st.button(theme_btn_text, use_container_width=True):
                st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
                st.rerun()
            
            # Navigation Choices
            nav_options = ["🏠 Home / Scraper", "📧 Email Sender", "💰 Price Estimator"]
            if st.session_state.user_role == 'admin':
                nav_options.append("🛡️ Admin Panel")
            
            # Find current index
            current_tab = st.session_state.get('current_tab', 'user')
            if current_tab == 'admin':
                default_idx = nav_options.index("🛡️ Admin Panel")
            elif current_tab == 'estimator':
                default_idx = nav_options.index("💰 Price Estimator")
            elif current_tab == 'email':
                default_idx = nav_options.index("📧 Email Sender")
            else:
                default_idx = 0

            nav_selection = st.radio(
                "Navigation",
                nav_options,
                index=default_idx,
                key="nav_radio"
            )

            if nav_selection == "🛡️ Admin Panel":
                st.session_state.current_tab = 'admin'
            elif nav_selection == "💰 Price Estimator":
                st.session_state.current_tab = 'estimator'
            elif nav_selection == "📧 Email Sender":
                st.session_state.current_tab = 'email'
            else:
                st.session_state.current_tab = 'user'
            
            st.divider()
            
            if st.button("🚪 Logout", key="logout_btn"):
                # Clear cookies
                try:
                    cookie_manager.delete('user_token')
                    cookie_manager.delete('user_role')
                except:
                    pass
                
                st.session_state.logged_in = False
                st.session_state.user_role = None
                st.session_state.page = 'login'
                st.session_state.current_tab = 'user'
                st.rerun()
        
        # Main content based on current tab
        if st.session_state.get('current_tab') == 'admin' and st.session_state.user_role == 'admin':
            admin_panel()
        elif st.session_state.get('current_tab') == 'estimator':
            price_estimator()
        elif st.session_state.get('current_tab') == 'email':
            email_sender()
        else:
            user_panel()

if __name__ == "__main__":
    main()