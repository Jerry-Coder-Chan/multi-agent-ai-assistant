"""
ControllerAgent - Main orchestrator that routes queries to appropriate agents
Enhanced with Palo Alto Networks Prisma AIRS Runtime Security
"""
import re
import openai
from datetime import datetime, timezone, timedelta
from typing import Dict, Union, Optional
from agents.security_agent import SecurityAgent, AIRSResponse

class ControllerAgent:
    """Main orchestrator that routes queries to appropriate agents with security monitoring."""

    def __init__(
        self,
        chat_agent,
        weather_agent,
        event_agent,
        recommendation_agent,
        rag_agent,
        image_agent,
        openai_api_key: str,
        security_agent: Optional[SecurityAgent] = None
    ):
        self.chat_agent = chat_agent
        self.weather_agent = weather_agent
        self.event_agent = event_agent
        self.recommendation_agent = recommendation_agent
        self.rag_agent = rag_agent
        self.image_agent = image_agent
        self.llm = openai.OpenAI(api_key=openai_api_key)
        
        # Security integration
        self.security_agent = security_agent
        self.security_enabled = security_agent is not None and security_agent.enabled
        
        if self.security_enabled:
            print("[SECURITY] AIRS Runtime Security ENABLED")
        else:
            print("[SECURITY] Running without security monitoring")

    def handle_query(self, user_query: str, user_id: str = "anonymous") -> Dict[str, str]:
        """
        Main entry point - routes query to appropriate agent with security scanning.
        
        Args:
            user_query: User's input query
            user_id: User identifier for security logging
            
        Returns:
            Dictionary with 'response' and 'intent' keys
        """
        print(f"\n{'='*60}")
        print(f"User Query: {user_query}")
        print(f"{'='*60}")

        # ========================================================================
        # SECURITY STEP 1: Scan incoming prompt for threats
        # ========================================================================
        if self.security_enabled:
            prompt_scan = self.security_agent.scan_interaction(
                prompt=user_query,
                response=None,  # Only scanning prompt at this stage
                ai_model="gpt-4",
                app_user=user_id,
                agent_name="controller_input"
            )
            
            # Block if threat detected and blocking is enabled
            if prompt_scan.threat_detected and self.security_agent.block_on_threat:
                print(f"[SECURITY] ⚠️ THREAT BLOCKED: {prompt_scan.threat_type}")
                safe_response = self.security_agent.get_safe_response(prompt_scan.threat_type)
                return {
                    "response": safe_response,
                    "intent": "SECURITY_BLOCKED",
                    "security_status": "blocked",
                    "threat_type": prompt_scan.threat_type
                }
            
            # Log threat but continue processing
            if prompt_scan.threat_detected:
                print(f"[SECURITY] ⚠️ Threat logged: {prompt_scan.threat_type} (not blocking)")

        # Continue with normal processing
        location, date = self.chat_agent.extract_entities(user_query)
        intent = self._classify_intent(user_query, date)

        print(f"[CONTROLLER] Intent: {intent}")
        print(f"[CONTROLLER] Location: {location}")
        print(f"[CONTROLLER] Date: {date}")
        print(f"{'-'*60}")

        try:
            # Route to appropriate handler
            if intent == "IMAGE_GENERATION":
                response = self._handle_image_generation(user_query, user_id)
            elif intent == "RAG_QUERY":
                response = self._handle_rag_query(user_query, user_id)
            elif intent == "EVENT_QUERY_DB":
                response = self._handle_event_query(date, user_query, location, user_id)
            elif intent == "RECOMMENDATION":
                response = self._handle_recommendation(location, date, user_id)
            elif intent == "WEATHER_QUERY":
                response = self._handle_weather_query(location, date, user_id)
            elif intent == "TIME_QUERY":
                response = self._handle_time_query(user_query, user_id)
            else:
                response = self._handle_unknown(user_query, routed_via_llm=True)

            # ====================================================================
            # SECURITY STEP 2: Scan response before returning to user
            # ====================================================================
            if self.security_enabled:
                response_scan = self.security_agent.scan_interaction(
                    prompt=user_query,
                    response=response,
                    ai_model="gpt-4",
                    app_user=user_id,
                    agent_name=f"controller_{intent.lower()}"
                )
                
                # Block response if threat detected
                if response_scan.threat_detected and self.security_agent.block_on_threat:
                    print(f"[SECURITY] ⚠️ RESPONSE BLOCKED: {response_scan.threat_type}")
                    response = self.security_agent.get_safe_response(response_scan.threat_type)
                    response += "\n\n_Note: The original response was filtered for security reasons._"
                    intent = "SECURITY_FILTERED"

            self.chat_agent.add_to_history(user_query, response)
            
            # Return response with security metadata
            result = {
                "response": response,
                "intent": intent
            }
            
            # Add security info if available
            if self.security_enabled:
                result["security_scanned"] = True
                result["scan_time_ms"] = (
                    (prompt_scan.scan_time_ms or 0) + 
                    (response_scan.scan_time_ms if 'response_scan' in locals() and response_scan.scan_time_ms else 0)
                )
                result["security"] = {
                    "prompt": {
                        "threat_detected": prompt_scan.threat_detected,
                        "threat_type": prompt_scan.threat_type,
                        "risk_score": prompt_scan.risk_score,
                        "action_taken": prompt_scan.action_taken,
                        "details": prompt_scan.details,
                    },
                    "response": {
                        "threat_detected": response_scan.threat_detected if 'response_scan' in locals() else False,
                        "threat_type": response_scan.threat_type if 'response_scan' in locals() else None,
                        "risk_score": response_scan.risk_score if 'response_scan' in locals() else None,
                        "action_taken": response_scan.action_taken if 'response_scan' in locals() else None,
                        "details": response_scan.details if 'response_scan' in locals() else None,
                    },
                }
            
            return result

        except Exception as e:
            error_msg = f"Error processing request: {str(e)}"
            print(f"[ERROR] {error_msg}")
            return {
                "response": error_msg,
                "intent": "ERROR"
            }

    def _classify_intent(self, query: str, extracted_date: str) -> str:
        """Classify user intent using LLM."""
        prompt = f"""Classify this query into ONE category:

    Query: "{query}"
    Date: "{extracted_date}"

    Categories:
    - EVENT_QUERY_DB: List/filter events, ask price/capacity ("show events", "how much")
    - RECOMMENDATION: Ask for suggestions ("what should I do", "recommend")
    - TIME_QUERY: Ask current time/date ("what time", "what date", "what day")
    - WEATHER_QUERY: Ask weather ("weather", "temperature")
    - IMAGE_GENERATION: Generate image ("generate image", "create picture")
    - RAG_QUERY: Future events 2026+, history ("2026 concerts", "F1 history")
    - UNKNOWN: None of above

    Rules (first match wins):
    1. IF "generate" or "create image" → IMAGE_GENERATION
    2. IF "what time" or "what date" or "what day" or "when is" → TIME_QUERY
    3. IF "weather" or "temperature" → WEATHER_QUERY
    4. IF price/cost/capacity keywords → EVENT_QUERY_DB
    5. IF "history" or "2026+" → RAG_QUERY
    6. IF "recommend" or "suggest" → RECOMMENDATION
    7. IF "show" or "list" → EVENT_QUERY_DB

    Category (one word):"""

        try:
            response = self.llm.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Classify intent. Reply with ONE word only."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=20,
                temperature=0.0
            )

            intent = response.choices[0].message.content.strip().upper()
            valid_intents = ["RECOMMENDATION", "EVENT_QUERY_DB", "RAG_QUERY",
                            "IMAGE_GENERATION", "WEATHER_QUERY", "TIME_QUERY", "UNKNOWN"]

            for valid_intent in valid_intents:
                if valid_intent in intent:
                    return valid_intent

            return "UNKNOWN"

        except Exception as e:
            print(f"[ERROR] Intent classification failed: {e}")
            return "UNKNOWN"

    def _handle_recommendation(self, location: str, date: str, user_id: str = "anonymous") -> str:
        """Handle recommendation requests."""
        print(f"[RECOMMENDATION] Generating for {location} on {date}")

        try:
            print(f"  → Fetching weather...")
            weather_data = self.weather_agent.get_weather(location, date)
            cond = weather_data.get('condition', 'Unknown')
            temp = weather_data.get('temperature_c', 'N/A')
            print(f"  ✓ Weather: {cond}, {temp}°C")

            print(f"  → Querying events...")
            events = self.event_agent.get_events(date)
            print(f"  ✓ Found {len(events)} events")

            if not events:
                return f"No events in database for {date}. Try asking about 2026 events!"

            print(f"  → Generating recommendations...")
            recommendations = self.recommendation_agent.generate_recommendation(weather_data, events)
            print(f"  ✓ Done")

            return recommendations
        except Exception as e:
            return f"Error: {str(e)}"

    def _handle_event_query(self, date: str, query: str, location: str, user_id: str = "anonymous") -> str:
        """Handle direct database queries with natural language response."""
        print(f"[EVENT QUERY] Querying for {date}")

        try:
            # Simple keyword filters for the DB query
            filters = {}
            if 'indoor' in query.lower():
                filters['indoor'] = True
            elif 'outdoor' in query.lower():
                filters['indoor'] = False
            
            events = self.event_agent.get_events(date, **filters)
            print(f"  ✓ Found {len(events)} events")

            if not events:
                return f"I couldn't find any events scheduled for {date}."

            # Create context for LLM
            event_list_str = "\n".join([ 
                f"- {e['name']} ({e['type']}): Located at {e['location']}. Price: ${e['price']}. Capacity: {e['capacity']}. Indoor: {e['indoor']}."
                for e in events
            ])

            prompt = f"""
            You are a helpful event assistant. Answer the user's question based ONLY on the following event information.
            
            User Question: "{query}"
            
            Available Events for {date}:
            {event_list_str}
            
            Instructions:
            1. If the user asks for a list, format it as a bulleted list. Use bold for event names (e.g., **Event Name** - Details).
            2. If the user asks specific questions (e.g., "how much for 2 people", "is there anything cheap"), calculate the answer or filter based on the data provided.
            3. Do not make up information not present in the event list.
            4. Be concise but engaging.
            """

            response = self.llm.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            
            return response.choices[0].message.content

        except Exception as e:
            return f"Error processing event query: {str(e)}"

    def _handle_rag_query(self, query: str, user_id: str = "anonymous") -> str:
        """Handle RAG-based queries."""
        print(f"[RAG QUERY] Searching knowledge base...")

        try:
            answer = self.rag_agent.query(query)
            print(f"  ✓ Answer retrieved")

            if "2026" in query:
                answer += "\n\n💡 _For current events, ask for recommendations!_"

            # If RAG couldn't answer, fall back to friendly LLM response
            if self._is_rag_no_answer(answer):
                return self._handle_unknown(query, routed_via_llm=True)

            return answer
        except Exception as e:
            return self._handle_unknown(query, routed_via_llm=True)

    def _is_rag_no_answer(self, answer: str) -> bool:
        """Heuristic to detect when RAG has no useful answer."""
        if not answer:
            return True
        lowered = answer.lower()
        signals = [
            "documents provided do not contain",
            "i don't know",
            "i do not know",
            "not contain information",
            "cannot find",
            "no information",
        ]
        return any(s in lowered for s in signals)

    def _handle_image_generation(self, query: str, user_id: str = "anonymous") -> str:
        """Handle image generation with extra security scanning."""
        print(f"[IMAGE] Generating...")

        prompt = re.sub(
            r'(generate|create|make|draw)\s+(an?\s+)?(image|picture|photo)\s+(of\s+)?',
            '', query, flags=re.IGNORECASE
        ).strip()

        if len(prompt) < 3:
            return "Please provide a description for the image."

        # Extra security check for image generation (high-risk operation)
        if self.security_enabled:
            image_prompt_scan = self.security_agent.scan_interaction(
                prompt=f"Image generation request: {prompt}",
                response=None,
                ai_model="dall-e-3",
                app_user=user_id,
                agent_name="image_agent"
            )
            
            if image_prompt_scan.threat_detected:
                print(f"[SECURITY] ⚠️ Image generation blocked: {image_prompt_scan.threat_type}")
                return self.security_agent.get_safe_response(image_prompt_scan.threat_type)

        try:
            image_url = self.image_agent.generate_image(prompt)
            return f"Here is your image based on '{prompt}':\n\n![Generated Image]({image_url})\n\n[Open Image in Browser]({image_url})"
        except Exception as e:
            return f"Error: {str(e)}"

    def _handle_weather_query(self, location: str, date: str, user_id: str = "anonymous") -> str:
        """Handle weather queries."""
        print(f"[WEATHER QUERY] Fetching weather for {location} on {date}")

        try:
            weather_data = self.weather_agent.get_weather(location, date)
            
            if "error" in weather_data:
                 return f"Could not fetch weather: {weather_data['error']}"

            # Format comprehensive weather response
            response = f"The weather in {location} on {date} is: {weather_data.get('condition', 'Unknown')} "
            response += f"with a temperature of {weather_data.get('temperature_c', 'N/A')}°C. "
            response += f"The humidity is {weather_data.get('humidity', 'N/A')}% and wind speed is {weather_data.get('wind_speed_kph', 'N/A')} km/h."

            # Add helpful weather insights
            rain_chance = weather_data.get('rain_chance', 0)
            uv_index = weather_data.get('uv_index', 0)
            temp = weather_data.get('temperature_c', 0)
            
            if rain_chance > 60:
                response += f"\n\n⚠️ High chance of rain ({rain_chance}%). Consider indoor activities!"
            elif uv_index >= 8:
                response += f"\n\n☀️ High UV index ({uv_index}). Remember sunscreen!"
            elif temp > 32:
                response += "\n\n🌡️ High temperature. Stay hydrated!"

            return response
        except Exception as e:
            return f"Error fetching weather for {location}: {str(e)}"

    def _handle_time_query(self, query: str, user_id: str = "anonymous") -> str:
        """Handle time and date queries with human-readable responses, including timezone support."""
        print(f"[TIME QUERY] Getting current time/date")
        
        from zoneinfo import ZoneInfo
        
        # City to timezone mapping
        timezone_map = {
            'london': 'Europe/London',
            'new york': 'America/New_York',
            'tokyo': 'Asia/Tokyo',
            'singapore': 'Asia/Singapore',
            'paris': 'Europe/Paris',
            'sydney': 'Australia/Sydney',
            'dubai': 'Asia/Dubai',
            'hong kong': 'Asia/Hong_Kong',
            'los angeles': 'America/Los_Angeles',
            'chicago': 'America/Chicago',
            'toronto': 'America/Toronto',
            'mumbai': 'Asia/Kolkata',
            'beijing': 'Asia/Shanghai',
            'berlin': 'Europe/Berlin',
            'moscow': 'Europe/Moscow',
        }
        
        query_lower = query.lower()
        
        # Check if a specific location/timezone is mentioned
        target_tz = None
        location_name = None
        for city, tz in timezone_map.items():
            if city in query_lower:
                target_tz = tz
                location_name = city.title()
                break
        
        # Get the appropriate time
        if target_tz:
            now = datetime.now(ZoneInfo(target_tz))
            location_str = f" in {location_name}"
        else:
            now = datetime.now()
            location_str = " (local time)"
        
        tomorrow = now + timedelta(days=1)
        yesterday = now - timedelta(days=1)
        
        # Check if asking specifically about tomorrow
        if "tomorrow" in query_lower:
            response = f"**Tomorrow's Date{location_str}:**\n\n"
            response += f"📅 {tomorrow.strftime('%A, %B %d, %Y')}\n"
            response += f"🌍 Day of Week: {tomorrow.strftime('%A')}\n"
            if target_tz:
                response += f"🕐 Timezone: {target_tz}\n"
            return response
        
        # Check if asking specifically about yesterday
        elif "yesterday" in query_lower:
            response = f"**Yesterday's Date{location_str}:**\n\n"
            response += f"📅 {yesterday.strftime('%A, %B %d, %Y')}\n"
            response += f"🌍 Day of Week: {yesterday.strftime('%A')}\n"
            if target_tz:
                response += f"🕐 Timezone: {target_tz}\n"
            return response
        
        # Check if asking only about time
        elif "time" in query_lower and "date" not in query_lower:
            response = f"**Current Time{location_str}:**\n\n"
            response += f"🕐 {now.strftime('%I:%M:%S %p')}\n"
            response += f"🕐 24-hour format: {now.strftime('%H:%M:%S')}\n"
            if target_tz:
                response += f"🌍 Timezone: {target_tz}\n"
            return response
        
        # Check if asking only about date/day
        elif any(word in query_lower for word in ["date", "day", "today"]) and "time" not in query_lower:
            response = f"**Today's Date{location_str}:**\n\n"
            response += f"📅 {now.strftime('%A, %B %d, %Y')}\n"
            response += f"🌍 Day of Week: {now.strftime('%A')}\n"
            if target_tz:
                response += f"🕐 Timezone: {target_tz}\n"
            return response
        
        # Default: show both date and time
        else:
            response = f"**Current Date & Time{location_str}:**\n\n"
            response += f"📅 **Date:** {now.strftime('%A, %B %d, %Y')}\n"
            response += f"🕐 **Time:** {now.strftime('%I:%M:%S %p')} ({now.strftime('%H:%M:%S')} 24-hour)\n"
            response += f"🌍 **Day of Week:** {now.strftime('%A')}\n"
            if target_tz:
                response += f"🕐 **Timezone:** {target_tz}\n"
            response += f"\n**Tomorrow will be:**\n"
            response += f"📅 {tomorrow.strftime('%A, %B %d, %Y')}\n"
            return response

    def _handle_unknown(self, query: str, routed_via_llm: bool = False) -> str:
        """Handle unknown intents with a friendly response and guidance."""
        reminder = (
            "I’m focused on a few specific services right now. Try one of these:\n"
            "🎯 Recommendations → \"What should I do today?\"\n"
            "📋 Events → \"Show me events today\"\n"
            "📚 Future info → \"What concerts in 2026?\"\n"
            "🎨 Images → \"Generate an image of...\"\n"
            "☁️ Weather → \"What's the weather?\"\n"
            "⏰ Time → \"What time is it?\""
        )

        # Guardrail for time-sensitive/news/sports questions
        if self._looks_time_sensitive(query):
            notice = (
                "I don’t have reliable access to live sports/news results in this demo. "
                "I can still share general info if you rephrase, or you can ask about the "
                "features below."
            )
            return f"{notice}\n\n{reminder}"

        try:
            response = self.llm.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a friendly assistant for a multi-agent demo app. "
                            "Answer the user briefly and politely in 1-2 sentences. "
                            "Do not claim capabilities outside the listed services."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                max_tokens=80,
                temperature=0.4,
            )
            reply = response.choices[0].message.content.strip()
            if routed_via_llm:
                routed_note = "Note: I couldn’t answer from the system’s data, so I routed this to the LLM."
                return f"{reply}\n\n{routed_note}\n\n{reminder}"
            return f"{reply}\n\n{reminder}"
        except Exception:
            return reminder

    def _looks_time_sensitive(self, query: str) -> bool:
        """Detect likely time-sensitive queries (news/sports/results)."""
        lowered = query.lower()
        signals = [
            "last week",
            "today",
            "yesterday",
            "this week",
            "recent",
            "latest",
            "who won",
            "results",
            "score",
            "champion",
            "final",
        ]
        topics = ["news", "sports", "tournament", "open", "league", "cup"]
        return any(s in lowered for s in signals) and any(t in lowered for t in topics)
    
    def get_security_stats(self) -> Dict:
        """Get security statistics if security agent is enabled"""
        if self.security_enabled:
            return self.security_agent.get_statistics()
        return {"enabled": False, "message": "Security monitoring not enabled"}
