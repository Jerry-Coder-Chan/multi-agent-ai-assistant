import streamlit as st
import os
import sqlite3
from datetime import datetime, timezone, timedelta
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
    
    # Get today's date and tomorrow for realistic testing
    today = datetime.now()
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
    
    # API Keys
    st.subheader("API Keys")
    
    # Try to load keys from environment variables
    env_openai_key = os.environ.get('OPENAI_API_KEY')
    env_weather_key = os.environ.get('WEATHER_API_KEY')
    env_airs_key = os.environ.get('AIRS_API_KEY')
    
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
    
    # Settings
    st.subheader("Settings")
    llm_model = st.selectbox("LLM Model", ["gpt-4", "gpt-3.5-turbo"], index=0)
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
    if st.button("🚀 Initialize Assistant", type="primary"):
        if not openai_api_key or not weather_api_key:
            st.error("Please provide both API keys!")
        else:
            with st.spinner("Initializing agents..."):
                try:
                    # Initialize all agents
                    chat_agent = ChatAgent(max_history=max_history)
                    weather_agent = WeatherAgent(weather_api_key)
                    
                    # Use the db_path we already defined
                    pdf_path = os.path.join(data_dir, "Singapore_2026_Major_Events.pdf")
                    
                    event_agent = EventAgent(db_path)
                    recommendation_agent = RecommendationAgent(openai_api_key)
                    rag_agent = RAGAgent(openai_api_key, pdf_path, llm_model)
                    image_agent = ImageAgent(openai_api_key)
                    
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
                        security_agent=security_agent
                    )
                    
                    st.session_state.initialized = True
                    st.success("✅ Assistant initialized successfully!")
                except Exception as e:
                    st.error(f"Initialization failed: {str(e)}")
    
    # Clear conversation
    if st.button("🗑️ Clear Conversation"):
        st.session_state.messages = []
        if st.session_state.controller:
            st.session_state.controller.chat_agent.clear_history()
        st.rerun()
    
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

# Main chat interface
st.title("🤖 Multi-Agent AI Assistant")
st.caption("Your intelligent event and activity companion")
app_version = os.environ.get("APP_VERSION", "dev")
st.caption(f"Version: {app_version}")

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
    st.info("👈 Please configure API keys and initialize the assistant in the sidebar to begin.")
    
    # Example queries
    st.subheader("💡 Example Queries")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        **Event Queries:**
        - What events are available today?
        - Show me free events tomorrow
        - How much does the historical tour cost?
        
        **Weather & Recommendations:**
        - What's the weather tomorrow?
        - What should I do this weekend?
        - Recommend indoor activities
        """)
    
    with col2:
        st.markdown("""
        **Future Events (2026):**
        - What concerts are in 2026?
        - Tell me about F1 Singapore 2026
        - Any sports events next year?
        
        **Image Generation:**
        - Generate an image of Marina Bay at sunset
        - Create a futuristic cityscape
        """)
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

    def _format_multi_intent(intent: str) -> str:
        if not intent.startswith("MULTI:"):
            return intent_labels.get(intent, intent)
        parts = intent.replace("MULTI:", "").split("+")
        labels = [intent_labels.get(p, p) for p in parts]
        if len(labels) == 1:
            return labels[0]
        if len(labels) == 2:
            return f"Multiple Agents: {labels[0]} and {labels[1]}"
        return f"Multiple Agents: {', '.join(labels[:-1])}, and {labels[-1]}"

    def _render_response(text: str):
        st.markdown(f'<div class="assistant-text">{text}</div>', unsafe_allow_html=True)
    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            # Display Intent Badge if present
            if "intent" in message:
                label = _format_multi_intent(message["intent"])
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
    if prompt := st.chat_input("Ask me anything..."):
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
                            st.session_state.security_events.append({
                                "kind": event_kind,
                                "threat_type": threat_type,
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
                    label = _format_multi_intent(intent)
                    st.markdown(f'<div class="intent-badge">🔍 {label}</div>', unsafe_allow_html=True)
                    if security_badge:
                        st.markdown(
                            '<div style="display:inline-block;background:#c62828;color:white;'
                            'padding:0.15rem 0.4rem;border-radius:0.3rem;font-size:0.75rem;'
                            'font-weight:bold;margin-bottom:0.4rem;">AIRS BLOCKED</div>',
                            unsafe_allow_html=True
                        )
                    _render_response(response)
                    
                    # Add assistant message with intent
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": response,
                        "intent": intent,
                        "security_badge": security_badge
                    })
                except Exception as e:
                    error_msg = f"Error: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})

# Footer
st.divider()
st.caption("Built with Streamlit • Multi-Agent AI System • Created by Jerry Chan")
