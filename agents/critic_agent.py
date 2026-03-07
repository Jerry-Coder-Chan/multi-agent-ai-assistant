"""
Critic Agent - Cross-LLM response reviewer for factual consistency and coherence.
"""
import json
import re
from typing import Dict, List, Optional

from agents.llm_client import LLMClient


class CriticAgent:
    """Reviews and optionally rewrites a draft response."""

    def __init__(
        self,
        provider: str,
        model: str,
        openai_api_key: str = "",
        ollama_base_url: str = "",
        qwen_api_key: str = "",
        qwen_base_url: str = "",
        llm_client=None,
    ):
        self.provider = (provider or "").lower()
        self.model = model
        self.client = llm_client
        self.enabled = bool(self.provider and self.model)

        if self.client is None and self.enabled:
            try:
                self.client = LLMClient(
                    provider=self.provider,
                    openai_api_key=openai_api_key,
                    ollama_base_url=ollama_base_url,
                    qwen_api_key=qwen_api_key,
                    qwen_base_url=qwen_base_url,
                )
            except Exception:
                self.enabled = False

    def is_enabled(self) -> bool:
        return self.enabled and self.client is not None

    def _is_quota_or_rate_error(self, err: str) -> bool:
        msg = (err or "").lower()
        signals = [
            "insufficient_quota",
            "quota",
            "rate limit",
            "ratelimit",
            "429",
            "exceeded",
            "billing",
            "credits",
            "balance",
        ]
        return any(s in msg for s in signals)

    def _extract_json_object(self, text: str) -> Optional[dict]:
        if not text:
            return None
        raw = text.strip()
        try:
            return json.loads(raw)
        except Exception:
            pass
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    def review_response(
        self,
        user_query: str,
        draft_response: str,
        intents: List[str],
        recent_history: List[Dict],
        tourism_persona: str,
        style_memory: str,
    ) -> Dict[str, str]:
        """Return dict: {response, status, reason}."""
        if not self.is_enabled():
            return {"response": draft_response, "status": "disabled", "reason": "critic_disabled"}
        if not draft_response or not draft_response.strip():
            return {"response": draft_response, "status": "skipped", "reason": "empty_response"}

        history_lines = []
        for turn in (recent_history or [])[-6:]:
            q = str(turn.get("query", "")).strip()
            a = str(turn.get("response", "")).strip()
            if q or a:
                history_lines.append(f"User: {q}\nAssistant: {a}")
        history_block = "\n\n".join(history_lines) if history_lines else "No prior conversation."

        system_prompt = (
            "You are a strict response critic and editor.\n"
            "Goal:\n"
            "1) Detect factual/math/context inconsistencies.\n"
            "2) Improve coherence and tone continuity with prior conversation.\n"
            "3) Preserve facts, numbers, dates, prices, and named entities unless correcting an obvious inconsistency.\n"
            "Output STRICT JSON only:\n"
            "{"
            '"action":"keep|rewrite",'
            '"rewritten_response":"...",'
            '"reason":"short reason"'
            "}"
        )
        user_prompt = (
            f"Persona:\n{tourism_persona}\n\n"
            f"Style memory:\n{style_memory}\n\n"
            f"Detected intents:\n{', '.join(intents or [])}\n\n"
            f"Recent conversation:\n{history_block}\n\n"
            f"Current user query:\n{user_query}\n\n"
            f"Draft response:\n{draft_response}\n\n"
            "If the draft is already correct and coherent, return action=keep."
        )

        try:
            raw = self.client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=self.model,
                temperature=0.1,
                max_tokens=600,
            )
            if not raw or not raw.strip():
                return {"response": draft_response, "status": "skipped", "reason": "empty_critic_output"}

            parsed = self._extract_json_object(raw)
            if not isinstance(parsed, dict):
                return {"response": draft_response, "status": "skipped", "reason": "invalid_critic_json"}

            action = str(parsed.get("action", "keep")).strip().lower()
            rewritten = str(parsed.get("rewritten_response", "")).strip()
            reason = str(parsed.get("reason", "")).strip() or "no_reason"

            if action == "rewrite" and rewritten:
                return {"response": rewritten, "status": "applied", "reason": reason}
            return {"response": draft_response, "status": "kept", "reason": reason}
        except Exception as e:
            msg = str(e)
            if self._is_quota_or_rate_error(msg):
                return {"response": draft_response, "status": "skipped_quota", "reason": msg}
            return {"response": draft_response, "status": "skipped_error", "reason": msg}
