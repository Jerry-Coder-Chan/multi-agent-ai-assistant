
import re
from datetime import timezone, datetime, timedelta # Added datetime and timedelta

class ChatAgent:
    """Manages conversational context and memory."""

    def __init__(self, max_history: int = 20):
        self.conversation_history = []
        self.max_history = max_history
        self.last_active_date = None
        self.last_active_location = "Singapore"

    def extract_entities(self, query: str):
        """Extract location and date from query."""
        # Extract location
        location_match = re.search(
            r'(?:in|at|for|near|of)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)',
            query
        )
        location = location_match.group(1) if location_match else self.last_active_location

        if location_match:
            self.last_active_location = location

        # Extract date
        sgt_tz = timezone(timedelta(hours=8))
        today = datetime.now(sgt_tz)
        date = None

        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', query)
        if date_match:
            date = date_match.group(1)
        elif re.search(r'\btoday\b', query, re.IGNORECASE):
            date = today.strftime("%Y-%m-%d")
        elif re.search(r'\btomorrow\b', query, re.IGNORECASE):
            date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        elif re.search(r'\btonight\b', query, re.IGNORECASE):
            date = today.strftime("%Y-%m-%d")

        if date:
            self.last_active_date = date
        elif self.last_active_date:
            date = self.last_active_date
        else:
            date = today.strftime("%Y-%m-%d")
            self.last_active_date = date

        return location, date

    def add_to_history(self, query: str, response: str):
        """Add exchange to conversation history."""
        self.conversation_history.append({
            'query': query,
            'response': response,
            'timestamp': datetime.now().isoformat()
        })

        if len(self.conversation_history) > self.max_history:
            self.conversation_history.pop(0)

    def get_conversation_history(self):
        """Return conversation history."""
        return self.conversation_history

    def clear_history(self):
        """Clear conversation history and context."""
        self.conversation_history = []
        self.last_active_date = None
        self.last_active_location = "Singapore"
        print("Conversation history cleared.")

    def get_context_summary(self):
        """Get summary of current context."""
        return {
            'last_active_date': self.last_active_date,
            'last_active_location': self.last_active_location,
            'conversation_count': len(self.conversation_history)
        }
