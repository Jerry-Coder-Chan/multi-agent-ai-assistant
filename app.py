import streamlit as st
import os
import sqlite3
import json
import hashlib
import base64
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

def _location_cache_path(location: str) -> str:
    key = hashlib.md5(location.strip().lower().encode()).hexdigest()[:16]
    return os.path.join(bg_cache_dir, f"{key}.jpg")

def _image_to_data_uri(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "jpeg"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"

def _get_cached_background(location: str):
    location = location.strip() or "Singapore"
    cache_path = _location_cache_path(location)
    if not os.path.exists(cache_path):
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
if 'db_initialized' not in st.session_state:
    try:
        event_count = initialize_events_database(db_path)
        st.session_state.db_initialized = True
        st.session_state.db_event_count = event_count
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

# Sidebar configuration
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
    ollama_model = env_ollama_model or "llama3.2"

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
    
    # Settings
    st.subheader("Settings")
    warm_ollama = False
    enable_critic = st.checkbox(
        "Enable Critic LLM",
        value=True,
        help="Cross-check response quality with a secondary model; auto-skips on quota/errors."
    )
    llm_provider = st.selectbox("LLM Provider", ["OpenAI", "Ollama", "Qwen"], index=0)
    if llm_provider == "OpenAI":
        llm_model = st.selectbox("LLM Model", ["gpt-5-mini", "gpt-5", "gpt-5.4"], index=0)
        if not dashscope_api_key:
            dashscope_api_key = st.text_input(
                "Qwen API Key (Optional, Critic)",
                type="password",
                key="dashscope_key",
                help="Used only as cross-LLM critic when primary provider is OpenAI."
            )
    else:
        if llm_provider == "Ollama":
            if env_ollama_base_url:
                st.success("✅ OLLAMA_BASE_URL loaded (you can override below)")
            ollama_base_url = st.text_input(
                "Ollama Base URL",
                value=env_ollama_base_url or ollama_base_url or "http://localhost:11434",
                help="For local Ollama, use http://localhost:11434"
            )
            ollama_model = st.text_input(
                "Ollama Model",
                value=ollama_model or "llama3.2",
                help="Example: llama3.2"
            )
            warm_ollama = st.checkbox(
                "Warm up Ollama on init",
                value=True,
                help="Sends a short prompt during initialization to reduce cold-start latency"
            )
            if st.button("Test Ollama connection"):
                try:
                    resp = requests.get(f"{ollama_base_url.rstrip('/')}/api/tags", timeout=5)
                    resp.raise_for_status()
                    st.success("✅ Ollama reachable")
                except Exception as e:
                    st.error(f"❌ Ollama test failed: {e}")
            llm_model = ollama_model
        else:
            if env_dashscope_key:
                dashscope_api_key = env_dashscope_key
                st.success("✅ DASHSCOPE_API_KEY loaded")
            else:
                dashscope_api_key = st.text_input("Qwen API Key", type="password", key="dashscope_key")
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
    max_history = st.number_input("Conversation History", min_value=5, max_value=50, value=20, step=1)

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
                    
                    # Use the db_path we already defined
                    pdf_path = os.path.join(data_dir, "Singapore_2026_Major_Events.pdf")
                    
                    event_agent = EventAgent(db_path)
                    provider_key = (
                        "ollama" if llm_provider == "Ollama"
                        else "qwen" if llm_provider == "Qwen"
                        else "openai"
                    )
                    if provider_key == "ollama" and warm_ollama:
                        try:
                            warm_client = LLMClient(
                                provider=provider_key,
                                openai_api_key=openai_api_key,
                                ollama_base_url=ollama_base_url,
                                qwen_api_key=dashscope_api_key,
                                qwen_base_url=dashscope_base_url,
                            )
                            _ = warm_client.chat(
                                messages=[{"role": "user", "content": "hi"}],
                                model=llm_model,
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
                    rag_agent = RAGAgent(
                        openai_api_key,
                        pdf_path,
                        llm_model,
                        llm_provider=provider_key,
                        ollama_base_url=ollama_base_url,
                        qwen_api_key=dashscope_api_key,
                        qwen_base_url=dashscope_base_url,
                    )
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
                    st.error(f"Initialization failed: {str(e)}")

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
            <div class="landing-title">Meet Amanda - your Multi-Agent AI Assistant</div>
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
            if status in {"applied", "kept"}:
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
        st.markdown(text)
    # Display chat messages
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            # Display Intent Badge if present
            if "intent" in message:
                label = _format_multi_intent(message["intent"], message.get("critic"))
                st.markdown(f'<div class="intent-badge">🔍 {label}</div>', unsafe_allow_html=True)
            if message.get("security_badge"):
                st.markdown(
                    '<div style="display:inline-block;background:#c62828;color:white;'
                    'padding:0.15rem 0.4rem;border-radius:0.3rem;font-size:0.75rem;'
                    'font-weight:bold;margin-bottom:0.4rem;">AIRS BLOCKED</div>',
                    unsafe_allow_html=True
                )
            _render_response(message["content"])
    
    # Chat input
    if prompt := st.chat_input(
        f"I am Amanda, your intelligent event and activity companion - ask me anyting to plan, search, recommend, or create fun activities in {landing_location}."
    ):
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
                except Exception as e:
                    error_msg = f"Error: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})


# Footer
st.divider()
st.caption("© 2026 Jerry Chan. All rights reserved. Built with OpenAI Codex • Powered by Streamlit • Hosted on Google Cloud.")
