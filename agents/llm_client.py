import os
from typing import List, Dict, Optional

import requests
import openai


class LLMClient:
    """Simple chat client for OpenAI or Ollama."""

    def __init__(
        self,
        provider: str,
        openai_api_key: Optional[str] = None,
        ollama_base_url: Optional[str] = None,
        qwen_api_key: Optional[str] = None,
        qwen_base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        self.provider = (provider or "openai").lower()
        env_timeout = os.environ.get("OLLAMA_TIMEOUT")
        self.timeout = int(env_timeout) if env_timeout else timeout
        self.ollama_base_url = (ollama_base_url or os.environ.get("OLLAMA_BASE_URL") or "").rstrip("/")
        self.ollama_fallback_enabled = os.environ.get("ENABLE_OLLAMA_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
        self.ollama_fallback_model = (os.environ.get("OLLAMA_FALLBACK_MODEL") or "").strip() or "qwen3:8b"
        self.cloud_fallback_from_ollama = os.environ.get("ENABLE_CLOUD_FALLBACK_FROM_OLLAMA", "0").strip().lower() in {"1", "true", "yes", "on"}
        self.cloud_fallback_provider = (os.environ.get("CLOUD_FALLBACK_PROVIDER") or "openai").strip().lower()
        self.cloud_fallback_model = (os.environ.get("CLOUD_FALLBACK_MODEL") or "").strip()
        self._openai_api_key = openai_api_key
        self._qwen_api_key = qwen_api_key or os.environ.get("DASHSCOPE_API_KEY")
        self._qwen_base_url = (qwen_base_url or os.environ.get("DASHSCOPE_BASE_URL") or "").rstrip("/")
        # For GPT-5 family, keep reasoning off by default for lower latency/cost.
        self.openai_reasoning_effort = os.environ.get("OPENAI_REASONING_EFFORT", "none").strip().lower()
        self._openai_client = None
        self._cloud_fallback_client = None
        self._cloud_fallback_client_provider = ""

        if self.provider == "openai":
            if not openai_api_key:
                raise ValueError("OpenAI API key is required for OpenAI provider.")
            self._openai_client = openai.OpenAI(api_key=openai_api_key)
        elif self.provider == "qwen":
            qwen_key = qwen_api_key or os.environ.get("DASHSCOPE_API_KEY")
            qwen_url = (qwen_base_url or os.environ.get("DASHSCOPE_BASE_URL") or "").rstrip("/")
            if not qwen_key:
                raise ValueError("DASHSCOPE_API_KEY is required for Qwen provider.")
            if not qwen_url:
                raise ValueError("DASHSCOPE_BASE_URL is required for Qwen provider.")
            self._openai_client = openai.OpenAI(
                api_key=qwen_key,
                base_url=qwen_url
            )
        elif self.provider == "ollama":
            if not self.ollama_base_url:
                raise ValueError("OLLAMA_BASE_URL is required for Ollama provider.")
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        if self.provider in ("openai", "qwen"):
            payload: Dict[str, object] = {
                "model": model,
                "messages": messages,
            }
            model_l = (model or "").lower()
            is_openai_gpt5 = self.provider == "openai" and model_l.startswith("gpt-5")

            if is_openai_gpt5 and self.openai_reasoning_effort:
                payload["reasoning_effort"] = self.openai_reasoning_effort

            # Some GPT-5 variants may reject temperature/top_p controls in chat completions.
            # Keep temperature for non-GPT-5 models by default.
            if temperature is not None and not is_openai_gpt5:
                payload["temperature"] = temperature
            if max_tokens is not None:
                if is_openai_gpt5:
                    payload["max_completion_tokens"] = max_tokens
                else:
                    payload["max_tokens"] = max_tokens
            try:
                response = self._openai_client.chat.completions.create(**payload)
            except Exception as e:
                # Fail open: if reasoning_effort is unsupported, retry without it.
                msg = str(e).lower()
                if "reasoning_effort" in msg and "reasoning_effort" in payload:
                    payload.pop("reasoning_effort", None)
                    response = self._openai_client.chat.completions.create(**payload)
                elif "unsupported parameter" in msg and "max_tokens" in msg and "max_tokens" in payload and is_openai_gpt5:
                    payload.pop("max_tokens", None)
                    payload["max_completion_tokens"] = max_tokens
                    response = self._openai_client.chat.completions.create(**payload)
                else:
                    if self._should_use_ollama_fallback(e):
                        return self._chat_with_ollama(
                            messages=messages,
                            model=self.ollama_fallback_model,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                    raise
            return response.choices[0].message.content.strip()

        return self._chat_with_ollama(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _chat_with_ollama(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        payload: Dict[str, object] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        options: Dict[str, object] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if options:
            payload["options"] = options

        response = requests.post(
            f"{self.ollama_base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        message = data.get("message", {})
        content = (message.get("content") or "").strip()
        if self._should_escalate_ollama_output(messages, content):
            return self._chat_with_cloud_fallback(messages, temperature=temperature, max_tokens=max_tokens)
        return content

    def _should_use_ollama_fallback(self, exc: Exception) -> bool:
        if not self.ollama_fallback_enabled:
            return False
        if not self.ollama_base_url:
            return False
        msg = str(exc).lower()
        fallback_signals = [
            "insufficient_quota",
            "exceeded your current quota",
            "429",
            "rate limit",
            "timeout",
            "timed out",
            "connection error",
            "service unavailable",
            "temporarily unavailable",
        ]
        return any(s in msg for s in fallback_signals)

    def _should_escalate_ollama_output(self, messages: List[Dict[str, str]], content: str) -> bool:
        if not self.cloud_fallback_from_ollama:
            return False
        if not self._can_use_cloud_fallback():
            return False
        text = (content or "").strip().lower()
        if not text:
            return True
        vague_signals = [
            "i'm not sure",
            "i am not sure",
            "i don't know",
            "i do not know",
            "not enough information",
            "cannot determine",
            "can't determine",
            "unclear",
            "please clarify",
            "could you clarify",
            "as an ai",
            "error",
        ]
        if any(s in text for s in vague_signals):
            return True
        user_text = ""
        if messages:
            user_text = str(messages[-1].get("content", "")).strip().lower()
        asks_for_cost = any(k in user_text for k in ["how much", "total", "cost", "price"])
        mentions_multi_leg = any(k in user_text for k in [" and then ", " then ", " with my ", " with "])
        if asks_for_cost and mentions_multi_leg and "$" not in content:
            return True
        # Very short answers to long prompts are often incomplete.
        if len(user_text) > 80 and len(text) < 40:
            return True
        return False

    def _can_use_cloud_fallback(self) -> bool:
        if self.cloud_fallback_provider == "openai":
            return bool(self._openai_api_key)
        if self.cloud_fallback_provider == "qwen":
            return bool(self._qwen_api_key and self._qwen_base_url)
        return bool(self._openai_api_key or (self._qwen_api_key and self._qwen_base_url))

    def _get_cloud_fallback_client(self):
        if self._cloud_fallback_client is not None:
            return self._cloud_fallback_client, self._cloud_fallback_client_provider

        provider = self.cloud_fallback_provider
        if provider == "openai" and self._openai_api_key:
            self._cloud_fallback_client = openai.OpenAI(api_key=self._openai_api_key)
            self._cloud_fallback_client_provider = "openai"
            return self._cloud_fallback_client, self._cloud_fallback_client_provider
        if provider == "qwen" and self._qwen_api_key and self._qwen_base_url:
            self._cloud_fallback_client = openai.OpenAI(api_key=self._qwen_api_key, base_url=self._qwen_base_url)
            self._cloud_fallback_client_provider = "qwen"
            return self._cloud_fallback_client, self._cloud_fallback_client_provider

        # Auto fallback order.
        if self._openai_api_key:
            self._cloud_fallback_client = openai.OpenAI(api_key=self._openai_api_key)
            self._cloud_fallback_client_provider = "openai"
            return self._cloud_fallback_client, self._cloud_fallback_client_provider
        if self._qwen_api_key and self._qwen_base_url:
            self._cloud_fallback_client = openai.OpenAI(api_key=self._qwen_api_key, base_url=self._qwen_base_url)
            self._cloud_fallback_client_provider = "qwen"
            return self._cloud_fallback_client, self._cloud_fallback_client_provider
        return None, ""

    def _chat_with_cloud_fallback(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        client, provider = self._get_cloud_fallback_client()
        if client is None:
            raise RuntimeError("Cloud fallback requested but no cloud credentials are available.")

        model = self.cloud_fallback_model
        if not model:
            model = "gpt-5-mini" if provider == "openai" else "qwen-plus"

        payload: Dict[str, object] = {
            "model": model,
            "messages": messages,
        }
        if temperature is not None and not (provider == "openai" and model.lower().startswith("gpt-5")):
            payload["temperature"] = temperature
        if max_tokens is not None:
            if provider == "openai" and model.lower().startswith("gpt-5"):
                payload["max_completion_tokens"] = max_tokens
            else:
                payload["max_tokens"] = max_tokens
        if provider == "openai" and model.lower().startswith("gpt-5") and self.openai_reasoning_effort:
            payload["reasoning_effort"] = self.openai_reasoning_effort
        try:
            response = client.chat.completions.create(**payload)
        except Exception as e:
            msg = str(e).lower()
            if "reasoning_effort" in msg and "reasoning_effort" in payload:
                payload.pop("reasoning_effort", None)
                response = client.chat.completions.create(**payload)
            elif "unsupported parameter" in msg and "max_tokens" in msg and "max_tokens" in payload and provider == "openai" and model.lower().startswith("gpt-5"):
                payload.pop("max_tokens", None)
                payload["max_completion_tokens"] = max_tokens
                response = client.chat.completions.create(**payload)
            else:
                raise
        content = response.choices[0].message.content
        return (content or "").strip()
