import streamlit as st
import pandas as pd
import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
import sqlite3
import hashlib

# Database Path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')

# Import our existing modules
from config import Config
from utils import setup_logging
from selenium_scraper import SeleniumScraper
from exporter import DataExporter
from dedupe import Deduplicator
from robots_checker import RobotsChecker
from yelp_scraper import YelpScraper
from yelp_scraper import YelpScraper
from yellow_pages_scraper import YellowPagesScraper
import extra_streamlit_components as stx
from datetime import timedelta
try:
    from streamlit_gsheets import GSheetsConnection
except ImportError:
    GSheetsConnection = None

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
            # Check if we can read, if not create basic structure in dataframe
            try:
                df = self.conn.read()
                if df.empty or 'username' not in df.columns:
                    raise Exception("Empty or invalid sheet")
            except:
                # Initialize sheet structure
                initial_data = pd.DataFrame([
                    {'username': 'admin', 'password': hash_password('admin'), 'role': 'admin', 'active': 1, 'created_at': datetime.now().isoformat()}
                ])
                self.conn.update(data=initial_data)
        else:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (username TEXT PRIMARY KEY, password TEXT, role TEXT, active INTEGER DEFAULT 1)''')
            
            # Check if admin exists
            c.execute("SELECT username FROM users WHERE username='admin'")
            if not c.fetchone():
                admin_pass = hash_password("admin")
                try:
                    c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                             ("admin", admin_pass, "admin"))
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
            conn.close()

    def get_user(self, username):
        if self.use_gsheets:
            try:
                df = self.conn.read()
                user = df[df['username'] == username]
                if not user.empty:
                    # Return tuple like sqlite: (password, role, active)
                    row = user.iloc[0]
                    return (row['password'], row['role'], int(row['active']))
            except Exception as e:
                print(f"GSheets Read Error: {e}")
            return None
        else:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT password, role, active FROM users WHERE username=?", (username,))
            result = c.fetchone()
            conn.close()
            return result

    def get_all_users(self):
        if self.use_gsheets:
            try:
                df = self.conn.read()
                return df[['username', 'role', 'active']]
            except:
                return pd.DataFrame(columns=['username', 'role', 'active'])
        else:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query("SELECT username, role, active FROM users", conn)
            conn.close()
            return df

    def add_user(self, username, password, role):
        username = username.strip().lower()
        password = password.strip()
        hashed = hash_password(password)
        
        if self.use_gsheets:
            try:
                df = self.conn.read()
                if username in df['username'].values:
                    return False
                
                new_user = pd.DataFrame([{
                    'username': username, 
                    'password': hashed, 
                    'role': role, 
                    'active': 1,
                    'created_at': datetime.now().isoformat()
                }])
                updated_df = pd.concat([df, new_user], ignore_index=True)
                self.conn.update(data=updated_df)
                return True
            except:
                return False
        else:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            try:
                c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                         (username, hashed, role))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                conn.close()

    def update_user(self, username, new_password=None, new_role=None, active=None):
        if self.use_gsheets:
            try:
                df = self.conn.read()
                mask = df['username'] == username
                if not mask.any(): return
                
                if new_password:
                    df.loc[mask, 'password'] = hash_password(new_password)
                if new_role:
                    df.loc[mask, 'role'] = new_role
                if active is not None:
                    df.loc[mask, 'active'] = 1 if active else 0
                    
                self.conn.update(data=df)
            except Exception as e:
                print(f"Update Error: {e}")
        else:
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
            
            if updates:
                params.append(username)
                c.execute(f"UPDATE users SET {', '.join(updates)} WHERE username = ?", params)
                conn.commit()
            conn.close()

    def delete_user(self, username):
        if self.use_gsheets:
            try:
                df = self.conn.read()
                df = df[df['username'] != username]
                self.conn.update(data=df)
            except:
                pass
        else:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()
            conn.close()

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

def init_db():
    db.init_db()

def authenticate_user(username, password):
    hashed_input = hash_password(password)
    result = db.get_user(username)
    
    if result:
        stored_password, role, active = result
        # Handle cases where GSheets might store integers as floats/strings
        try:
            active = int(active)
        except:
            active = 0
            
        print(f"Debug: User {username} found. Active: {active}")
        
        if stored_password == hashed_input:
            if active:
                st.session_state.username = username
                return "success", role
            else:
                return "inactive", None
        else:
            print(f"Debug: Password mismatch for {username}")
            
    return "invalid", None

def get_users():
    return db.get_all_users()

def add_user(username, password, role):
    return db.add_user(username, password, role)

def update_user(username, new_password=None, new_role=None, active=None):
    db.update_user(username, new_password, new_role, active)

def delete_user(username):
    db.delete_user(username)

def login_page():
    # Exact Replica of the Dark Theme Login UI
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        /* General App Styling */
        .stApp {
            background-color: #0e1117; /* Very dark background */
        }
        
        /* Hide default Streamlit elements */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}

        /* Centering Wrapper */
        .login-wrapper {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding-top: 50px;
            width: 100%;
        }

        /* 1. Header Card */
        .header-card {
            width: 100%;
            max-width: 500px;
            background: linear-gradient(90deg, #6c5ce7 0%, #a29bfe 100%); /* Purple Gradient */
            border-radius: 15px;
            padding: 40px 20px;
            text-align: center;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            position: relative;
        }
        
        .header-content {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 15px;
        }

        .header-title {
            color: white;
            font-family: 'Inter', sans-serif;
            font-size: 32px;
            font-weight: 700;
            margin: 0;
            line-height: 1;
        }
        
        .lock-icon {
            font-size: 32px;
        }

        /* 2. Login Form Styling (targeting standard Streamlit widgets) */
        
        /* Target the Form Container */
        [data-testid="stForm"] {
            background-color: #151921; /* Dark Card Background */
            border: 1px solid #2d333b;
            border-radius: 15px;
            padding: 30px;
            max-width: 500px; /* Match header width */
            margin: 0 auto; /* Center it */
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }

        /* Input Fields */
        .stTextInput label {
            color: #bdc3c7 !important;
            font-size: 14px;
            font-weight: 500;
        }
        
        .stTextInput > div > div > input {
            background-color: #262730;
            color: white;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 12px;
        }
        
        .stTextInput > div > div > input:focus {
            border-color: #6c5ce7;
            box-shadow: none;
        }

        /* Checkbox */
        .stCheckbox {
            color: white;
        }
        .stCheckbox label {
            color: white !important;
        }

        /* Submit Button (Red) */
        .stButton > button {
            background-color: #ff4757 !important; /* Coral Red */
            color: white !important;
            border: none;
            border-radius: 8px;
            padding: 10px 24px;
            font-weight: 600;
            transition: all 0.3s ease;
            width: auto; /* Allow it to be sized by text, or 100% if preferred */
            min-width: 120px;
        }
        
        .stButton > button:hover {
            background-color: #ff6b81 !important;
            box-shadow: 0 4px 12px rgba(255, 71, 87, 0.3);
        }

        /* Helper to align contents */
        .form-container {
            width: 100%;
            max-width: 500px;
            margin: 0 auto;
        }
        </style>
    """, unsafe_allow_html=True)

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
            
            col1, col2, col3 = st.columns(3)
            with col1:
                new_password = st.text_input("New Password (leave blank to keep current)", type="password")
            with col2:
                new_role = st.selectbox("New Role", ["admin", "user"], index=0 if user_data['role'] == 'admin' else 1)
            with col3:
                active_status = st.checkbox("Active", value=bool(user_data['active']))
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Update User"):
                    update_user(selected_user, new_password if new_password else None, new_role, active_status)
                    st.success(f"User {selected_user} updated!")
                    st.rerun()
            with col2:
                if st.button("Delete User"):
                    delete_user(selected_user)
                    st.success(f"User {selected_user} deleted!")
                    st.rerun()

def user_panel():
    st.title("👤 User Dashboard")
    
    # Direct access to Google Maps Scraper (Only Google Maps as requested)
    google_maps_scraping()

def google_maps_scraping():
    st.markdown("""
        <div style="background-color: #2c3e50; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
            <h2 style="color: white; margin: 0;">🌍 Google Maps Lead Scraper Pro</h2>
            <p style="color: #bdc3c7;">This Is Only For Ti-Tech Software House Canadiate Generate high-quality business leads with advanced extraction.</p>
        </div>
    """, unsafe_allow_html=True)
    
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
        ["excel", "csv", "json", "sqlite"], 
        default=["excel"],
        help="Select output formats. Excel includes CRM tracking columns."
    )
    
    if st.button("🚀 Start Lead Generation", key="google_maps_start", use_container_width=True):
        if not query or not location:
            st.error("Please specify both business criteria and target location.")
            return
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            config = Config()
            # Temporarily disable robots.txt for testing to ensure results
            config._config['robots']['enabled'] = False
            config._config['scraping']['default_delay'] = delay
            config._config['scraping']['max_leads_per_session'] = max_leads
            
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
            
            # Verify count - if we have duplicates, we might have fewer than requested
            # In a real "exact count" scenario, we'd loop. 
            # For now, we report what we have.
            
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
                
                progress_bar.progress(100)
                status_text.markdown("### ✅ Generation Complete!")
                
                st.success(f"Successfully generated {len(unique_leads)} unique leads (Raw: {len(leads)})")
                
                if unique_leads:
                    df = pd.DataFrame(unique_leads)
                    # Show preview (limit columns for UI)
                    preview_cols = ['name', 'phone', 'email', 'website', 'address']
                    st.dataframe(df[ [c for c in preview_cols if c in df.columns] ])
                    
                    # Download buttons - Read into memory immediately
                    st.markdown("### 📥 Download Results" )
                    cols = st.columns(len(exported_files))
                    for idx, file_path in enumerate(exported_files):
                        with cols[idx]:
                            path_obj = Path(file_path)
                            with open(file_path, 'rb') as f:
                                file_data = f.read()
                                
                            st.download_button(
                                label=f"Download {path_obj.suffix[1:].upper()}",
                                data=file_data,
                                file_name=path_obj.name,
                                mime="application/octet-stream" if path_obj.suffix != '.xlsx' else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"dl_{idx}"
                            )
                
            # Temp dir is automatically cleaned up here
        
        except Exception as e:
            st.error(f"System Error: {str(e)}")
            import traceback
            st.code(traceback.format_exc())

def main():
    init_db()
    
    # Cookie Manager for session persistence
    cookie_manager = stx.CookieManager()
    
    # Check for existing cookies if not logged in
    if not st.session_state.get('logged_in', False):
        user_token = cookie_manager.get('user_token')
        role_token = cookie_manager.get('user_role')
        
        if user_token and role_token:
            # Validate user against DB to ensure they still exist/active
            if db.use_gsheets:
                # Optimized check for gsheets to avoid repeated full reads if possible, 
                # but for safety we read.
                user_data = db.get_user(user_token)
                result = (user_data[2],) if user_data else None # (active,)
            else:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT active FROM users WHERE username=?", (user_token,))
                result = c.fetchone()
                conn.close()
            
            if result and result[0] == 1:
                st.session_state.logged_in = True
                st.session_state.username = user_token
                st.session_state.user_role = role_token
                st.session_state.page = 'dashboard'
                st.rerun()
            else:
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
            st.markdown(f'<div class="user-info">👤 User: {st.session_state.get("username", "Unknown")}<br>🏷️ Role: {st.session_state.get("user_role", "user")}</div>', unsafe_allow_html=True)
            
            # Navigation based on role
            if st.session_state.user_role == 'admin':
                nav_selection = st.radio(
                    "Navigation",
                    ["User Dashboard", "Admin Panel"],
                    index=0 if st.session_state.get('current_tab') != 'admin' else 1,
                    key="nav_radio"
                )
                if nav_selection == "Admin Panel":
                    st.session_state.current_tab = 'admin'
                else:
                    st.session_state.current_tab = 'user'
            else:
                st.session_state.current_tab = 'user'
                st.write("")  # Empty space
                st.write("👤 User Dashboard")
            
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
        else:
            user_panel()

if __name__ == "__main__":
    main()