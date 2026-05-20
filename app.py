import streamlit as st
import os
import sqlite3
import json
import hashlib
import base64
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
import streamlit.components.v1 as components
from openai import OpenAI
try:
    from google.colab import userdata
except ImportError:
    userdata = None

from agents.chat_agent import ChatAgent
from agents.weather_agent import WeatherAgent
from agents.event_agent import EventAgent
from agents.recommendation_agent import RecommendationAgent
from agents.rag_agent import RAGAgent
from agents.image_agent import ImageAgent
from agents.controller_agent import ControllerAgent
from agents.security_agent import SecurityAgent
from agents.search_agent import SearchAgent
from agents.llm_client import LLMClient
from agents.critic_agent import CriticAgent


class DisabledRAGAgent:
    """Fallback RAG agent when document indexing cannot be initialized."""

    def __init__(self, reason: str = ""):
        self.reason = reason or "RAG is temporarily unavailable."

    def query(self, question: str) -> str:
        return (
            "Future-events knowledge base is temporarily unavailable. "
            "Please try again later or use event/weather/recommendation queries."
        )

# ============================================================================
# DATABASE INITIALIZATION FUNCTION
# ============================================================================
def initialize_events_database(db_path):
    """
    Create and populate the events database with sample data.
    This runs automatically on app startup.
    """
    # Remove existing db file if it exists to ensure a clean slate
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Create the events table
    c.execute('''
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            description TEXT,
            time TEXT NOT NULL,
            price REAL DEFAULT 0.0,
            capacity INTEGER DEFAULT 0,
            date TEXT NOT NULL,
            location TEXT,
            indoor BOOLEAN DEFAULT 1
        )
    ''')
    
    # Use app timezone for date-based seed data consistency across environments.
    app_tz = os.environ.get("APP_TIMEZONE", "Asia/Singapore")
    try:
        now = datetime.now(ZoneInfo(app_tz))
    except Exception:
        now = datetime.now()

    # Get today's date and tomorrow for realistic testing
    today = now
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)
    
    today_str = today.strftime('%Y-%m-%d')
    tomorrow_str = tomorrow.strftime('%Y-%m-%d')
    day_after_str = day_after.strftime('%Y-%m-%d')
    
    # Insert sample data with TODAY and TOMORROW dates for testing
    events_data = [
        # TODAY'S EVENTS
        ('Concert in the Park', 'Music', 'Outdoor concert with local bands', '19:00', 0.0, 500, today_str, 'Botanic Gardens', 0),
        ('Art Exhibition', 'Art', 'Indoor display of contemporary art', '10:00', 15.0, 100, today_str, 'National Gallery', 1),
        ('Tech Meetup', 'Networking', 'Discussion on AI and Machine Learning', '18:30', 5.0, 30, today_str, 'StartupX Hub', 1),
        ('Cooking Class', 'Food', 'Learn to cook Italian cuisine', '14:00', 75.0, 10, today_str, 'Culinary Institute', 1),
        ('Outdoor Cinema', 'Movie', 'Classic film screening under the stars', '20:00', 12.0, 200, today_str, 'Marina Bay', 0),
        
        # TOMORROW'S EVENTS
        ('Yoga Session', 'Wellness', 'Morning yoga for all levels', '07:00', 20.0, 25, tomorrow_str, 'East Coast Park', 0),
        ('Stand-up Comedy', 'Entertainment', 'Local comedians perform live', '20:30', 25.0, 70, tomorrow_str, 'Comedy Club', 1),
        ('Historical Tour', 'Culture', 'Walking tour of the city\'s historic sites', '09:00', 30.0, 15, tomorrow_str, 'Chinatown', 0),
        ('Gaming Tournament', 'Gaming', 'Esports competition with prizes', '13:00', 10.0, 50, tomorrow_str, 'Gaming Arena', 1),
        ('Beach Volleyball', 'Sports', 'Friendly beach volleyball tournament', '16:00', 0.0, 40, tomorrow_str, 'Sentosa Beach', 0),
        
        # DAY AFTER TOMORROW
        ('Food Festival', 'Food', 'International food stalls and cooking demos', '11:00', 5.0, 1000, day_after_str, 'Clarke Quay', 0),
        ('Jazz Night', 'Music', 'Live jazz performances', '20:00', 35.0, 120, day_after_str, 'Jazz Bar & Lounge', 1),
        ('Photography Workshop', 'Education', 'Learn landscape photography techniques', '08:00', 80.0, 12, day_after_str, 'Various Locations', 0),
        ('Wine Tasting', 'Food', 'Sample wines from around the world', '19:00', 90.0, 30, day_after_str, 'Wine Gallery', 1),
        
        # STATIC FUTURE DATES (for testing specific date queries)
        ('Summer Music Festival', 'Music', 'Multi-day outdoor music festival', '15:00', 120.0, 5000, '2025-07-15', 'Sentosa', 0),
        ('Tech Conference', 'Networking', 'Annual technology conference', '09:00', 250.0, 500, '2025-07-15', 'Convention Center', 1),
        ('Marathon', 'Sports', 'City-wide marathon event', '06:00', 50.0, 10000, '2025-07-16', 'City Center', 0),
        ('Opera Performance', 'Arts', 'Classic opera at the theater', '19:30', 150.0, 800, '2025-07-16', 'Esplanade', 1),
    ]
    
    c.executemany('''
        INSERT INTO events (name, type, description, time, price, capacity, date, location, indoor) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', events_data)
    
    conn.commit()
    
    # Get count for verification
    c.execute('SELECT COUNT(*) FROM events')
    count = c.fetchone()[0]
    
    conn.close()
    
    return count

# ============================================================================
# INITIALIZE DATABASE ON STARTUP
# ============================================================================
# Ensure data directory exists
base_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(base_dir, "data")
os.makedirs(data_dir, exist_ok=True)

# Define database path
db_path = os.path.join(data_dir, "events.db")

# Asset cache paths
asset_cache_dir = os.path.join(data_dir, "asset_cache")
bg_cache_dir = os.path.join(asset_cache_dir, "backgrounds")
os.makedirs(bg_cache_dir, exist_ok=True)
mascot_cache_dir = os.path.join(asset_cache_dir, "mascot")
os.makedirs(mascot_cache_dir, exist_ok=True)
rag_upload_dir = os.path.join(data_dir, "rag_uploads")
os.makedirs(rag_upload_dir, exist_ok=True)

def _location_cache_key(location: str) -> str:
    return hashlib.md5(location.strip().lower().encode()).hexdigest()[:16]

def _location_cache_path(location: str, ext: str = "jpg") -> str:
    safe_ext = (ext or "jpg").lower().lstrip(".")
    return os.path.join(bg_cache_dir, f"{_location_cache_key(location)}.{safe_ext}")

def _resolve_cached_background_path(location: str):
    cache_key = _location_cache_key(location)
    for ext in ("jpg", "jpeg", "png", "webp"):
        candidate = os.path.join(bg_cache_dir, f"{cache_key}.{ext}")
        if os.path.exists(candidate):
            return candidate
    return None

def _image_to_data_uri(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "jpeg"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"

def _get_cached_background(location: str):
    location = location.strip() or "Singapore"
    cache_path = _resolve_cached_background_path(location)
    if not cache_path:
        cache_path = _location_cache_path(location, "jpg")
        try:
            query = urllib.parse.quote_plus(f"{location} skyline")
            url = f"https://source.unsplash.com/1600x900/?{query}"
            with urllib.request.urlopen(url, timeout=8) as response:
                image_bytes = response.read()
            with open(cache_path, "wb") as f:
                f.write(image_bytes)
        except Exception:
            return None
    try:
        return _image_to_data_uri(cache_path)
    except Exception:
        return None

def _get_saved_mascot_path():
    for ext in ("png", "jpg", "jpeg", "webp"):
        candidate = os.path.join(mascot_cache_dir, f"mascot.{ext}")
        if os.path.exists(candidate):
            return candidate
    return None


# Initialize database if not already done in this session
def _app_today_str() -> str:
    app_tz = os.environ.get("APP_TIMEZONE", "Asia/Singapore")
    try:
        return datetime.now(ZoneInfo(app_tz)).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

if 'db_initialized' not in st.session_state:
    st.session_state.db_initialized = False
if 'db_seed_date' not in st.session_state:
    st.session_state.db_seed_date = ""

# Refresh the seed data when app date rolls over to keep "today/tomorrow" queries accurate.
if (not st.session_state.db_initialized) or (st.session_state.db_seed_date != _app_today_str()):
    try:
        event_count = initialize_events_database(db_path)
        st.session_state.db_initialized = True
        st.session_state.db_event_count = event_count
        st.session_state.db_seed_date = _app_today_str()
    except Exception as e:
        st.error(f"Failed to initialize database: {str(e)}")
        st.session_state.db_initialized = False

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================
st.set_page_config(
    page_title="Multi-Agent AI Assistant",
    page_icon="🤖",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    :root {
        --brand-accent: #1f7a8c;
        --brand-accent-strong: #17606f;
        --landing-glow: rgba(255, 255, 255, 0.6);
        --landing-ink: #13232f;
        --landing-cream: #fff3e6;
        --landing-peach: #ffd6c2;
        --landing-coral: #ff8a7a;
        --landing-mint: #c9f7d6;
    }
    .stChatMessage {
        padding: 1rem;
        border-radius: 0.5rem;
    }
    .user-message {
        background-color: #e3f2fd;
    }
    .assistant-message {
        background-color: #f5f5f5;
    }
    .intent-badge {
        background-color: #e8eaf6;
        color: #3f51b5;
        padding: 0.2rem 0.5rem;
        border-radius: 0.3rem;
        font-size: 0.8rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
        display: inline-block;
    }
    .assistant-text, .assistant-text * {
        font-family: inherit !important;
        font-style: normal !important;
        font-weight: 400 !important;
    }
    .attack-chip {
        display: inline-block;
        background: #ffe8e8;
        color: #8b0000;
        border: 1px solid #f5b5b5;
        padding: 0.2rem 0.45rem;
        border-radius: 0.35rem;
        font-size: 0.78rem;
        font-weight: 600;
        margin: 0.25rem 0 0.5rem 0;
    }
    .attack-panel {
        border-left: 4px solid #c62828;
        background: #fff5f5;
        padding: 0.6rem 0.8rem;
        border-radius: 0.4rem;
        margin: 0.4rem 0 0.6rem 0;
    }
    .attack-banner {
        background: #ffe2e2;
        border: 1px solid #f2a3a3;
        color: #7a0000;
        padding: 0.5rem 0.7rem;
        border-radius: 0.45rem;
        font-weight: 700;
        margin: 0.4rem 0 0.6rem 0;
    }
    .landing-wrap {
        position: relative;
        margin: 0.5rem auto 0 auto;
        padding: 1.5rem 1.8rem 2.2rem 1.8rem;
        max-width: 1080px;
        background: rgba(255, 255, 255, 0.86);
        border-radius: 28px;
        border: 1px solid rgba(255, 255, 255, 0.55);
        box-shadow: 0 18px 60px rgba(21, 25, 36, 0.25);
        backdrop-filter: blur(12px);
        overflow: hidden;
    }
    .landing-backdrop {
        position: absolute;
        inset: 0;
        background-size: cover;
        background-position: center;
        opacity: 0.45;
        filter: saturate(1.1);
        z-index: 0;
    }
    .landing-wrap > *:not(.landing-backdrop) {
        position: relative;
        z-index: 1;
    }
    .landing-hero {
        position: relative;
        display: grid;
        grid-template-columns: minmax(240px, 1fr) minmax(280px, 1.2fr);
        gap: 1.5rem;
        align-items: center;
    }
    .landing-hero.centered {
        grid-template-columns: 1fr;
        justify-items: center;
        text-align: center;
    }
    .landing-title {
        font-family: "Space Grotesk", "Trebuchet MS", sans-serif;
        font-size: clamp(2rem, 3vw, 2.8rem);
        color: var(--landing-ink);
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
    }
    .landing-subtitle {
        font-family: "Space Grotesk", "Trebuchet MS", sans-serif;
        font-size: 1.05rem;
        line-height: 1.6;
        color: #2e4a5a;
        margin-bottom: 1.1rem;
    }
    .landing-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.35rem 0.8rem;
        background: linear-gradient(120deg, var(--landing-mint), var(--landing-cream));
        border-radius: 999px;
        font-weight: 600;
        color: #1b4d3d;
        font-size: 0.85rem;
    }
    .mascot-stage {
        position: relative;
        min-height: 360px;
        width: 100%;
        max-width: 860px;
        margin: 0 auto;
    }
    .mascot-bg {
        position: absolute;
        inset: 0;
        margin: auto;
        width: 360px;
        height: 360px;
        border-radius: 28px;
        background-size: cover;
        background-position: center top;
        box-shadow: 0 18px 40px rgba(21, 30, 44, 0.28);
        z-index: 1;
    }
    .mascot-core {
        position: absolute;
        inset: 0;
        margin: auto;
        width: 260px;
        height: 260px;
        display: flex;
        align-items: center;
        justify-content: center;
        filter: drop-shadow(0 25px 40px rgba(21, 30, 44, 0.28));
        animation: floaty 6s ease-in-out infinite;
    }
    .bubble {
        position: absolute;
        padding: 0.55rem 0.85rem;
        border-radius: 22px;
        background: rgba(255, 255, 255, 0.5);
        color: #243645;
        font-size: 0.88rem;
        font-weight: 600;
        box-shadow:
            inset 0 0 0 1px rgba(255, 255, 255, 0.7),
            inset 0 8px 18px rgba(255, 255, 255, 0.35),
            0 14px 28px rgba(19, 24, 34, 0.16);
        width: max-content;
        max-width: 190px;
        border: 1px solid rgba(255, 255, 255, 0.65);
        z-index: 3;
        line-height: 1.15;
        pointer-events: none;
        backdrop-filter: blur(10px) saturate(1.2);
        overflow: hidden;
    }
    .bubble::after {
        content: "";
        position: absolute;
        inset: -60% -40%;
        background: linear-gradient(120deg, transparent 35%, rgba(255, 255, 255, 0.7) 50%, transparent 65%);
        transform: translateX(-120%);
        animation: bubbleSheen 7s ease-in-out infinite;
        opacity: 0.8;
        pointer-events: none;
    }
    .bubble-1::after { animation-delay: 0s; }
    .bubble-2::after { animation-delay: 1s; }
    .bubble-3::after { animation-delay: 2s; }
    .bubble-4::after { animation-delay: 3s; }
    .bubble-5::after { animation-delay: 4s; }
    .bubble-6::after { animation-delay: 5s; }
    .bubble-title {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
    }
    .bubble span {
        display: block;
        font-weight: 400;
        font-size: 0.76rem;
        opacity: 0.75;
        margin-top: 0.12rem;
    }
    .bubble .icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 22px;
        height: 22px;
        border-radius: 9px;
        background: rgba(31, 122, 140, 0.18);
        font-size: 0.82rem;
    }
    .landing-prompt .stTextInput>div>div>input {
        border-radius: 16px;
        padding: 0.85rem 1.1rem;
        border: 2px solid rgba(31, 122, 140, 0.45);
        background: rgba(255, 255, 255, 0.9);
        font-size: 1rem;
        box-shadow: 0 10px 24px rgba(19, 24, 34, 0.12);
    }
    .bubble-float {
        animation: bubbleFloat 7s ease-in-out infinite;
    }
    .bubble-1 { top: 6%; left: 4%; animation-delay: 0s; }
    .bubble-2 { top: 10%; right: 4%; animation-delay: 0.8s; }
    .bubble-3 { top: 44%; left: 0.5%; animation-delay: 1.6s; }
    .bubble-4 { top: 44%; right: 0.5%; animation-delay: 2.4s; }
    .bubble-5 { bottom: 6%; left: 4%; animation-delay: 3.2s; }
    .bubble-6 { bottom: 6%; right: 4%; animation-delay: 4s; }
    .landing-prompt {
        margin-top: 1.2rem;
        text-align: center;
    }
    .landing-prompt .stTextInput {
        max-width: 560px;
        margin: 0 auto;
    }
    .landing-prompt .stTextInput>div>div>input {
        border-radius: 999px;
        padding: 0.75rem 1.2rem;
        border: 1px solid rgba(24, 38, 52, 0.18);
        background: white;
        font-size: 0.95rem;
    }
    .landing-prompt .stTextInput>div>div>input:focus {
        border-color: var(--brand-accent);
        box-shadow: 0 0 0 2px rgba(31, 122, 140, 0.2);
    }
    .landing-chips {
        margin-top: 0.9rem;
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        justify-content: center;
    }
    .landing-chip {
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.7);
        border: 1px solid rgba(25, 40, 54, 0.15);
        font-size: 0.75rem;
        color: #2b4555;
    }
    @keyframes floaty {
        0% { transform: translateY(0px); }
        50% { transform: translateY(-10px); }
        100% { transform: translateY(0px); }
    }
    @keyframes bubbleFloat {
        0% { transform: translateY(0px); }
        50% { transform: translateY(-8px); }
        100% { transform: translateY(0px); }
    }
    @keyframes bubbleSheen {
        0% { transform: translateX(-120%); }
        55% { transform: translateX(30%); }
        100% { transform: translateX(140%); }
    }
    @media (max-width: 980px) {
        .landing-hero {
            grid-template-columns: 1fr;
        }
        .mascot-stage {
            min-height: 320px;
        }
        .bubble-5, .bubble-6 {
            display: none;
        }
    }
    /* Neutralize red defaults for controls */
    .stRadio [role="radiogroup"] > div div[aria-checked="true"]::before {
        background-color: var(--brand-accent) !important;
        border-color: var(--brand-accent) !important;
    }
    .stSlider [data-baseweb="slider"] [data-testid="stTickBar"] {
        background: var(--brand-accent) !important;
    }
    .stSlider [data-testid="stTickBar"] {
        background: var(--brand-accent) !important;
        height: 4px !important;
    }
    .stSlider [data-testid="stTickBar"]::after {
        content: "";
        position: absolute;
        inset: 0;
        background: transparent !important;
    }
    /* Remove the filled block by clearing slider container backgrounds */
    .stSlider [data-baseweb="slider"] > div {
        background: transparent !important;
        box-shadow: none !important;
    }
    .stSlider [data-baseweb="slider"] .st-dw {
        background: transparent !important;
    }
    .stSlider [data-baseweb="slider"] > div > div,
    .stSlider [data-baseweb="slider"] > div > div > div {
        background: transparent !important;
        box-shadow: none !important;
    }
    .stSlider .st-dw.st-dd.st-df.st-de.st-b4.st-dx.st-dy,
    .stSlider .st-av.st-aw.st-ax.st-ay.st-dz.st-e0.st-b9.st-e1.st-e2 {
        background: transparent !important;
        box-shadow: none !important;
    }
    .stSlider [data-baseweb="slider"] {
        background: transparent !important;
    }
    .stSlider [data-baseweb="slider"] > div::before,
    .stSlider [data-baseweb="slider"] > div::after {
        background: transparent !important;
        box-shadow: none !important;
    }
    .stSlider [data-baseweb="slider"] [data-baseweb="slider-track"] {
        background: var(--brand-accent) !important;
        height: 4px !important;
        box-shadow: none !important;
    }
    .stSlider [data-baseweb="slider"] [data-baseweb="slider-track"] > div,
    .stSlider [data-baseweb="slider"] [data-baseweb="slider-track"] > div > div {
        background: transparent !important;
        box-shadow: none !important;
    }
    .stSlider [data-baseweb="slider"] [data-baseweb="progressbar"],
    .stSlider [data-baseweb="slider"] [role="progressbar"],
    .stSlider [data-baseweb="slider"] [aria-valuenow] {
        background: transparent !important;
        box-shadow: none !important;
    }
    .stSlider [data-baseweb="slider"] div[role="slider"]::before {
        background-color: var(--brand-accent) !important;
    }
    .stSlider [data-baseweb="slider"] div[role="slider"] {
        background-color: var(--brand-accent) !important;
        border-color: var(--brand-accent-strong) !important;
    }
    .stSlider [data-testid="stSliderValue"] {
        color: var(--brand-accent-strong) !important;
    }
    .stButton > button[kind="primary"] {
        background-color: var(--brand-accent) !important;
        border-color: var(--brand-accent-strong) !important;
        color: #ffffff !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: var(--brand-accent-strong) !important;
        border-color: var(--brand-accent-strong) !important;
    }
    /* Compact chat composer polish */
    .st-key-prompt_draft input {
        min-height: 46px !important;
        border-radius: 12px !important;
        border: 1px solid #d7dee7 !important;
        padding-left: 0.9rem !important;
        padding-right: 0.9rem !important;
        box-shadow: none !important;
    }
    .st-key-prompt_draft input:focus {
        border-color: var(--brand-accent) !important;
        box-shadow: 0 0 0 1px var(--brand-accent) !important;
    }
    .st-key-send_prompt_btn button {
        min-height: 46px !important;
        border-radius: 12px !important;
        font-size: 0 !important;
        background-color: var(--brand-accent) !important;
        border: 1px solid var(--brand-accent-strong) !important;
        color: #ffffff !important;
        position: relative !important;
    }
    .st-key-send_prompt_btn button:hover {
        background-color: var(--brand-accent-strong) !important;
        border-color: var(--brand-accent-strong) !important;
    }
    .st-key-send_prompt_btn button::before {
        content: "";
        width: 18px;
        height: 18px;
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        background: currentColor;
        -webkit-mask: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"white\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><line x1=\"22\" y1=\"2\" x2=\"11\" y2=\"13\"/><polygon points=\"22 2 15 22 11 13 2 9 22 2\"/></svg>') no-repeat center / contain;
        mask: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"white\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><line x1=\"22\" y1=\"2\" x2=\"11\" y2=\"13\"/><polygon points=\"22 2 15 22 11 13 2 9 22 2\"/></svg>') no-repeat center / contain;
    }
    .st-key-send_prompt_btn button:disabled {
        opacity: 0.6 !important;
    }
    .stPopover > button {
        min-height: 46px !important;
        border-radius: 12px !important;
        border: 1px solid #d7dee7 !important;
        background: #ffffff !important;
        font-size: 0 !important;
        position: relative !important;
    }
    .stPopover > button:hover {
        border-color: var(--brand-accent) !important;
        color: var(--brand-accent-strong) !important;
    }
    .stPopover > button::before {
        content: "";
        width: 18px;
        height: 18px;
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
        background: var(--brand-accent-strong);
        -webkit-mask: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"black\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z\"/><path d=\"M19 10a7 7 0 0 1-14 0\"/><line x1=\"12\" y1=\"19\" x2=\"12\" y2=\"23\"/><line x1=\"8\" y1=\"23\" x2=\"16\" y2=\"23\"/></svg>') no-repeat center / contain;
        mask: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"black\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z\"/><path d=\"M19 10a7 7 0 0 1-14 0\"/><line x1=\"12\" y1=\"19\" x2=\"12\" y2=\"23\"/><line x1=\"8\" y1=\"23\" x2=\"16\" y2=\"23\"/></svg>') no-repeat center / contain;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'initialized' not in st.session_state:
    st.session_state.initialized = False
    st.session_state.messages = []
    st.session_state.controller = None
    st.session_state.security_events = []
    st.session_state.last_security_verdict = None
    st.session_state.last_airs_request = None
    st.session_state.voice_enabled = False
    st.session_state.voice_rate = 1.0
    st.session_state.voice_pitch = 1.0
    st.session_state.voice_volume = 1.0
    st.session_state.voice_name = "marin"
    st.session_state.last_spoken_hash = None
    st.session_state.voice_greeted = False
    st.session_state.tts_cache = {}
    st.session_state.voice_last_enabled = False
    st.session_state.stt_language = "auto"
    st.session_state.audio_last_transcribed_hash = None
    st.session_state.audio_transcript_draft = ""
    st.session_state.audio_transcript_input = ""
    st.session_state.queued_audio_prompt = ""
    st.session_state.prompt_draft = ""
    st.session_state.prompt_prefill = ""
    st.session_state.queued_prompt = ""
    st.session_state.clear_prompt_draft = False

def _speak_text(text, rate=1.0, pitch=1.0, volume=1.0, voice_name=""):
    if not text:
        return
    payload = json.dumps({
        "text": text,
        "rate": rate,
        "pitch": pitch,
        "volume": volume,
        "voiceName": voice_name
    }).replace("</", "<\\/")
    components.html(
        f"""
        <script>
        (() => {{
            const data = {payload};
            if (!data.text) return;
            if (!window.speechSynthesis) return;
            const speak = () => {{
                const synth = window.speechSynthesis;
                const utter = new SpeechSynthesisUtterance(data.text);
                utter.rate = data.rate;
                utter.pitch = data.pitch;
                utter.volume = data.volume;
                if (data.voiceName) {{
                    const voices = synth.getVoices() || [];
                    const target = String(data.voiceName).trim().toLowerCase();
                    let match = voices.find(v => v.name === data.voiceName);
                    if (!match) {{
                        match = voices.find(v => v.name.toLowerCase() === target);
                    }}
                    if (!match) {{
                        match = voices.find(v => v.name.toLowerCase().includes(target));
                    }}
                    if (match) utter.voice = match;
                }}
                synth.cancel();
                synth.speak(utter);
            }};
            const voices = window.speechSynthesis.getVoices();
            if (voices && voices.length > 0) {{
                speak();
            }} else {{
                window.speechSynthesis.onvoiceschanged = () => speak();
            }}
        }})();
        </script>
        """,
        height=0
    )

def _play_audio_bytes(audio_bytes, mime_type="audio/mpeg"):
    if not audio_bytes:
        return
    b64 = base64.b64encode(audio_bytes).decode("ascii")
    components.html(
        f"""
        <audio autoplay="true" controls="false" class="assistant-audio">
            <source src="data:{mime_type};base64,{b64}">
        </audio>
        """,
        height=0
    )


def _openai_tts(text, model, voice, api_key):
    client = OpenAI(api_key=api_key)
    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        response_format="mp3"
    )
    return response.read()

def _transcribe_audio(audio_bytes, api_key, language_code=None, filename="speech.webm", mime_type="audio/webm"):
    if not audio_bytes:
        return ""
    client = OpenAI(api_key=api_key)
    request_kwargs = {
        "file": (filename, audio_bytes, mime_type),
        "response_format": "text",
    }
    if language_code:
        request_kwargs["language"] = language_code
    # Prefer newer transcription model; fall back for compatibility.
    for model_name in ("gpt-4o-mini-transcribe", "whisper-1"):
        try:
            transcript = client.audio.transcriptions.create(
                model=model_name,
                **request_kwargs,
            )
            return str(transcript).strip()
        except Exception:
            continue
    raise RuntimeError("Audio transcription failed for all supported models.")


def _is_ollama_reachable(base_url: str, timeout_sec: float = 1.5):
    """Fast health check for local/remote Ollama availability."""
    try:
        if not base_url:
            return False
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout_sec)
        return resp.status_code == 200
    except Exception:
        return False

def _get_tts_audio(text, api_key, model="gpt-4o-mini-tts", voice="marin"):
    cache = st.session_state.get("tts_cache", {})
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if text_hash in cache:
        return cache[text_hash]
    audio_bytes = _openai_tts(text, model=model, voice=voice, api_key=api_key)
    cache[text_hash] = audio_bytes
    st.session_state.tts_cache = cache
    return audio_bytes

def _play_voice(text, allow_autoplay=False):
    if not text:
        return
    active_openai_key = os.environ.get("OPENAI_API_KEY") or st.session_state.get("openai_key", "")
    if active_openai_key:
        try:
            audio_bytes = _get_tts_audio(
                text,
                api_key=active_openai_key,
                model="gpt-4o-mini-tts",
                voice=st.session_state.get("voice_name", "marin")
            )
            _play_audio_bytes(audio_bytes, mime_type="audio/mpeg")
            return
        except Exception:
            pass
    _speak_text(
        text,
        rate=st.session_state.get("voice_rate", 1.0),
        pitch=st.session_state.get("voice_pitch", 1.0),
        volume=st.session_state.get("voice_volume", 1.0),
        voice_name="Karen"
    )

def _redact_sensitive_fields(obj):
    """Redact common secret fields before displaying."""
    sensitive_keys = {"api_key", "token", "authorization", "x-pan-token", "secret"}
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            if k.lower() in sensitive_keys:
                redacted[k] = "***REDACTED***"
            else:
                redacted[k] = _redact_sensitive_fields(v)
        return redacted
    if isinstance(obj, list):
        return [_redact_sensitive_fields(v) for v in obj]
    return obj

# Ensure session ID exists for security tracking
if 'user_session_id' not in st.session_state:
    import hashlib
    from datetime import datetime
    session_id = hashlib.md5(f"{datetime.now().isoformat()}".encode()).hexdigest()[:12]
    st.session_state.user_session_id = f"session_{session_id}"
if "landing_location" not in st.session_state:
    st.session_state.landing_location = "Singapore"
if "selected_rag_docs" not in st.session_state:
    st.session_state.selected_rag_docs = []

# Sidebar configuration
stats_placeholder = None
verdict_placeholder = None
payload_placeholder = None
blocked_placeholder = None
with st.sidebar:
    st.title("⚙️ Configuration")
    
    # Show database status
    if st.session_state.get('db_initialized', False):
        st.success(f"✅ Database ready ({st.session_state.get('db_event_count', 0)} events)")
    else:
        st.warning("⚠️ Database initialization pending")
    
    st.divider()

    # Try to load keys from environment variables early for voice audition
    env_openai_key = os.environ.get('OPENAI_API_KEY')
    env_weather_key = os.environ.get('WEATHER_API_KEY')
    env_airs_key = (
        os.environ.get('AIRS_API_KEY')
        or os.environ.get('AIRS_KEY')
        or os.environ.get('AIRSAPI_API_KEY')
    )
    env_serp_key = (
        os.environ.get('SERPAPI_API_KEY')
        or os.environ.get('SERP_API_KEY')
    )
    env_ollama_base_url = os.environ.get('OLLAMA_BASE_URL')
    env_ollama_model = os.environ.get('OLLAMA_MODEL')
    env_dashscope_key = os.environ.get('DASHSCOPE_API_KEY')
    env_dashscope_base_url = os.environ.get('DASHSCOPE_BASE_URL')
    openai_api_key = env_openai_key
    weather_api_key = env_weather_key
    airs_api_key = env_airs_key
    serpapi_api_key = env_serp_key
    dashscope_api_key = env_dashscope_key
    dashscope_base_url = env_dashscope_base_url or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_model = "qwen-plus"
    ollama_base_url = env_ollama_base_url or ""
    ollama_model = env_ollama_model or "qwen3:8b"
    enable_ollama_fallback = False
    warm_fallback_ollama = False
    detected_ollama_base_url = env_ollama_base_url or "http://localhost:11434"
    ollama_available = _is_ollama_reachable(detected_ollama_base_url)

    # API Keys
    st.subheader("API Keys")
    
    # OpenAI Key Logic
    if env_openai_key:
        openai_api_key = env_openai_key
        st.success("✅ OpenAI API Key loaded")
    else:
        openai_api_key = st.text_input("OpenAI API Key", type="password", key="openai_key")
        
    # Weather Key Logic
    if env_weather_key:
        weather_api_key = env_weather_key
        st.success("✅ Weather API Key loaded")
    else:
        weather_api_key = st.text_input("Weather API Key", type="password", key="weather_key")
    
    # AIRS Security Key Logic
    if env_airs_key:
        airs_api_key = env_airs_key
        st.success("✅ AIRS API Key loaded")
    else:
        airs_api_key = st.text_input(
            "AIRS API Key (Optional)",
            type="password",
            key="airs_key",
            help="Palo Alto Networks Prisma AIRS for runtime security"
        )
        if airs_api_key:
            st.success("✅ AIRS API Key loaded")

    # SerpAPI Key Logic (optional)
    if env_serp_key:
        serpapi_api_key = env_serp_key
        st.success("✅ SerpAPI Key loaded")
    else:
        serpapi_api_key = st.text_input(
            "SerpAPI Key (Optional)",
            type="password",
            key="serpapi_key",
            help="Enables live web search fallback"
        )

    # Qwen (DashScope) Key Logic (optional for critic, required when Qwen is primary)
    if env_dashscope_key:
        dashscope_api_key = env_dashscope_key
        st.success("✅ Qwen API Key loaded")
    else:
        dashscope_api_key = st.text_input(
            "Qwen API Key (Optional, Critic)",
            type="password",
            key="dashscope_key",
            help="Used for Qwen provider or optional cross-LLM critic."
        )
        if dashscope_api_key:
            st.success("✅ Qwen API Key loaded")
    
    # Settings
    st.subheader("Settings")
    st.text_input(
        "Default City",
        key="landing_location",
        help="Used for hero background and default examples.",
    )
    st.subheader("Appearance")
    bg_upload = st.file_uploader(
        "City background image (optional)",
        type=["png", "jpg", "jpeg", "webp"],
        key="city_bg_upload",
        help="Overrides auto-fetched background for the selected city.",
    )
    if bg_upload is not None:
        bg_bytes = bg_upload.getvalue()
        bg_hash = hashlib.sha256(bg_bytes).hexdigest()
        bg_signature = f"{(st.session_state.get('landing_location') or 'Singapore').strip().lower()}:{bg_hash}"
        if bg_signature != st.session_state.get("last_bg_upload_signature"):
            city = (st.session_state.get("landing_location") or "Singapore").strip() or "Singapore"
            ext = (os.path.splitext(bg_upload.name)[1].lower().lstrip(".") or "jpg")
            cache_key = _location_cache_key(city)
            for old_ext in ("jpg", "jpeg", "png", "webp"):
                old_path = os.path.join(bg_cache_dir, f"{cache_key}.{old_ext}")
                if os.path.exists(old_path):
                    os.remove(old_path)
            save_path = _location_cache_path(city, ext)
            with open(save_path, "wb") as f:
                f.write(bg_bytes)
            st.session_state.last_bg_upload_signature = bg_signature
            st.success(f"✅ Background uploaded for {city}.")

    mascot_upload = st.file_uploader(
        "Mascot image (optional)",
        type=["png", "jpg", "jpeg", "webp"],
        key="mascot_upload",
        help="Upload a custom mascot image for the landing card.",
    )
    if mascot_upload is not None:
        mascot_bytes = mascot_upload.getvalue()
        mascot_hash = hashlib.sha256(mascot_bytes).hexdigest()
        if mascot_hash != st.session_state.get("last_mascot_upload_hash"):
            ext = (os.path.splitext(mascot_upload.name)[1].lower().lstrip(".") or "png")
            for old_ext in ("png", "jpg", "jpeg", "webp"):
                old_path = os.path.join(mascot_cache_dir, f"mascot.{old_ext}")
                if os.path.exists(old_path):
                    os.remove(old_path)
            mascot_path = os.path.join(mascot_cache_dir, f"mascot.{ext}")
            with open(mascot_path, "wb") as f:
                f.write(mascot_bytes)
            st.session_state.mascot_path = mascot_path
            st.session_state.last_mascot_upload_hash = mascot_hash
            st.success("✅ Mascot uploaded.")

    st.subheader("RAG Documents")
    rag_uploads = st.file_uploader(
        "Upload RAG files (PDF/TXT/MD)",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
        key="rag_docs_upload",
        help="These files will be used by the Future Info / RAG agent.",
    )
    if rag_uploads:
        for upload in rag_uploads:
            doc_bytes = upload.getvalue()
            doc_hash = hashlib.sha256(doc_bytes).hexdigest()[:12]
            ext = os.path.splitext(upload.name)[1].lower() or ".pdf"
            base = re.sub(r"[^a-zA-Z0-9._-]+", "_", os.path.splitext(upload.name)[0]).strip("_") or "rag_doc"
            save_name = f"{base}_{doc_hash}{ext}"
            save_path = os.path.join(rag_upload_dir, save_name)
            if not os.path.exists(save_path):
                with open(save_path, "wb") as f:
                    f.write(doc_bytes)
        st.success(f"✅ Uploaded {len(rag_uploads)} RAG document(s).")

    default_rag_doc = os.path.join(data_dir, "Singapore_2026_Major_Events.pdf")
    available_rag_docs = []
    if os.path.exists(default_rag_doc):
        available_rag_docs.append(default_rag_doc)
    for fname in sorted(os.listdir(rag_upload_dir)):
        if fname.lower().endswith((".pdf", ".txt", ".md")):
            available_rag_docs.append(os.path.join(rag_upload_dir, fname))

    doc_labels = {p: ("Default: Singapore 2026 Major Events" if p == default_rag_doc else os.path.basename(p)) for p in available_rag_docs}
    default_selection = st.session_state.get("selected_rag_docs") or ([default_rag_doc] if os.path.exists(default_rag_doc) else [])
    selected_rag_docs = st.multiselect(
        "Active RAG documents",
        options=available_rag_docs,
        default=[p for p in default_selection if p in available_rag_docs],
        format_func=lambda p: doc_labels.get(p, os.path.basename(p)),
        help="Pick one or more documents to index when initializing the assistant.",
    )
    st.session_state.selected_rag_docs = selected_rag_docs

    warm_ollama = False
    enable_critic = st.checkbox(
        "Enable Critic LLM",
        value=True,
        help="Cross-check response quality with a secondary model; auto-skips on quota/errors."
    )
    provider_options = ["OpenAI", "Qwen"]
    if ollama_available:
        provider_options.insert(1, "Ollama")
        st.success(f"✅ Ollama reachable ({detected_ollama_base_url})")
    else:
        st.info("ℹ️ Ollama not reachable from this runtime. Hiding Ollama provider options.")

    if st.session_state.get("llm_provider_select") not in provider_options:
        st.session_state["llm_provider_select"] = provider_options[0]
    llm_provider = st.selectbox("LLM Provider", provider_options, key="llm_provider_select")
    if llm_provider == "OpenAI":
        llm_model = st.selectbox("LLM Model", ["gpt-5-mini", "gpt-5", "gpt-5.4"], index=0)
    else:
        if llm_provider == "Ollama":
            if env_ollama_base_url:
                st.success("✅ OLLAMA_BASE_URL loaded (you can override below)")
            ollama_base_url = st.text_input(
                "Ollama Base URL",
                value=env_ollama_base_url or ollama_base_url or "http://localhost:11434",
                help="For local Ollama, use http://localhost:11434"
            )
            ollama_preset = st.selectbox(
                "Ollama Preset Model",
                options=["qwen3:8b", "Custom"],
                index=0 if (ollama_model or "").startswith("qwen3:8b") else 1,
                help="Pick a local Ollama model quickly, or choose Custom."
            )
            ollama_model = st.text_input(
                "Ollama Model",
                value=(
                    "qwen3:8b"
                    if ollama_preset == "qwen3:8b"
                    else (ollama_model or "qwen3:8b")
                ),
                help="Example: qwen3:8b"
            )
            warm_ollama = st.checkbox(
                "Warm up Ollama on init",
                value=True,
                help="Sends a short prompt during initialization to reduce cold-start latency"
            )
            ollama_timeout = st.number_input(
                "Ollama timeout (seconds)",
                min_value=10,
                max_value=300,
                value=int(os.environ.get("OLLAMA_TIMEOUT", "60")),
                step=5,
                help="Increase this for slower local models to avoid read timeouts."
            )
            os.environ["OLLAMA_TIMEOUT"] = str(int(ollama_timeout))
            enable_cloud_handover = st.checkbox(
                "Escalate unclear Ollama answers to cloud LLM",
                value=bool(openai_api_key or dashscope_api_key),
                help="If Ollama returns unclear/partial output, retry the same prompt on cloud LLM."
            )
            os.environ["ENABLE_CLOUD_FALLBACK_FROM_OLLAMA"] = "1" if enable_cloud_handover else "0"
            cloud_choices = ["OpenAI", "Qwen", "Auto"]
            cloud_default = "OpenAI" if openai_api_key else "Qwen" if dashscope_api_key else "Auto"
            cloud_provider = st.selectbox(
                "Cloud handover target",
                options=cloud_choices,
                index=cloud_choices.index(cloud_default),
                disabled=not enable_cloud_handover
            )
            if cloud_provider == "OpenAI":
                os.environ["CLOUD_FALLBACK_PROVIDER"] = "openai"
                os.environ["CLOUD_FALLBACK_MODEL"] = "gpt-5-mini"
            elif cloud_provider == "Qwen":
                os.environ["CLOUD_FALLBACK_PROVIDER"] = "qwen"
                os.environ["CLOUD_FALLBACK_MODEL"] = "qwen-plus"
            else:
                os.environ["CLOUD_FALLBACK_PROVIDER"] = "auto"
                os.environ["CLOUD_FALLBACK_MODEL"] = ""
            # When Ollama is primary, cloud fallback is not used.
            os.environ["ENABLE_OLLAMA_FALLBACK"] = "0"
            os.environ["OLLAMA_FALLBACK_MODEL"] = ollama_model or "qwen3:8b"
            if st.button("Test Ollama connection"):
                try:
                    resp = requests.get(f"{ollama_base_url.rstrip('/')}/api/tags", timeout=5)
                    resp.raise_for_status()
                    st.success("✅ Ollama reachable")
                except Exception as e:
                    st.error(f"❌ Ollama test failed: {e}")
            llm_model = ollama_model
        else:
            if not dashscope_api_key:
                st.warning("Qwen API Key is required when LLM Provider is Qwen.")
            dashscope_base_url = st.text_input(
                "Qwen Base URL",
                value=dashscope_base_url,
                help="Singapore default: https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            )
            qwen_model = st.text_input(
                "Qwen Model",
                value=qwen_model,
                help="Recommended: qwen-plus"
            )
            llm_model = qwen_model
    if llm_provider != "Ollama":
        os.environ["ENABLE_CLOUD_FALLBACK_FROM_OLLAMA"] = "0"
        os.environ["CLOUD_FALLBACK_PROVIDER"] = os.environ.get("CLOUD_FALLBACK_PROVIDER", "openai")
        os.environ["CLOUD_FALLBACK_MODEL"] = os.environ.get("CLOUD_FALLBACK_MODEL", "")
        if ollama_available:
            enable_ollama_fallback = st.checkbox(
                "Use Ollama as fallback for cloud errors",
                value=bool(ollama_base_url),
                help="Requires Ollama Base URL. Falls back on quota/rate-limit/timeout."
            )
            if enable_ollama_fallback:
                ollama_base_url = st.text_input(
                    "Ollama Base URL (Fallback)",
                    value=env_ollama_base_url or ollama_base_url or "http://localhost:11434",
                    help="For local Ollama, use http://localhost:11434"
                )
                ollama_model = st.text_input(
                    "Ollama Fallback Model",
                    value=ollama_model or "qwen3:8b",
                    help="Example: qwen3:8b"
                )
                warm_fallback_ollama = st.checkbox(
                    "Warm up Ollama fallback on init",
                    value=True,
                    help="Runs a short test prompt so fallback is ready before first failure."
                )
            os.environ["ENABLE_OLLAMA_FALLBACK"] = "1" if enable_ollama_fallback else "0"
            if ollama_model:
                os.environ["OLLAMA_FALLBACK_MODEL"] = ollama_model
            if ollama_base_url:
                os.environ["OLLAMA_BASE_URL"] = ollama_base_url
        else:
            enable_ollama_fallback = False
            os.environ["ENABLE_OLLAMA_FALLBACK"] = "0"
    max_history = st.number_input("Conversation History", min_value=5, max_value=50, value=20, step=1)
    st.selectbox(
        "Audio input language",
        options=["auto", "en", "zh", "ms", "ta"],
        key="stt_language",
        format_func=lambda x: {
            "auto": "Auto-detect",
            "en": "English",
            "zh": "Chinese",
            "ms": "Malay",
            "ta": "Tamil",
        }.get(x, x),
        help="Language hint for transcription. Auto-detect is best for mixed language audio."
    )

    # Security Settings (only show if AIRS key provided)
    if airs_api_key:
        st.subheader("🔒 Security Settings")
        airs_mode = st.radio(
            "Prisma AIRS Runtime Security",
            ["ON", "OFF"],
            index=0,
            key="enable_airs_security",
            help="Route prompts and responses through AIRS Runtime Security"
        )
        enable_airs_security = airs_mode == "ON"
        prompt_mode = st.radio(
            "Scan User Prompts",
            ["ON", "OFF"],
            index=0,
            disabled=not enable_airs_security
        )
        enable_prompt_scan = prompt_mode == "ON"
        response_mode = st.radio(
            "Scan AI Responses",
            ["ON", "OFF"],
            index=0,
            disabled=not enable_airs_security
        )
        enable_response_scan = response_mode == "ON"
        # Block on real threats when AIRS is enabled
        block_on_threat = enable_airs_security
        
        # Show security stats if controller exists
        if st.session_state.controller and hasattr(st.session_state.controller, 'security_agent'):
            if st.session_state.controller.security_agent:
                with st.expander("📊 Security Statistics"):
                    stats_placeholder = st.empty()
                with st.expander("🧪 AIRS Verdict (Last Request)"):
                    verdict_placeholder = st.empty()
                with st.expander("📦 AIRS Request Payload (Last Request)"):
                    payload_placeholder = st.empty()
                with st.expander("🚫 Blocked/Filtered Events"):
                    blocked_placeholder = st.empty()
    else:
        # Placeholder for security settings when no key
        st.info("💡 Add AIRS API Key to enable runtime security monitoring")
    
    # Initialize button
    init_label = "🔄 Restart Assistant" if st.session_state.get("initialized") else "🚀 Initialize Assistant"
    if st.button(init_label, type="primary"):
        if not openai_api_key or not weather_api_key:
            st.error("Please provide both API keys!")
        elif llm_provider == "Ollama" and not ollama_base_url:
            st.error("Please provide Ollama Base URL.")
        elif llm_provider == "Qwen" and not dashscope_api_key:
            st.error("Please provide Qwen API Key.")
        else:
            with st.spinner("Initializing agents..."):
                try:
                    # Initialize all agents
                    chat_agent = ChatAgent(max_history=max_history)
                    weather_agent = WeatherAgent(weather_api_key)
                    
                    # Use selected RAG documents from sidebar (fall back to default file).
                    default_rag_doc = os.path.join(data_dir, "Singapore_2026_Major_Events.pdf")
                    rag_doc_paths = st.session_state.get("selected_rag_docs") or []
                    if not rag_doc_paths and os.path.exists(default_rag_doc):
                        rag_doc_paths = [default_rag_doc]
                    
                    event_agent = EventAgent(db_path)
                    provider_key = (
                        "ollama" if llm_provider == "Ollama"
                        else "qwen" if llm_provider == "Qwen"
                        else "openai"
                    )
                    should_warm_ollama = (
                        (provider_key == "ollama" and warm_ollama)
                        or (provider_key != "ollama" and enable_ollama_fallback and warm_fallback_ollama and ollama_base_url)
                    )
                    if should_warm_ollama:
                        try:
                            warm_provider = "ollama"
                            warm_model = ollama_model or "qwen3:8b"
                            warm_client = LLMClient(
                                provider=warm_provider,
                                openai_api_key=openai_api_key,
                                ollama_base_url=ollama_base_url,
                                qwen_api_key=dashscope_api_key,
                                qwen_base_url=dashscope_base_url,
                            )
                            # Warm-up should validate local Ollama only (no cloud handover).
                            warm_client.cloud_fallback_from_ollama = False
                            _ = warm_client.chat(
                                messages=[{"role": "user", "content": "hi"}],
                                model=warm_model,
                                max_tokens=5,
                                temperature=0.0,
                            )
                            st.caption("✅ Ollama warmed up")
                        except Exception as e:
                            st.warning(f"⚠️ Ollama warm-up failed: {e}")
                    recommendation_agent = RecommendationAgent(
                        openai_api_key,
                        model=llm_model,
                        llm_provider=provider_key,
                        ollama_base_url=ollama_base_url,
                        qwen_api_key=dashscope_api_key,
                        qwen_base_url=dashscope_base_url,
                    )
                    try:
                        rag_agent = RAGAgent(
                            openai_api_key,
                            rag_doc_paths,
                            llm_model,
                            llm_provider=provider_key,
                            ollama_base_url=ollama_base_url,
                            qwen_api_key=dashscope_api_key,
                            qwen_base_url=dashscope_base_url,
                        )
                    except Exception as e:
                        st.warning(f"⚠️ RAG initialization skipped: {e}")
                        rag_agent = DisabledRAGAgent(str(e))
                    image_agent = ImageAgent(openai_api_key)
                    search_agent = SearchAgent(serpapi_api_key) if serpapi_api_key else None
                    critic_agent = None

                    # Cross-LLM critic selection:
                    # - OpenAI primary -> Qwen critic
                    # - Qwen primary -> OpenAI critic
                    # - Ollama primary -> OpenAI (fallback Qwen)
                    if enable_critic:
                        critic_provider = None
                        critic_model = None
                        if provider_key == "openai" and dashscope_api_key:
                            critic_provider = "qwen"
                            critic_model = "qwen-plus"
                        elif provider_key == "qwen" and openai_api_key:
                            critic_provider = "openai"
                            critic_model = "gpt-5-mini"
                        elif provider_key == "ollama":
                            if openai_api_key:
                                critic_provider = "openai"
                                critic_model = "gpt-5-mini"
                            elif dashscope_api_key:
                                critic_provider = "qwen"
                                critic_model = "qwen-plus"

                        if critic_provider and critic_model:
                            try:
                                critic_agent = CriticAgent(
                                    provider=critic_provider,
                                    model=critic_model,
                                    openai_api_key=openai_api_key,
                                    ollama_base_url=ollama_base_url,
                                    qwen_api_key=dashscope_api_key,
                                    qwen_base_url=dashscope_base_url,
                                )
                                if critic_agent.is_enabled():
                                    st.caption(f"✅ Critic enabled: {critic_provider} ({critic_model})")
                                else:
                                    st.caption("ℹ️ Critic disabled (provider not ready)")
                            except Exception as e:
                                st.warning(f"⚠️ Critic initialization failed; continuing without critic: {e}")
                                critic_agent = None
                        else:
                            st.caption("ℹ️ Critic skipped (cross-provider key/model unavailable)")
                    
                    # Initialize SecurityAgent if API key provided and enabled
                    security_agent = None
                    if airs_api_key and enable_airs_security:
                        try:
                            security_agent = SecurityAgent(
                                api_key=airs_api_key,
                                enable_prompt_scan=enable_prompt_scan,
                                enable_response_scan=enable_response_scan,
                                block_on_threat=block_on_threat,
                                timeout=5
                            )
                            
                            # Test connection
                            is_healthy, health_msg = security_agent.health_check()
                            if is_healthy:
                                st.success(f"🔒 {health_msg}")
                            else:
                                st.warning(f"⚠️ {health_msg}")
                        except Exception as e:
                            st.warning(f"⚠️ Security Agent initialization failed: {str(e)}")
                            security_agent = None
                    
                    # Initialize controller with security
                    st.session_state.controller = ControllerAgent(
                        chat_agent,
                        weather_agent,
                        event_agent,
                        recommendation_agent,
                        rag_agent,
                        image_agent,
                        openai_api_key,
                        llm_provider=provider_key,
                        llm_model=llm_model,
                        ollama_base_url=ollama_base_url,
                        qwen_api_key=dashscope_api_key,
                        qwen_base_url=dashscope_base_url,
                        security_agent=security_agent,
                        search_agent=search_agent,
                        critic_agent=critic_agent,
                    )
                    
                    st.session_state.initialized = True
                    st.session_state.voice_greeted = False
                    st.success("✅ Assistant initialized successfully!")
                except Exception as e:
                    err = str(e)
                    if "insufficient_quota" in err.lower() or "429" in err:
                        st.error(
                            "Initialization failed due to provider quota limits. "
                            "Please verify billing/credits for the active provider "
                            "(OpenAI or Qwen) and retry."
                        )
                    else:
                        st.error(f"Initialization failed: {err}")

    # Persist security telemetry panels across reruns.
    if stats_placeholder is not None and st.session_state.get("controller"):
        try:
            stats = st.session_state.controller.get_security_stats()
            if stats.get("enabled"):
                with stats_placeholder.container():
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Total Scans", stats.get("total_scans", 0))
                        st.metric("Threats", stats.get("threats_detected", 0))
                    with col2:
                        st.metric("Blocked", stats.get("blocked_requests", 0))
                        st.metric("Threat Rate", f"{stats.get('threat_rate', 0.0):.1f}%")
            else:
                stats_placeholder.info("Security monitoring is currently disabled.")
        except Exception:
            stats_placeholder.info("Security statistics unavailable.")

    if verdict_placeholder is not None:
        verdict = st.session_state.get("last_security_verdict")
        if verdict:
            verdict_placeholder.json(verdict)
        else:
            verdict_placeholder.info("No AIRS verdict yet.")

    if payload_placeholder is not None:
        payload = st.session_state.get("last_airs_request")
        if payload:
            payload_placeholder.json(_redact_sensitive_fields(payload))
        else:
            payload_placeholder.info("No AIRS payload yet.")

    if blocked_placeholder is not None:
        events = st.session_state.get("security_events", [])
        if events:
            lines = []
            for event in events[-5:][::-1]:
                lines.append(
                    f"- **{event['kind']}** · {event['threat_type']} · "
                    f"`{event['time']}`\n  - {event['summary']}"
                )
            blocked_placeholder.markdown("\n".join(lines))
        else:
            blocked_placeholder.info("No blocked/filtered events yet.")

    # Avoid duplicate success banners on rerun
    # (initialization already shows a success message)
    # if st.session_state.get("initialized"):
    #     st.success("✅ Assistant initialized successfully!")
    
    # Clear conversation
    if st.button("🗑️ Clear Conversation"):
        st.session_state.messages = []
        if st.session_state.controller:
            st.session_state.controller.chat_agent.clear_history()
        st.rerun()

    # Voice Output
    st.subheader("Voice Output")
    if "voice_enabled" not in st.session_state:
        st.session_state.voice_enabled = False
    voice_enabled = st.checkbox("Assistant Voice", key="voice_enabled")
    st.caption("AI-generated voice via OpenAI TTS when a key is available.")

    # If user toggles voice off, stop any in-flight browser speech/audio immediately.
    if (
        st.session_state.get("voice_last_enabled", False)
        and not st.session_state.get("voice_enabled", False)
    ):
        components.html(
            """
            <script>
            (() => {
                try {
                    if (window.speechSynthesis) {
                        window.speechSynthesis.cancel();
                    }
                    const audios = document.querySelectorAll("audio");
                    audios.forEach((a) => {
                        try {
                            a.pause();
                            a.currentTime = 0;
                        } catch (e) {}
                    });
                } catch (e) {}
            })();
            </script>
            """,
            height=0,
        )
    st.session_state.voice_last_enabled = st.session_state.get("voice_enabled", False)

    st.session_state.voice_rate = st.session_state.get("voice_rate", 1.0)
    st.session_state.voice_pitch = st.session_state.get("voice_pitch", 1.0)
    st.session_state.voice_volume = st.session_state.get("voice_volume", 1.0)
    st.session_state.voice_name = st.session_state.get("voice_name", "marin")

    if st.session_state.get("initialized") and voice_enabled and not st.session_state.get("voice_greeted"):
        greeting_text = (
            "Welcome to the Multi-Agent AI Assistant. I can help with time, weather, "
            "event search, recommendations, and image generation. You can turn my voice "
            "on or off in the sidebar anytime using the Assistant Voice button. "
            "Have a nice day!"
        )
        _play_voice(greeting_text, allow_autoplay=True)
        st.session_state.voice_greeted = True
    
    # Info section
    st.divider()
    st.subheader("ℹ️ Capabilities")
    st.markdown("""
    - 🎯 **Recommendations** - Activity suggestions
    - 📋 **Events** - Search and filter events
    - 📚 **Future Info** - 2026 events lookup
    - 🎨 **Images** - Generate AI images
    - ☁️ **Weather** - Real-time forecasts
    - ⏰ **Time** - Current date/time
    - 🔒 **Security** - AIRS runtime protection
    """)

# Background image (cached per location)
landing_location = (st.session_state.get("landing_location") or "Singapore").strip() or "Singapore"
background_data_uri = _get_cached_background(landing_location)
if background_data_uri:
    banner_bg_style = f"background-image: linear-gradient(140deg, rgba(255, 255, 255, 0.7) 0%, rgba(255, 255, 255, 0.4) 40%, rgba(255, 255, 255, 0.15) 100%), url('{background_data_uri}');"
else:
    banner_bg_style = "background: linear-gradient(140deg, #d9f8ff 0%, #fff1e6 55%, #ffffff 100%);"

# Main chat interface

# Landing hero (shown before and after initialization)
mascot_path = st.session_state.get("mascot_path") or _get_saved_mascot_path()
mascot_data_uri = ""
if mascot_path:
    mascot_data_uri = _image_to_data_uri(mascot_path)
    mascot_layer = f'<div class="mascot-bg" style="background-image: url(\'{mascot_data_uri}\');"></div>'
else:
    mascot_markup = """
        <svg width="260" height="260" viewBox="0 0 260 260" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="helm" x1="30" y1="40" x2="230" y2="220" gradientUnits="userSpaceOnUse">
                    <stop stop-color="#FFD5EC"/>
                    <stop offset="1" stop-color="#B9E1FF"/>
                </linearGradient>
                <linearGradient id="visor" x1="70" y1="95" x2="190" y2="165" gradientUnits="userSpaceOnUse">
                    <stop stop-color="#2E3C4A"/>
                    <stop offset="1" stop-color="#101821"/>
                </linearGradient>
            </defs>
            <circle cx="130" cy="140" r="98" fill="url(#helm)"/>
            <ellipse cx="130" cy="150" rx="78" ry="62" fill="url(#visor)"/>
            <circle cx="100" cy="150" r="10" fill="#FFD1A1"/>
            <circle cx="160" cy="150" r="10" fill="#FFD1A1"/>
            <circle cx="130" cy="78" r="16" fill="#FFE6A8"/>
            <rect x="106" y="173" width="48" height="18" rx="9" fill="#FF8A7A"/>
            <path d="M85 110C95 95 115 90 130 90C145 90 165 95 175 110" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round"/>
            <circle cx="40" cy="145" r="18" fill="#B7C8FF"/>
            <circle cx="220" cy="145" r="18" fill="#B7C8FF"/>
            <rect x="120" y="20" width="20" height="46" rx="10" fill="#C5F2FF"/>
            <circle cx="130" cy="18" r="14" fill="#FFE6A8"/>
            <circle cx="130" cy="18" r="6" fill="#FF8A7A"/>
        </svg>
    """
    mascot_layer = f'<div class="mascot-core">{mascot_markup}</div>'

st.markdown(
    f"""
    <div class="landing-wrap">
        <div class="landing-backdrop" style="{banner_bg_style}"></div>
        <div class="landing-hero centered">
            <div class="landing-title">Agentic AI Tourist Chatbot</div>
            <div class="mascot-stage">
                <div class="bubble bubble-1 bubble-float"><div class="bubble-title"><span class="icon">⏰</span>Time</div><span>Current date and time around the world</span></div>
                <div class="bubble bubble-2 bubble-float"><div class="bubble-title"><span class="icon">☁️</span>Weather</div><span>Realtime weather forecast</span></div>
                <div class="bubble bubble-3 bubble-float"><div class="bubble-title"><span class="icon">🧭</span>Activities</div><span>Indoor &amp; outdoor actvities for today and tomorrow</span></div>
                <div class="bubble bubble-4 bubble-float"><div class="bubble-title"><span class="icon">🎯</span>Recommendations</div><span>Activity recommendations</span></div>
                <div class="bubble bubble-5 bubble-float"><div class="bubble-title"><span class="icon">📚</span>2026 Events</div><span>Key events in 2026</span></div>
                <div class="bubble bubble-6 bubble-float"><div class="bubble-title"><span class="icon">🎨</span>Images</div><span>Generate fun images</span></div>
                {mascot_layer}
            </div>
        </div>
        <div class="landing-prompt">
    """,
    unsafe_allow_html=True,
)

if not background_data_uri:
    st.info("City background image not available. Upload one in the sidebar or check network access.")

st.markdown(
    """
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Prisma AIRS status indicator (for demo visibility)
airs_status = "OFF"
if st.session_state.get("controller") and getattr(st.session_state.controller, "security_agent", None):
    if st.session_state.controller.security_agent.enabled:
        airs_status = "ON"

if airs_status == "ON":
    st.success("Prisma AIRS Runtime Security: ON")
else:
    # Fallback placeholders if security sidebar is not available
    stats_placeholder = None
    verdict_placeholder = None
    payload_placeholder = None
    blocked_placeholder = None
    st.warning("Prisma AIRS Runtime Security: OFF")

# Display initialization status
if not st.session_state.initialized:
    st.info("👈 Configure API keys and initialize the assistant in the sidebar to begin.")
    st.text_input(
        "Ask me anything",
        placeholder=f"I am Amanda, your intelligent event and activity companion - ask me anyting to plan, search, recommend, or create fun activities in {landing_location}.",
        label_visibility="collapsed",
        key="landing_prompt",
    )
else:
    intent_labels = {
        "SECURITY_BLOCKED": "Security Agent",
        "SECURITY_FILTERED": "Security Agent",
        "TIME_QUERY": "Time Agent",
        "WEATHER_QUERY": "Weather Agent",
        "RECOMMENDATION": "Recommendation Agent",
        "RAG_QUERY": "RAG Agent",
        "EVENT_QUERY_DB": "SQL Agent",
        "IMAGE_GENERATION": "Image Agent",
        "UNKNOWN": "LLM Direct",
    }

    def _format_multi_intent(intent: str, critic: dict = None) -> str:
        critic_suffix = ""
        if isinstance(critic, dict) and critic.get("enabled"):
            status = str(critic.get("status", "")).lower()
            provider = str(critic.get("provider", "")).strip()
            provider_label = provider.title() if provider else "Critic"
            if status in {"applied", "kept", "clarification_requested"}:
                critic_suffix = f" + Critic Agent ({provider_label})"
            elif status == "skipped_quota":
                critic_suffix = " + Critic Agent (Skipped: Quota)"
            else:
                critic_suffix = " + Critic Agent (Skipped)"

        if not intent.startswith("MULTI:"):
            return f"{intent_labels.get(intent, intent)}{critic_suffix}"
        parts = intent.replace("MULTI:", "").split("+")
        labels = [intent_labels.get(p, p) for p in parts]
        if len(labels) == 1:
            return f"{labels[0]}{critic_suffix}"
        if len(labels) == 2:
            return f"Multiple Agents: {labels[0]} and {labels[1]}{critic_suffix}"
        return f"Multiple Agents: {', '.join(labels[:-1])}, and {labels[-1]}{critic_suffix}"

    def _render_response(text: str):
        if not isinstance(text, str):
            st.markdown(text)
            return
        # Normalize markdown/math artifacts that cause mixed fonts and broken inline equations.
        clean = unicodedata.normalize("NFKC", text)
        clean = clean.replace("```", "").replace("`", "")
        clean = re.sub(
            r"\n\s*([0-9]+(?:\.[0-9]+)?)\s*\n\s*([xX×*∗])\s*\n\s*([0-9]+(?:\.[0-9]+)?)\s*",
            r"\n\1 \2 \3 ",
            clean,
        )
        clean = re.sub(r"\s*\n\s*=\s*\n\s*", " = ", clean)
        clean = re.sub(r"\s*\n\s*([xX×*∗])\s*\n\s*", r" \1 ", clean)
        # Remove accidental emphasis markers from model outputs to keep typography consistent.
        clean = clean.replace("**", "").replace("__", "")
        # Avoid markdown math renderer switching fonts on inline `$...$`.
        clean = re.sub(r"(?<!\\)\$", r"\\$", clean)
        clean = re.sub(r"\n{3,}", "\n\n", clean)
        st.markdown(clean)
    # Display chat messages
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            # Display Intent Badge if present
            if "intent" in message:
                label = _format_multi_intent(message["intent"], message.get("critic"))
                st.markdown(f'<div class="intent-badge">🔍 {label}</div>', unsafe_allow_html=True)
                critic_meta = message.get("critic") if isinstance(message.get("critic"), dict) else {}
                critic_status = str(critic_meta.get("status", "")).lower()
                if critic_status.startswith("skipped"):
                    reason = str(critic_meta.get("reason", "")).strip()
                    if reason:
                        st.caption(f"Critic skipped reason: {reason}")
            if message.get("security_badge"):
                st.markdown(
                    '<div style="display:inline-block;background:#c62828;color:white;'
                    'padding:0.15rem 0.4rem;border-radius:0.3rem;font-size:0.75rem;'
                    'font-weight:bold;margin-bottom:0.4rem;">AIRS BLOCKED</div>',
                    unsafe_allow_html=True
                )
            _render_response(message["content"])
    
    # Compact composer: text input + mic button + submit button.
    if "prompt_draft" not in st.session_state:
        st.session_state.prompt_draft = ""
    if st.session_state.get("clear_prompt_draft"):
        st.session_state.prompt_draft = ""
        st.session_state.clear_prompt_draft = False
    if st.session_state.get("prompt_prefill"):
        st.session_state.prompt_draft = st.session_state.get("prompt_prefill", "")
        st.session_state.prompt_prefill = ""
    prompt = (st.session_state.get("queued_prompt") or "").strip() or None
    if prompt:
        st.session_state.queued_prompt = ""
    composer_cols = st.columns([0.84, 0.08, 0.08], vertical_alignment="bottom")
    with composer_cols[0]:
        st.text_input(
            "Message",
            key="prompt_draft",
            label_visibility="collapsed",
            placeholder=f"I am Amanda, your intelligent event and activity companion - ask me anyting to plan, search, recommend, or create fun activities in {landing_location}.",
        )
    with composer_cols[1]:
        with st.popover("Mic", use_container_width=True):
            st.caption("Record and auto-fill message")
            audio_clip = None
            if hasattr(st, "audio_input"):
                audio_clip = st.audio_input("Audio", label_visibility="collapsed")
            else:
                audio_clip = st.file_uploader(
                    "Upload audio",
                    type=["wav", "mp3", "m4a", "webm"],
                    key="audio_upload_fallback",
                    label_visibility="collapsed",
                )
            if audio_clip is not None:
                audio_bytes = audio_clip.getvalue()
                audio_name = getattr(audio_clip, "name", "speech.webm")
                audio_type = getattr(audio_clip, "type", "audio/webm") or "audio/webm"
                audio_hash = hashlib.sha256(audio_bytes).hexdigest()
                if audio_hash != st.session_state.get("audio_last_transcribed_hash"):
                    active_openai_key = openai_api_key or st.session_state.get("openai_key", "")
                    if not active_openai_key:
                        st.error("OpenAI API Key is required for audio transcription.")
                    else:
                        with st.spinner("Transcribing..."):
                            try:
                                language_hint = st.session_state.get("stt_language", "auto")
                                transcript = _transcribe_audio(
                                    audio_bytes,
                                    active_openai_key,
                                    language_code=None if language_hint == "auto" else language_hint,
                                    filename=audio_name,
                                    mime_type=audio_type,
                                )
                                st.session_state.audio_last_transcribed_hash = audio_hash
                                if transcript:
                                    st.session_state.prompt_prefill = transcript
                                    st.rerun()
                                else:
                                    st.warning("Could not detect speech. Try again.")
                            except Exception as e:
                                st.error(f"Audio transcription failed: {e}")
    with composer_cols[2]:
        send_clicked = st.button("Send", key="send_prompt_btn", use_container_width=True, type="primary")
    if send_clicked:
        typed = (st.session_state.get("prompt_draft") or "").strip()
        if typed:
            st.session_state.queued_prompt = typed
            st.session_state.clear_prompt_draft = True
            st.rerun()
        else:
            st.warning("Please enter or record a prompt first.")
    if prompt:
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # Always call AIRS (via controller). Demo mode can force a block
                    # when AIRS detects a threat even if policy would allow it.
                    result = st.session_state.controller.handle_query(
                        prompt,
                        user_id=st.session_state.get("user_session_id", "session_unknown")
                    )
                    
                    # Handle dictionary response from updated controller
                    if isinstance(result, dict):
                        response = result["response"]
                        intent = result.get("intent", "UNKNOWN")
                        security_badge = intent in ["SECURITY_BLOCKED", "SECURITY_FILTERED"]
                        
                        # Show security status if available
                        if result.get("security_scanned"):
                            scan_time = result.get("scan_time_ms", 0)
                            st.caption(f"🔒 Security scanned ({scan_time:.0f}ms)")
                            st.session_state.last_security_verdict = result.get("security")
                            if result.get("airs_request_payload"):
                                st.session_state.last_airs_request = result.get("airs_request_payload")
                            elif st.session_state.controller and st.session_state.controller.security_agent:
                                st.session_state.last_airs_request = getattr(
                                    st.session_state.controller.security_agent,
                                    "last_request_payload",
                                    None
                                )
                            if stats_placeholder is not None and st.session_state.controller:
                                stats = st.session_state.controller.get_security_stats()
                                if stats.get('enabled'):
                                    with stats_placeholder.container():
                                        col1, col2 = st.columns(2)
                                        with col1:
                                            st.metric("Total Scans", stats['total_scans'])
                                            st.metric("Threats", stats['threats_detected'])
                                        with col2:
                                            st.metric("Blocked", stats['blocked_requests'])
                                            st.metric("Threat Rate", f"{stats['threat_rate']:.1f}%")
                            # Update sidebar immediately if placeholders exist
                            if verdict_placeholder is not None:
                                verdict = st.session_state.last_security_verdict
                                if verdict:
                                    mapping = None
                                    try:
                                        prompt_block = verdict.get("prompt", {})
                                        mapping = (
                                            prompt_block.get("attack_mapping")
                                            or prompt_block.get("details", {}).get("_attack_mapping")
                                            or prompt_block.get("details", {}).get("details", {}).get("_attack_mapping")
                                        )
                                    except Exception:
                                        mapping = None
                                    if mapping:
                                        lines = ["**Attack Classification (mapped):**"]
                                        for m in mapping:
                                            lines.append(
                                                f"- **{m.get('type')} / {m.get('category')}** — "
                                                f"Impact: {m.get('impact')} (Reason: {m.get('reason')})"
                                            )
                                        verdict_placeholder.markdown("\n".join(lines))
                                    else:
                                        verdict_placeholder.json(verdict)
                                else:
                                    verdict_placeholder.info("No AIRS verdict yet.")
                            if payload_placeholder is not None:
                                payload = st.session_state.last_airs_request
                                if payload:
                                    payload_placeholder.json(_redact_sensitive_fields(payload))
                                else:
                                    payload_placeholder.info("No AIRS payload yet.")
                        
                        # Capture blocked or filtered events for demo visibility
                        security_status = result.get("security_status")
                        threat_type = result.get("threat_type", "unknown")
                        if intent in ["SECURITY_BLOCKED", "SECURITY_FILTERED"] or security_status == "blocked":
                            event_kind = "Blocked Prompt" if intent == "SECURITY_BLOCKED" else "Filtered Response"
                            # Prefer mapped attack/category for display
                            attack_label = None
                            try:
                                mapping = result.get("security", {}).get("prompt", {}).get("attack_mapping")
                                if mapping:
                                    top = mapping[0]
                                    attack_label = f"{top.get('type')} / {top.get('category')}"
                            except Exception:
                                attack_label = None
                            if not attack_label:
                                details = result.get("security", {}).get("prompt", {}).get("details", {})
                                flags = details.get("prompt_detected", {}) if isinstance(details, dict) else {}
                                active_flags = [k.replace("_", " ").title() for k, v in flags.items() if v]
                                attack_label = " / ".join(active_flags) if active_flags else None
                            st.session_state.security_events.append({
                                "kind": event_kind,
                                "threat_type": attack_label or threat_type,
                                "summary": prompt[:120],
                                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            if blocked_placeholder is not None:
                                events = st.session_state.security_events
                                if events:
                                    lines = []
                                    for event in events[-5:][::-1]:
                                        lines.append(
                                            f"- **{event['kind']}** · {event['threat_type']} · "
                                            f"`{event['time']}`\n  - {event['summary']}"
                                        )
                                    blocked_placeholder.markdown("\n".join(lines))
                                else:
                                    blocked_placeholder.info("No blocked/filtered events yet.")
                    else:
                        # Fallback for legacy support
                        response = result
                        intent = "UNKNOWN"
                        security_badge = False
                    
                    # Display Intent
                    label = _format_multi_intent(intent, result.get("critic"))
                    st.markdown(f'<div class="intent-badge">🔍 {label}</div>', unsafe_allow_html=True)
                    if security_badge:
                        st.markdown(
                            '<div style="display:inline-block;background:#c62828;color:white;'
                            'padding:0.15rem 0.4rem;border-radius:0.3rem;font-size:0.75rem;'
                            'font-weight:bold;margin-bottom:0.4rem;">AIRS BLOCKED</div>',
                            unsafe_allow_html=True
                        )
                        mapping = None
                        try:
                            mapping = result.get("security", {}).get("prompt", {}).get("attack_mapping")
                        except Exception:
                            mapping = None
                        if mapping:
                            top = mapping[0]
                            st.markdown(
                                f'<div class="attack-banner">Detected Attack: {top.get("type")} / {top.get("category")} '
                                f'— Impact: {top.get("impact")}</div>',
                                unsafe_allow_html=True
                            )
                            st.markdown(
                                f'<div class="attack-panel">'
                                f'<strong>Reason:</strong> {top.get("reason")}'
                                f'</div>',
                                unsafe_allow_html=True
                            )
                        else:
                            # Fallback to AIRS category/flags if mapping not available
                            details = None
                            try:
                                details = result.get("security", {}).get("prompt", {}).get("details", {})
                            except Exception:
                                details = {}
                            category = details.get("category")
                            flags = details.get("prompt_detected", {}) if isinstance(details, dict) else {}
                            flag_labels = {
                                "agent": "System/Tool Manipulation",
                                "injection": "Prompt Injection",
                                "dlp": "Data Exfiltration",
                                "malicious_code": "Malicious Code",
                                "topic_violation": "Topic Violation",
                                "toxic_content": "Toxic Content",
                                "url_cats": "Suspicious URLs",
                            }
                            active_flags = [
                                flag_labels.get(k, k.replace("_", " ").title())
                                for k, v in flags.items() if v
                            ]
                            label = " / ".join(active_flags) if active_flags else (category.title() if category else "Unclassified")
                            st.markdown(
                                f'<div class="attack-banner">Detected Attack: {label} (AIRS flagged)</div>',
                                unsafe_allow_html=True
                            )
                    _render_response(response)

                    # Voice playback controlled by Assistant Voice toggle
                    if st.session_state.get("voice_enabled") and st.session_state.get("initialized"):
                        _play_voice(response)
                    
                    # Add assistant message with intent
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": response,
                        "intent": intent,
                        "security_badge": security_badge,
                        "critic": result.get("critic"),
                    })
                    st.rerun()
                except Exception as e:
                    error_msg = f"Error: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})


# Footer
st.divider()
st.caption("© 2026 Jerry Chan. All rights reserved. Built with OpenAI Codex • Powered by Streamlit • Hosted on Google Cloud.")
