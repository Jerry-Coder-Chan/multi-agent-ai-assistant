"""
ControllerAgent - Main orchestrator that routes queries to appropriate agents
Enhanced with Palo Alto Networks Prisma AIRS Runtime Security
"""
import json
import re
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Union, Optional, List
from zoneinfo import ZoneInfo
from agents.security_agent import SecurityAgent, AIRSResponse
from agents.llm_client import LLMClient
from agents.critic_agent import CriticAgent

class ControllerAgent:
    """Main orchestrator that routes queries to appropriate agents with security monitoring."""
    TOURISM_PERSONA = (
        "You are Amanda, a professional tourism advisor and customer service assistant "
        "for travelers. Be warm, courteous, practical, and concise. Use welcoming, "
        "service-oriented language, and prioritize clarity and actionable guidance."
    )
    DEFAULT_STYLE_MEMORY = (
        "Style memory: Use a less formal conversational tone. "
        "Use light emojis where appropriate (avoid overuse)."
    )

    def __init__(
        self,
        chat_agent,
        weather_agent,
        event_agent,
        recommendation_agent,
        rag_agent,
        image_agent,
        openai_api_key: str,
        llm_provider: str = "openai",
        llm_model: str = "gpt-5-mini",
        ollama_base_url: str = "",
        qwen_api_key: str = "",
        qwen_base_url: str = "",
        security_agent: Optional[SecurityAgent] = None,
        search_agent=None,
        critic_agent: Optional[CriticAgent] = None,
    ):
        self.chat_agent = chat_agent
        self.weather_agent = weather_agent
        self.event_agent = event_agent
        self.recommendation_agent = recommendation_agent
        self.rag_agent = rag_agent
        self.image_agent = image_agent
        self.llm = LLMClient(
            provider=llm_provider,
            openai_api_key=openai_api_key,
            ollama_base_url=ollama_base_url,
            qwen_api_key=qwen_api_key,
            qwen_base_url=qwen_base_url,
        )
        self.llm_model = llm_model
        self.search_agent = search_agent
        self.critic_agent = critic_agent
        self.last_non_unknown_intents = []
        self.last_event_results = []
        self.last_event_date = None
        # Default time zone for time queries
        self.last_time_tz = "Asia/Singapore"
        self.last_time_location_name = "Singapore"
        self.pending_cost_clarification_query = ""
        
        # Security integration
        self.security_agent = security_agent
        self.security_enabled = security_agent is not None and security_agent.enabled
        
        if self.security_enabled:
            print("[SECURITY] AIRS Runtime Security ENABLED")
        else:
            print("[SECURITY] Running without security monitoring")

    def _get_style_memory_prompt(self) -> str:
        """Get style guidance from chat memory, with a safe default."""
        getter = getattr(self.chat_agent, "get_style_prompt", None)
        if callable(getter):
            style = getter()
            if isinstance(style, str) and style.strip():
                return style.strip()
        return self.DEFAULT_STYLE_MEMORY

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

        # If the previous turn asked for attendee clarification, merge short numeric follow-ups
        # back into the original cost query so context is preserved.
        if (
            self.pending_cost_clarification_query
            and self._is_attendee_only_followup(user_query)
        ):
            user_query = f"{self.pending_cost_clarification_query}. Also: {user_query}"
            self.pending_cost_clarification_query = ""

        # ========================================================================
        # SECURITY STEP 1: Scan incoming prompt for threats
        # ========================================================================
        if self.security_enabled:
            prompt_scan = self.security_agent.scan_interaction(
                prompt=user_query,
                response=None,  # Only scanning prompt at this stage
                ai_model=self.llm_model,
                app_user=user_id,
                agent_name="controller_input"
            )
            
            # Block if threat detected and blocking is enabled
            should_block = False
            if prompt_scan.threat_detected:
                should_block = True
            # Also block if attack mapping indicates a prompt-attack technique
            if not should_block and getattr(prompt_scan, "attack_mapping", None):
                should_block = True

            if should_block and self.security_agent.block_on_threat:
                print(f"[SECURITY] ⚠️ THREAT BLOCKED: {prompt_scan.threat_type}")
                safe_response = self.security_agent.get_safe_response(
                    prompt_scan.threat_type,
                    attack_mapping=getattr(prompt_scan, "attack_mapping", None)
                )
                safe_response += (
                    "\n\nI’m focused on a few specific services right now. Try one of these:\n"
                    "🎯 Recommendations → \"What should I do today?\"\n"
                    "📋 Events → \"Show me events today\"\n"
                    "📚 Future info → \"What concerts in 2026?\"\n"
                    "🎨 Images → \"Generate an image of...\"\n"
                    "☁️ Weather → \"How's the weather?\"\n"
                    "⏰ Time → \"What time is it?\""
                )
                return {
                    "response": safe_response,
                    "intent": "SECURITY_BLOCKED",
                    "security_status": "blocked",
                    "threat_type": prompt_scan.threat_type,
                    "security_scanned": True,
                    "scan_time_ms": (prompt_scan.scan_time_ms or 0),
                    "security": {
                        "prompt": {
                            "threat_detected": prompt_scan.threat_detected,
                            "threat_type": prompt_scan.threat_type,
                            "risk_score": prompt_scan.risk_score,
                            "action_taken": prompt_scan.action_taken,
                            "details": prompt_scan.details,
                            "attack_mapping": getattr(prompt_scan, "attack_mapping", None),
                        },
                        "response": {
                            "threat_detected": False,
                            "threat_type": None,
                            "risk_score": None,
                            "action_taken": None,
                            "details": None,
                        },
                    },
                    "airs_request_payload": getattr(self.security_agent, "last_request_payload", None),
                }
            
            # Log threat but continue processing
            if prompt_scan.threat_detected:
                print(f"[SECURITY] ⚠️ Threat logged: {prompt_scan.threat_type} (not blocking)")

        # Deterministic policy enforcement for sensitive-data exfiltration requests.
        # This complements AIRS classification with hard guarantees for high-impact cases.
        if self._is_sensitive_data_request(user_query):
            print("[POLICY] 🚫 Blocked sensitive-data request")
            policy_response = (
                "I can't provide secrets or credentials (API keys, tokens, passwords, or internal config). "
                "I can help with secure setup steps instead."
            )
            result = {
                "response": policy_response,
                "intent": "POLICY_BLOCKED",
                "security_status": "policy_blocked",
            }
            if self.security_enabled:
                result["security_scanned"] = True
                result["scan_time_ms"] = (prompt_scan.scan_time_ms or 0)
                result["security"] = {
                    "prompt": {
                        "threat_detected": prompt_scan.threat_detected,
                        "threat_type": prompt_scan.threat_type,
                        "risk_score": prompt_scan.risk_score,
                        "action_taken": prompt_scan.action_taken,
                        "details": prompt_scan.details,
                    },
                    "response": {
                        "threat_detected": False,
                        "threat_type": None,
                        "risk_score": None,
                        "action_taken": "POLICY_BLOCKED",
                        "details": {"policy": "sensitive_data_exfiltration"},
                    },
                }
            return result

        # Continue with normal processing
        location, date = self.chat_agent.extract_entities(user_query)
        llm_parsed = self._extract_query_with_llm(user_query, location, date)
        if llm_parsed:
            location = llm_parsed.get("location", location)
            date = llm_parsed.get("date", date)
            intents = llm_parsed.get("intents", [])
            if not intents or intents == ["UNKNOWN"]:
                intents = self._classify_intents(user_query, date)
        else:
            intents = self._classify_intents(user_query, date)
        intents = self._apply_follow_up_intent_override(user_query, intents)
        intents = self._normalize_intents_by_query(user_query, intents)
        intent = intents[0] if intents else "UNKNOWN"
        if intents and not (len(intents) == 1 and intents[0] == "UNKNOWN"):
            self.last_non_unknown_intents = intents.copy()

        print(f"[CONTROLLER] Intent(s): {intents}")
        print(f"[CONTROLLER] Location: {location}")
        print(f"[CONTROLLER] Date: {date}")
        print(f"{'-'*60}")

        try:
            # Route to appropriate handler(s)
            if not intents:
                response = self._handle_unknown(user_query, routed_via_llm=True)
            elif len(intents) == 1:
                response = self._handle_intent(intents[0], user_query, location, date, user_id)
            else:
                # If image generation is mixed with other intents, prioritize image only
                if "IMAGE_GENERATION" in intents and len(intents) > 1:
                    response = self._handle_image_generation(user_query, user_id)
                    response += "\n\n_Note: Image generation was prioritized over other requests._"
                    intents = ["IMAGE_GENERATION"]
                else:
                    parts = []
                    section_titles = {
                        "TIME_QUERY": "Time Query",
                        "WEATHER_QUERY": "Weather Query",
                        "EVENT_QUERY_DB": "Event Query",
                        "RECOMMENDATION": "Recommendation",
                        "RAG_QUERY": "Rag Query",
                        "IMAGE_GENERATION": "Image Generation",
                    }
                    for it in intents:
                        part = self._handle_intent(it, user_query, location, date, user_id)
                        title = section_titles.get(it, it.replace("_", " ").title())
                        parts.append(f"{title}:\n{part}")
                    response = "\n\n".join(parts)

            # ====================================================================
            # CRITIC STEP: Optional cross-LLM review/rewrite before security scan.
            # Fail-open by design on quota/timeouts/errors.
            # ====================================================================
            critic_meta = {"enabled": False, "status": "disabled", "reason": "critic_disabled"}
            response, critic_meta = self._apply_critic_if_enabled(user_query, response, intents)

            # ====================================================================
            # SECURITY STEP 2: Scan response before returning to user
            # ====================================================================
            if self.security_enabled:
                response_scan = self.security_agent.scan_interaction(
                    prompt=user_query,
                    response=response,
                    ai_model=self.llm_model,
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
                    "intent": "MULTI:" + "+".join(intents) if len(intents) > 1 else intent
            }
            result["critic"] = critic_meta
            
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

    def _apply_critic_if_enabled(self, user_query: str, response: str, intents: list):
        """Run optional critic pass; always fail open to original response."""
        active_intents = intents or []
        if "EVENT_QUERY_DB" in active_intents:
            if self.critic_agent and self.critic_agent.is_enabled() and "cost summary" in (response or "").lower():
                check = self.critic_agent.detect_attendee_inconsistency(user_query, response)
                if check.get("status") == "clarification_needed":
                    clarification = check.get("clarification_question") or (
                        "Just to confirm, how many people are attending each activity in total?"
                    )
                    # Preserve original cost query so short follow-up confirmations
                    # can be merged back for deterministic recalculation.
                    self.pending_cost_clarification_query = user_query
                    return clarification, {
                        "enabled": True,
                        "status": "clarification_requested",
                        "reason": "attendee_inconsistency_detected",
                        "provider": getattr(self.critic_agent, "provider", ""),
                        "model": getattr(self.critic_agent, "model", ""),
                    }
                if check.get("status", "").startswith("skipped"):
                    return response, {
                        "enabled": True,
                        "status": check.get("status"),
                        "reason": check.get("reason", ""),
                        "provider": getattr(self.critic_agent, "provider", ""),
                        "model": getattr(self.critic_agent, "model", ""),
                    }
            # Keep SQL response deterministic: do not rewrite wording or numbers.
            return response, {
                "enabled": False,
                "status": "skipped_guardrail",
                "reason": "deterministic_event_query_response",
            }

        # Deterministic/structured outputs should not be flattened by critic rewrites.
        if (
            "TIME_QUERY" in active_intents
            or "RECOMMENDATION" in active_intents
        ):
            return response, {
                "enabled": False,
                "status": "skipped_guardrail",
                "reason": "structured_response_guardrail",
            }

        if not self.critic_agent or not self.critic_agent.is_enabled():
            return response, {"enabled": False, "status": "disabled", "reason": "critic_disabled"}

        try:
            history_getter = getattr(self.chat_agent, "get_conversation_history", None)
            history = history_getter() if callable(history_getter) else []
            review = self.critic_agent.review_response(
                user_query=user_query,
                draft_response=response,
                intents=active_intents,
                recent_history=history or [],
                tourism_persona=self.TOURISM_PERSONA,
                style_memory=self._get_style_memory_prompt(),
            )
            new_response = review.get("response", response) if isinstance(review, dict) else response
            meta = {
                "enabled": True,
                "status": review.get("status", "unknown") if isinstance(review, dict) else "unknown",
                "reason": review.get("reason", "") if isinstance(review, dict) else "",
                "provider": getattr(self.critic_agent, "provider", ""),
                "model": getattr(self.critic_agent, "model", ""),
            }
            return new_response or response, meta
        except Exception as e:
            return response, {"enabled": True, "status": "skipped_error", "reason": str(e)}

    def _is_sensitive_data_request(self, query: str) -> bool:
        """Deterministic guardrail for requests to exfiltrate secrets/credentials."""
        q = (query or "").lower()
        action_terms = [
            "send", "share", "reveal", "show", "leak", "give", "expose", "dump", "print",
            "return", "provide", "display",
        ]
        secret_terms = [
            "api key", "api keys", "secret", "secrets", "token", "tokens", "password",
            "passwords", "credential", "credentials", "private key", "access key",
        ]
        scope_terms = [
            "your", "internal", "system", "stored", "env", "environment", "backend",
            "server", "config", "variables",
        ]
        has_action = any(t in q for t in action_terms)
        has_secret = any(t in q for t in secret_terms)
        has_scope = any(t in q for t in scope_terms)

        # Require both action + secret markers, with optional scope markers for stronger match.
        # Also block direct "send me api keys" style without scope terms.
        if has_action and has_secret:
            return True
        if "api key" in q and ("send me" in q or "give me" in q or "show me" in q):
            return True
        if has_secret and has_scope and ("where" in q or "what is" in q):
            return True
        return False

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
            intent = self.llm.chat(
                messages=[
                    {"role": "system", "content": "Classify intent. Reply with ONE word only."},
                    {"role": "user", "content": prompt},
                ],
                model=self.llm_model,
                max_tokens=20,
                temperature=0.0,
            ).upper()
            valid_intents = ["RECOMMENDATION", "EVENT_QUERY_DB", "RAG_QUERY",
                            "IMAGE_GENERATION", "WEATHER_QUERY", "TIME_QUERY", "UNKNOWN"]

            for valid_intent in valid_intents:
                if valid_intent in intent:
                    return valid_intent

            return "UNKNOWN"

        except Exception as e:
            print(f"[ERROR] Intent classification failed: {e}")
            return "UNKNOWN"

    def _classify_intents(self, query: str, extracted_date: str) -> list:
        """Classify multiple intents using keyword heuristics with LLM fallback."""
        q = query.lower()
        intents = []

        image_request = (
            any(k in q for k in [
                "generate image", "create image", "create picture", "generate picture",
                "image of", "create a photo", "generate a photo", "generate fun images"
            ])
            or re.search(
                r"\b(generate|create|make|draw)\b.{0,80}\b(image|picture|photo|mascot|illustration|artwork)\b",
                q,
            ) is not None
        )

        # Keyword-based detection (allow multiple)
        if image_request:
            intents.append("IMAGE_GENERATION")
        if any(k in q for k in [
            "what time", "what date", "what day", "date is", "time is",
            "current date", "current time", "date and time",
            "tomorrow date", "yesterday date"
        ]):
            intents.append("TIME_QUERY")
        if any(k in q for k in ["weather", "temperature", "forecast", "rain", "humidity", "uv"]):
            intents.append("WEATHER_QUERY")
        if any(k in q for k in ["recommend", "suggest", "what should i do", "ideas", "activities"]):
            intents.append("RECOMMENDATION")
        if any(k in q for k in ["events", "event", "show me", "list events", "how much", "price", "capacity", "tickets"]):
            intents.append("EVENT_QUERY_DB")
        if any(k in q for k in ["history", "2026", "future", "next year"]):
            intents.append("RAG_QUERY")

        # If we found multiple, return in a stable order
        if intents:
            order = ["TIME_QUERY", "WEATHER_QUERY", "EVENT_QUERY_DB", "RECOMMENDATION", "RAG_QUERY", "IMAGE_GENERATION"]
            deduped = []
            for it in order:
                if it in intents and it not in deduped:
                    deduped.append(it)
            return deduped

        # Follow-up shorthand should inherit prior intent(s)
        follow_up_location_only = re.search(
            r'^\s*(?:(?:how|what)\s+about|and)\s+[A-Za-z][A-Za-z\s\-\'\.]*\??\s*$',
            query,
            re.IGNORECASE,
        ) is not None or re.search(
            r'^\s*[A-Za-z][A-Za-z\s\-\'\.]*\s+instead\??\s*$',
            query,
            re.IGNORECASE,
        ) is not None
        if follow_up_location_only and self.last_non_unknown_intents:
            return self.last_non_unknown_intents.copy()

        # Fallback to single-intent LLM classification
        single = self._classify_intent(query, extracted_date)
        return [single] if single else []

    def _normalize_intents_by_query(self, query: str, intents: list) -> list:
        """Post-process intent list to prevent noisy multi-intent routing."""
        if not intents:
            return intents
        q = query.lower()
        has_event = any(k in q for k in ["event", "events", "show me", "list events", "tickets", "capacity", "price", "how much"])
        has_time_phrase = any(k in q for k in ["what time", "what date", "what day", "date and time", "current time", "current date", "time is", "date is"])
        has_recommendation_phrase = any(k in q for k in ["recommend", "suggest", "what should i do", "ideas", "activities"])
        has_cost_phrase = any(
            k in q for k in [
                "how much", "total cost", "cost", "price", "cost in total",
                "in total", "total price"
            ]
        )
        references_previous_plan = any(
            k in q for k in [
                "with my", "with wife", "then", "attend", "go to", "go for",
                "if i want to", "if i go"
            ]
        )
        cost_only_event_query = has_cost_phrase and not has_recommendation_phrase

        # If user is asking about events and did not ask explicit time/date,
        # suppress accidental TIME_QUERY from model extraction.
        if has_event and not has_time_phrase and "TIME_QUERY" in intents:
            intents = [it for it in intents if it != "TIME_QUERY"]
            if not intents:
                intents = ["EVENT_QUERY_DB"]

        # Cost calculations should route to Event Query, including follow-up phrasing.
        if cost_only_event_query and (has_event or references_previous_plan or "EVENT_QUERY_DB" in self.last_non_unknown_intents):
            if "EVENT_QUERY_DB" not in intents:
                intents = ["EVENT_QUERY_DB"] + [it for it in intents if it != "EVENT_QUERY_DB"]
            if "RECOMMENDATION" in intents:
                intents = [it for it in intents if it != "RECOMMENDATION"]

        # Broad year/future queries should use RAG instead of SQL date lookup.
        has_specific_date = re.search(r"\b\d{4}-\d{2}-\d{2}\b", q) is not None
        has_year_ref = re.search(r"\b20\d{2}\b", q) is not None
        has_future_ref = any(k in q for k in ["future", "next year", "this year", "history", "key events", "major events"])
        has_relative_day = any(k in q for k in ["today", "tomorrow", "yesterday", "tonight"])
        if (has_year_ref or has_future_ref) and not has_specific_date and not has_relative_day:
            if "RAG_QUERY" not in intents:
                intents.insert(0, "RAG_QUERY")
            intents = [it for it in intents if it not in {"EVENT_QUERY_DB", "TIME_QUERY", "WEATHER_QUERY"}]

        return intents

    def _apply_follow_up_intent_override(self, query: str, intents: list) -> list:
        """Reuse prior intent(s) for short follow-up prompts like 'how about tomorrow?'."""
        q = query.lower().strip()
        has_explicit_intent_terms = any(
            k in q for k in [
                "weather", "temperature", "forecast", "rain", "humidity", "uv",
                "what time", "what date", "what day", "date and time", "current time", "current date",
                "recommend", "suggest", "what should i do", "ideas", "activities",
                "event", "events", "show me", "list",
                "generate image", "create image", "image of",
            ]
        )
        is_follow_up_short = (
            re.search(r'^\s*(?:(?:how|what)\s+about|and)\s+[A-Za-z][A-Za-z\s\-\'\.]*\??\s*$', query, re.IGNORECASE) is not None
            or re.search(r'^\s*[A-Za-z][A-Za-z\s\-\'\.]*\s+instead\??\s*$', query, re.IGNORECASE) is not None
        )
        if is_follow_up_short and not has_explicit_intent_terms and self.last_non_unknown_intents:
            return self.last_non_unknown_intents.copy()
        return intents

    def _extract_query_with_llm(self, query: str, default_location: str, default_date: str) -> Optional[dict]:
        """Use LLM to extract intents/location/date as strict JSON with validation."""
        valid_intents = {
            "RECOMMENDATION",
            "EVENT_QUERY_DB",
            "RAG_QUERY",
            "IMAGE_GENERATION",
            "WEATHER_QUERY",
            "TIME_QUERY",
            "UNKNOWN",
        }
        schema_hint = (
            '{'
            '"intents":["TIME_QUERY","WEATHER_QUERY"],'
            '"location":"Bangkok",'
            '"date":"2026-03-04"'
            '}'
        )
        prompt = (
            "Extract the user's intents and entities.\n"
            "Return JSON only (no markdown, no prose).\n"
            "Use this schema exactly:\n"
            f"{schema_hint}\n"
            "Rules:\n"
            "- intents: array from [RECOMMENDATION, EVENT_QUERY_DB, RAG_QUERY, IMAGE_GENERATION, WEATHER_QUERY, TIME_QUERY, UNKNOWN]\n"
            "- location: city/country/place string if present; else empty string\n"
            "- date: YYYY-MM-DD only when user gives exact date or relative day (today/tomorrow/yesterday/tonight); otherwise empty string\n"
            "- If query asks both time and weather, return both intents.\n"
            f"Today date is {default_date}.\n"
            f'Query: "{query}"'
        )
        try:
            raw = self.llm.chat(
                messages=[
                    {"role": "system", "content": "You are an information extraction engine. Output valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                model=self.llm_model,
                max_tokens=220,
                temperature=0.0,
            ).strip()
        except Exception as e:
            print(f"[WARN] LLM extraction failed: {e}")
            return None

        data = None
        try:
            data = json.loads(raw)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                try:
                    data = json.loads(match.group(0))
                except Exception:
                    data = None
        if not isinstance(data, dict):
            return None

        parsed_intents = data.get("intents", [])
        if isinstance(parsed_intents, str):
            parsed_intents = [parsed_intents]
        if not isinstance(parsed_intents, list):
            parsed_intents = []

        intents = []
        for it in parsed_intents:
            if not isinstance(it, str):
                continue
            norm = it.strip().upper()
            if norm in valid_intents and norm not in intents:
                intents.append(norm)

        location = data.get("location", "")
        if not isinstance(location, str):
            location = ""
        location = re.sub(r"\s+", " ", location).strip(" ,;:")
        if len(location) < 2:
            location = default_location

        date = data.get("date", "")
        if not isinstance(date, str):
            date = ""
        date = date.strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            date = default_date

        if not intents and location == default_location and date == default_date:
            return None

        order = ["TIME_QUERY", "WEATHER_QUERY", "EVENT_QUERY_DB", "RECOMMENDATION", "RAG_QUERY", "IMAGE_GENERATION", "UNKNOWN"]
        intents = [it for it in order if it in intents]
        return {"intents": intents, "location": location, "date": date}

    def _is_attendee_only_followup(self, query: str) -> bool:
        q = (query or "").strip().lower()
        if not q:
            return False
        # Confirmation-style follow-ups after a clarification prompt:
        # "yes, include cooking class cost too".
        if any(
            phrase in q
            for phrase in [
                "yes",
                "yep",
                "yeah",
                "pls include",
                "please include",
                "include",
                "exclude",
                "including me",
                "excluding me",
            ]
        ):
            # Avoid merging if user is clearly asking a brand-new domain question.
            if any(k in q for k in ["weather", "time", "recommend", "image", "search"]):
                return False
            if len(q.split()) <= 20:
                return True
        # Numeric-only short follow-ups.
        if re.fullmatch(
            r"(?:about\s+)?\d+\s*(?:people|persons|person|pax)?(?:\s*in\s*total|\s*total)?[.?!]?",
            q,
        ):
            return True

        # Clarification phrases that refine attendee counts, e.g.
        # "include me as well. 3 pax in total for tech meetup".
        has_attendee_phrase = any(
            k in q for k in [
                "include me",
                "excluding me",
                "in total",
                "total",
                "pax",
                "people",
                "persons",
                "person",
            ]
        )
        has_number = re.search(r"\b\d+\b", q) is not None
        has_new_primary_question = any(
            k in q for k in ["how much", "cost", "price", "recommend", "weather", "time"]
        )
        return has_attendee_phrase and has_number and not has_new_primary_question

    def _handle_intent(self, intent: str, user_query: str, location: str, date: str, user_id: str) -> str:
        """Dispatch a single intent to its handler."""
        if intent == "IMAGE_GENERATION":
            return self._handle_image_generation(user_query, user_id)
        if intent == "RAG_QUERY":
            return self._handle_rag_query(user_query, user_id)
        if intent == "EVENT_QUERY_DB":
            return self._handle_event_query(date, user_query, location, user_id)
        if intent == "RECOMMENDATION":
            return self._handle_recommendation(user_query, location, date, user_id)
        if intent == "WEATHER_QUERY":
            return self._handle_weather_query(location, date, user_id)
        if intent == "TIME_QUERY":
            return self._handle_time_query(user_query, user_id, location)
        return self._handle_unknown(user_query, routed_via_llm=True)

    def _handle_recommendation(self, query: str, location: str, date: str, user_id: str = "anonymous") -> str:
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

            # Apply deterministic preference filters from the user prompt before LLM synthesis.
            q = (query or "").lower()
            wants_indoor = "indoor" in q
            wants_outdoor = "outdoor" in q
            wants_free = "free" in q
            wants_budget = any(k in q for k in ["cheap", "budget", "affordable", "low cost", "low-cost"])

            filtered_events = events
            if wants_indoor and not wants_outdoor:
                filtered_events = [e for e in filtered_events if bool(e.get("indoor"))]
            elif wants_outdoor and not wants_indoor:
                filtered_events = [e for e in filtered_events if not bool(e.get("indoor"))]

            if wants_free:
                filtered_events = [e for e in filtered_events if float(e.get("price", 0) or 0) == 0.0]
            elif wants_budget:
                filtered_events = [e for e in filtered_events if float(e.get("price", 0) or 0) <= 20.0]

            if filtered_events:
                events = filtered_events
                print(f"  ✓ Filtered to {len(events)} event(s) by user preference")
            elif wants_indoor or wants_outdoor or wants_free or wants_budget:
                return (
                    "I couldn't find events matching all your requested filters for today. "
                    "Try relaxing one filter (for example, indoor-only or free-only)."
                )

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
            query_lower = query.lower()

            # Support explicit multi-day prompts like "today and tomorrow".
            if "today" in query_lower and "tomorrow" in query_lower:
                app_tz = os.environ.get("APP_TIMEZONE", "Asia/Singapore")
                try:
                    base = datetime.now(ZoneInfo(app_tz))
                except Exception:
                    base = datetime.now()
                d_today = base.strftime("%Y-%m-%d")
                d_tomorrow = (base + timedelta(days=1)).strftime("%Y-%m-%d")
                events_today = self.event_agent.get_events(d_today)
                events_tomorrow = self.event_agent.get_events(d_tomorrow)
                self.last_event_results = events_tomorrow if events_tomorrow else events_today
                self.last_event_date = d_tomorrow if events_tomorrow else d_today
                lines = [f"Events on {d_today}:"]
                if events_today:
                    for e in events_today:
                        indoor_text = "Yes" if e.get("indoor") else "No"
                        lines.append(
                            f"- {e.get('name')} ({e.get('type')}) at {e.get('location')}, "
                            f"{e.get('time')}, ${e.get('price')}, Capacity {e.get('capacity')}, Indoor: {indoor_text}"
                        )
                else:
                    lines.append("- No events found.")
                lines.append("")
                lines.append(f"Events on {d_tomorrow}:")
                if events_tomorrow:
                    for e in events_tomorrow:
                        indoor_text = "Yes" if e.get("indoor") else "No"
                        lines.append(
                            f"- {e.get('name')} ({e.get('type')}) at {e.get('location')}, "
                            f"{e.get('time')}, ${e.get('price')}, Capacity {e.get('capacity')}, Indoor: {indoor_text}"
                        )
                else:
                    lines.append("- No events found.")
                return "\n".join(lines)

            # Simple keyword filters for the DB query
            filters = {}
            if 'indoor' in query_lower:
                filters['indoor'] = True
            elif 'outdoor' in query_lower:
                filters['indoor'] = False
            
            events = self.event_agent.get_events(date, **filters)
            print(f"  ✓ Found {len(events)} events")

            if not events:
                return f"I couldn't find any events scheduled for {date}."

            # If this is a follow-up cost question, prefer last shown event context.
            cost_answer = self._calculate_cost_from_query(query, events, date)
            if cost_answer:
                return cost_answer

            # Store event context for subsequent follow-up questions.
            self.last_event_results = events
            self.last_event_date = date

            # For broad list-style event questions, return deterministic DB-backed output.
            ql = query_lower
            list_style = any(
                k in ql for k in [
                    "any event", "any events", "show", "list", "what events",
                    "events today", "event today"
                ]
            )
            if list_style:
                lines = [f"Events on {date}:"]
                for e in events:
                    indoor_text = "Yes" if e.get("indoor") else "No"
                    lines.append(
                        f"- {e.get('name')} ({e.get('type')}) at {e.get('location')}, "
                        f"{e.get('time')}, ${e.get('price')}, Capacity {e.get('capacity')}, "
                        f"Indoor: {indoor_text}"
                    )
                return "\n".join(lines)

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
            5. Use clear punctuation and spacing in full sentences.
            """

            text = self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": f"{self.TOURISM_PERSONA} {self._get_style_memory_prompt()}",
                    },
                    {"role": "user", "content": prompt},
                ],
                model=self.llm_model,
                temperature=0.3,
            )
            text = re.sub(r"asthepriceperpersonis", "as the price per person is", text, flags=re.IGNORECASE)
            # Fix common spacing/punctuation glitches from LLM output
            text = re.sub(r"\.(?=[A-Za-z])", ". ", text)
            text = re.sub(r",(?!\s)", ", ", text)
            text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
            text = re.sub(r"(?<=[0-9])(?=[A-Za-z])", " ", text)
            # Prevent markdown code/header artifacts from changing visual style.
            text = text.replace("`", "")
            text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
            text = re.sub(r"\s{2,}", " ", text).strip()
            return text

        except Exception as e:
            return f"Error processing event query: {str(e)}"

    def _calculate_cost_from_query(self, query: str, events: list, date: str) -> Optional[str]:
        """Compute total cost deterministically from follow-up event plan questions."""
        ql = query.lower()
        if not any(k in ql for k in ["how much", "cost", "price", "total"]):
            return None

        candidate_events = events or []
        candidate_date = date
        fallback_events = self.last_event_results or []
        fallback_date = self.last_event_date or date

        if not candidate_events and not fallback_events:
            return None

        llm_clarification_question = ""

        def _tokenize(text: str) -> set:
            words = re.findall(r"[a-z0-9]+", text.lower())
            stop = {
                "the", "a", "an", "at", "in", "on", "to", "for", "with", "and", "then",
                "person", "persons", "people", "pax", "attending", "attend", "going", "go",
                "session", "event", "my", "wife", "total", "cost", "price",
            }
            return {w for w in words if w not in stop}

        def _extract_target_phrase(seg: str) -> str:
            m = re.search(r"(?:attending|attend|for|to attend|going to|go to)\s+(.+)", seg)
            phrase = m.group(1) if m else seg
            phrase = re.split(r"\bwith\b", phrase)[0]
            phrase = re.split(r"[?!.]", phrase)[0]
            phrase = phrase.strip(" ,;:")
            return phrase

        def _match_event(seg: str):
            phrase = _extract_target_phrase(seg)
            phrase_tokens = _tokenize(phrase)
            if not phrase_tokens:
                return None, None, 0

            best_event = None
            best_date = None
            best_score = 0

            def score_dataset(dataset, ds_date):
                nonlocal best_event, best_date, best_score
                for ev in dataset:
                    haystack = f"{ev.get('name', '')} {ev.get('location', '')}"
                    ev_tokens = _tokenize(haystack)
                    score = len(phrase_tokens.intersection(ev_tokens))
                    # Extra confidence if event name appears verbatim in phrase.
                    ev_name = str(ev.get("name", "")).lower()
                    if ev_name and ev_name in phrase.lower():
                        score += 3
                    if score > best_score:
                        best_score = score
                        best_event = ev
                        best_date = ds_date

            score_dataset(candidate_events, candidate_date)
            score_dataset(fallback_events, fallback_date)
            return best_event, best_date, best_score

        def _strip_json_blob(text: str) -> str:
            if not text:
                return ""
            text = text.strip()
            if text.startswith("```"):
                m = re.search(r"\{[\s\S]*\}", text)
                return m.group(0) if m else text.strip("`")
            m = re.search(r"\{[\s\S]*\}", text)
            return m.group(0) if m else text

        def _infer_attendees_from_segment(seg: str) -> int:
            qty_match = re.search(r"(\d+)\s*(?:persons?|people|pax)\b", seg)
            if qty_match:
                # Explicit headcount (e.g. "6 people") is treated as total attendees.
                return max(1, int(qty_match.group(1)))

            companions = 0
            # Generic companion pattern: "with 5 colleagues and 3 partners" => +8
            for num in re.findall(r"\b(?:with|and)\s+(\d+)\s+[a-z][a-z0-9_-]*\b", seg, flags=re.IGNORECASE):
                companions += max(0, int(num))

            if companions == 0:
                # Minimal fallback if no explicit quantity is found.
                if "with " in seg:
                    companions = 1

            return max(1, 1 + companions)

        def _extract_legs_via_llm() -> List[dict]:
            nonlocal llm_clarification_question
            llm = getattr(self, "llm", None)
            llm_model = getattr(self, "llm_model", None)
            if not llm or not llm_model:
                return []

            all_events = []
            seen_names = set()
            for ev in candidate_events + fallback_events:
                name = str(ev.get("name", "")).strip()
                if name and name.lower() not in seen_names:
                    seen_names.add(name.lower())
                    all_events.append(name)

            if not all_events:
                return []

            system_prompt = (
                "You extract structured activity plans for cost calculation.\n"
                "Output STRICT JSON only with this shape:\n"
                "{\n"
                '  "legs": [\n'
                "    {\n"
                '      "activity_text": "string",\n'
                '      "attendees_total": 1,\n'
                '      "confidence": 0.0\n'
                "    }\n"
                "  ],\n"
                '  "needs_clarification": false,\n'
                '  "clarification_question": ""\n'
                "}\n"
                "Rules:\n"
                "- attendees_total is total people attending that activity, including the user.\n"
                "- Use one leg per activity mentioned.\n"
                "- If a count is not inferable, set needs_clarification=true and add a concise question.\n"
                "- No markdown, no commentary."
            )
            user_prompt = (
                f"User query:\n{query}\n\n"
                f"Available events:\n- " + "\n- ".join(all_events) + "\n\n"
                "Extract the plan."
            )

            try:
                raw = llm.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=llm_model,
                    temperature=0.0,
                    max_tokens=260,
                )
                blob = _strip_json_blob(raw)
                data = json.loads(blob)
                needs_clarification = bool(data.get("needs_clarification"))
                clarification_question = str(data.get("clarification_question") or "").strip()
                if needs_clarification and clarification_question:
                    llm_clarification_question = clarification_question
                legs = data.get("legs", [])
                if not isinstance(legs, list):
                    return []

                normalized = []
                for leg in legs:
                    if not isinstance(leg, dict):
                        continue
                    event_text = str(
                        leg.get("activity_text")
                        or leg.get("event")
                        or leg.get("event_name")
                        or leg.get("target")
                        or ""
                    ).strip()
                    if not event_text:
                        continue

                    attendees_total = leg.get("attendees_total")
                    if attendees_total is None and leg.get("companions") is not None:
                        try:
                            attendees_total = int(leg.get("companions")) + 1
                        except Exception:
                            attendees_total = None

                    try:
                        attendees_total = int(attendees_total)
                    except Exception:
                        continue

                    if attendees_total < 1 or attendees_total > 1000:
                        continue

                    confidence = leg.get("confidence")
                    try:
                        confidence = float(confidence) if confidence is not None else 1.0
                    except Exception:
                        confidence = 1.0
                    if confidence < 0.0 or confidence > 1.0:
                        confidence = 1.0

                    normalized.append(
                        {
                            "event_text": event_text.lower(),
                            "attendees": attendees_total,
                            "confidence": confidence,
                        }
                    )
                return normalized
            except Exception:
                return []

        def _extract_legs_with_fallback() -> List[dict]:
            def _extract_legs_regex() -> List[dict]:
                # Regex fallback for reliability when LLM extraction is unavailable
                # or returns an incomplete set of activities.
                segments = re.split(r"\s+\b(?:and|then)\b\s+(?=\d+\s*(?:persons?|people|pax)\b)", ql)
                if len(segments) == 1:
                    segments = re.split(r"\bthen\b", ql)
                return [
                    {"event_text": seg.strip(), "attendees": _infer_attendees_from_segment(seg)}
                    for seg in segments
                    if seg.strip()
                ]

            llm_legs = _extract_legs_via_llm()
            if llm_clarification_question:
                return []

            regex_legs = _extract_legs_regex()
            if not llm_legs:
                return regex_legs

            # Prefer whichever extraction captures more activity legs.
            # This prevents partial LLM parses from dropping a second activity.
            if len(regex_legs) > len(llm_legs):
                return regex_legs
            return llm_legs

        legs = _extract_legs_with_fallback()
        breakdown = []
        total = 0.0
        used_date = candidate_date
        for leg in legs:
            seg_text = leg.get("event_text", "").strip()
            if not seg_text:
                continue
            matched, matched_date, score = _match_event(seg_text)
            if not matched or score <= 0:
                continue

            attendees = max(1, int(leg.get("attendees", 1)))

            unit_price = float(matched.get("price", 0.0) or 0.0)
            event_cost = unit_price * attendees
            total += event_cost
            used_date = matched_date or used_date
            breakdown.append(
                f"- {matched.get('name')}: ${unit_price:.2f} x {attendees} = ${event_cost:.2f}"
            )

        if not breakdown:
            if llm_clarification_question:
                self.pending_cost_clarification_query = query
                return llm_clarification_question
            self.pending_cost_clarification_query = ""
            return None

        self.pending_cost_clarification_query = ""

        lines = [f"**Cost Summary ({used_date})**", ""]
        lines.extend(
            [
                # Escape currency marker to avoid markdown/math rendering artifacts.
                line.replace("$", r"\$")
                for line in breakdown
            ]
        )
        lines.append("")
        lines.append(f"**Total: \\${total:.2f}**")
        return "\n".join(lines)

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
                # fallback to LLM, then search if still no answer
                fallback = self._handle_unknown(query, routed_via_llm=True)
                if self._is_llm_no_answer(fallback):
                    return self._handle_search(query, user_id)
                return fallback

            return answer
        except Exception as e:
            fallback = self._handle_unknown(query, routed_via_llm=True)
            if self._is_llm_no_answer(fallback):
                return self._handle_search(query, user_id)
            return fallback

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
            "i don't have information",
            "i do not have information",
            "i don't have",
            "i do not have",
        ]
        return any(s in lowered for s in signals)

    def _is_llm_no_answer(self, answer: str) -> bool:
        """Heuristic to detect when LLM refuses or lacks info."""
        if not answer:
            return True
        lowered = answer.lower()
        signals = [
            "i don't have",
            "i do not have",
            "i can't access",
            "cannot access",
            "no real-time",
            "not have real-time",
            "please check the latest",
            "check the latest",
            "i'm sorry",
            "i cannot assist",
            "i can't assist",
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

    def _handle_time_query(self, query: str, user_id: str = "anonymous", location: str = None) -> str:
        """Handle time and date queries with human-readable responses, including timezone support."""
        print(f"[TIME QUERY] Getting current time/date")
        
        from zoneinfo import ZoneInfo
        
        # Resolve timezone via WeatherAPI for all time queries
        target_tz = None
        location_name = None
        location_query = None

        # First choice: location already extracted by chat agent.
        location_query = (location or "").strip()
        if not location_query:
            # Prefer explicit preposition-based location mentions to avoid false captures
            preposition_match = re.search(
                r'\b(?:in|at|for|near|of)\b\s+([A-Za-z][A-Za-z\s\-\'\.]+)',
                query,
                re.IGNORECASE,
            )
            if preposition_match:
                location_query = preposition_match.group(1).strip()
            else:
                fallback_patterns = [
                    r'([A-Za-z][A-Za-z\s\-\'\.]+)\s+(?:time|date|day)$',
                    r'(?:what\s+)?(?:time|date|day)\s+(?:is\s+it\s+)?([A-Za-z][A-Za-z\s\-\'\.]+)$',
                ]
                for pattern in fallback_patterns:
                    match = re.search(pattern, query, re.IGNORECASE)
                    if match:
                        location_query = match.group(1).strip()
                        break

        if not location_query:
            location_query = self.last_time_location_name

        # Clean up trailing punctuation and trailing context
        if location_query:
            location_query = re.split(r"[?!.]", location_query)[0]
            location_query = re.split(
                r"\b(now|today|tomorrow|yesterday|tonight|weather|how|please)\b",
                location_query,
                flags=re.IGNORECASE,
            )[0]
            location_query = re.sub(
                r"\b(time|date|day)\b",
                "",
                location_query,
                flags=re.IGNORECASE,
            )
            location_query = location_query.rstrip(" ,;:").strip()
            location_query = re.sub(r"\s+", " ", location_query)
            if len(location_query) < 2:
                location_query = None
            if not location_query:
                location_query = None

        if self.weather_agent and location_query:
            try:
                tz_data = self.weather_agent.get_timezone(location_query)
                if tz_data.get("tz_id"):
                    target_tz = tz_data["tz_id"]
                    location_name = tz_data.get("name") or location_query
            except Exception:
                pass

        # Remember last requested time zone (time queries only)
        if target_tz:
            self.last_time_tz = target_tz
            self.last_time_location_name = location_name
        
        # Get the appropriate time (default to last requested, Singapore initially)
        if ZoneInfo:
            if target_tz:
                now = datetime.now(ZoneInfo(target_tz))
            else:
                now = datetime.now(ZoneInfo(self.last_time_tz))
        else:
            now = datetime.now()
        
        location_display = location_name or self.last_time_location_name

        response = (
            f"🌍 Location: {location_display} "
            f"📅 Date: {now.strftime('%A, %B %d, %Y')} "
            f"🕐 Time: {now.strftime('%I:%M:%S %p')}"
        )
        return response

    def _handle_unknown(self, query: str, routed_via_llm: bool = False) -> str:
        """Handle unknown intents with a friendly response and guidance."""
        reminder = (
            "I’m focused on a few specific services right now. Try one of these:\n"
            "🎯 Recommendations → \"What should I do today?\"\n"
            "📋 Events → \"Show me events today\"\n"
            "📚 Future info → \"What concerts in 2026?\"\n"
            "🎨 Images → \"Generate an image of...\"\n"
            "☁️ Weather → \"How's the weather?\"\n"
            "⏰ Time → \"What time is it?\""
        )

        # Guardrail for time-sensitive/news/sports questions
        time_sensitive_notice = None
        if self._looks_time_sensitive(query):
            time_sensitive_notice = (
                "I don’t have reliable access to live sports/news results in this demo. "
                "I can still share general info, but it may be out of date."
            )

        try:
            reply = self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{self.TOURISM_PERSONA} "
                            f"{self._get_style_memory_prompt()} "
                            "Answer the user briefly and politely in 1-2 sentences. "
                            "If the question is outside the app’s core services, you may still answer "
                            "with general knowledge, but avoid claiming real-time or proprietary data."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                model=self.llm_model,
                max_tokens=80,
                temperature=0.4,
            )
            if routed_via_llm:
                routed_note = "Note: I couldn’t answer from the system’s data, so I routed this to the LLM."
                if time_sensitive_notice:
                    return f"{time_sensitive_notice}\n\n{reply}\n\n{routed_note}\n\n{reminder}"
                return f"{reply}\n\n{routed_note}\n\n{reminder}"
            if time_sensitive_notice:
                return f"{time_sensitive_notice}\n\n{reply}\n\n{reminder}"
            return f"{reply}\n\n{reminder}"
        except Exception:
            return reminder

    def _handle_search(self, query: str, user_id: str = "anonymous") -> str:
        """Fallback live search via SerpAPI if configured."""
        if not self.search_agent or not getattr(self.search_agent, "is_enabled", lambda: False)():
            return "Live search is not configured."
        try:
            results = self.search_agent.search(query)
            # Optional security scan of search output
            if self.security_enabled:
                _ = self.security_agent.scan_interaction(
                    prompt=f"Search query: {query}",
                    response=results,
                    ai_model="search",
                    app_user=user_id,
                    agent_name="search_agent"
                )
            return f"**Live Web Search:**\n{results}"
        except Exception as e:
            return f"Search error: {str(e)}"

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
