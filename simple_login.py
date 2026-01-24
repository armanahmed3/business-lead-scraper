
import streamlit as st
import time

# Page Configuration
st.set_page_config(
    page_title="Login - Secure Access",
    page_icon="🔒",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Custom CSS for Premium & Simple Look
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Background and Main Container */
    .stApp {
        background-color: #f8f9fa;
        background-image: radial-gradient(#e9ecef 1px, transparent 1px);
        background-size: 20px 20px;
    }

    /* Hide standard Streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Login Card Container */
    .login-container {
        background: white;
        padding: 3rem;
        border-radius: 20px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.08);
        max-width: 400px;
        margin: 0 auto;
        text-align: center;
        border: 1px solid rgba(0,0,0,0.02);
    }

    /* Typography */
    .login-header {
        margin-bottom: 2rem;
    }
    
    .login-header h1 {
        font-size: 2rem;
        font-weight: 700;
        color: #1a1a1a;
        margin-bottom: 0.5rem;
    }
    
    .login-header p {
        color: #666;
        font-size: 0.95rem;
    }

    /* Input Fields Styling */
    .stTextInput > div > div > input {
        border-radius: 10px;
        border: 1px solid #e0e0e0;
        padding: 12px 15px;
        font-size: 1rem;
        transition: all 0.3s ease;
        background-color: #fcfcfc;
    }

    .stTextInput > div > div > input:focus {
        border-color: #2563eb;
        box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.1);
        background-color: white;
    }

    /* Button Styling */
    .stButton > button {
        width: 100%;
        background-color: #2563eb;
        color: white;
        border: none;
        padding: 0.75rem 1.5rem;
        font-size: 1.05rem;
        font-weight: 600;
        border-radius: 10px;
        cursor: pointer;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2);
    }

    .stButton > button:hover {
        background-color: #1d4ed8;
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(37, 99, 235, 0.3);
    }
    
    .stButton > button:active {
        transform: translateY(0);
    }

    /* Alerts */
    .stAlert {
        border-radius: 10px;
        margin-top: 1rem;
    }
    
    /* Footer/Help links */
    .auth-footer {
        margin-top: 2rem;
        font-size: 0.85rem;
        color: #888;
    }
    
    .auth-footer a {
        color: #2563eb;
        text-decoration: none;
        font-weight: 500;
        transition: color 0.2s;
    }
    
    .auth-footer a:hover {
        color: #1e40af;
        text-decoration: underline;
    }

</style>
""", unsafe_allow_html=True)

import sqlite3
import hashlib

# Database Authentication Functions
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    # Check if table exists first to avoid errors if run in empty env
    c.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='users'")
    if c.fetchone()[0] == 0:
        conn.close()
        return False, None
        
    c.execute("SELECT password, role, active FROM users WHERE username=? AND active=1", (username,))
    result = c.fetchone()
    conn.close()
    
    if result:
        stored_password, role, active = result
        if stored_password == hash_password(password):
            return True, role
    return False, None

def login():
    # Session state initialization
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'user_role' not in st.session_state:
        st.session_state.user_role = None

    # If already logged in, show success/dashboard placeholder
    if st.session_state.logged_in:
        st.success(f"Welcome back, {st.session_state.user_role}!")
        if st.button("Log Out"):
            st.session_state.logged_in = False
            st.session_state.user_role = None
            st.rerun()
        return

    # Container for the login form
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        <div class="login-container">
            <div class="login-header">
                <h1>Welcome Back</h1>
                <p>Enter your credentials to access your account</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Form Inputs
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            
            submit = st.form_submit_button("Sign In")
        
        # Form Logic
        if submit:
            if username and password:
                is_valid, role = authenticate_user(username, password)
                if is_valid:
                    st.session_state.logged_in = True
                    st.session_state.user_role = role
                    st.success("Login successful! Redirecting...")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Invalid username or password")
                    # Fallback for demo if DB is empty/missing
                    if username == "admin" and password == "admin":
                        st.info("Demo Note: Database might be empty. Using demo admin/admin for entry.")
                        st.session_state.logged_in = True
                        st.session_state.user_role = "admin"
                        time.sleep(1)
                        st.rerun()
            else:
                st.warning("Please enter both username and password")
        
        st.markdown("""
            <div class="auth-footer" style="text-align: center;">
                <p>Forgot password? <a href="#">Reset it</a></p>
                <p>Don't have an account? <a href="#">Create one</a></p>
            </div>
        """, unsafe_allow_html=True)

if __name__ == "__main__":
    login()
