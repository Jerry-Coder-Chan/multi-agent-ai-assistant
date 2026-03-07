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
        # For GPT-5 family, keep reasoning off by default for lower latency/cost.
        self.openai_reasoning_effort = os.environ.get("OPENAI_REASONING_EFFORT", "none").strip().lower()
        self._openai_client = None

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
                payload["max_tokens"] = max_tokens
            try:
                response = self._openai_client.chat.completions.create(**payload)
            except Exception as e:
                # Fail open: if reasoning_effort is unsupported, retry without it.
                msg = str(e).lower()
                if "reasoning_effort" in msg and "reasoning_effort" in payload:
                    payload.pop("reasoning_effort", None)
                    response = self._openai_client.chat.completions.create(**payload)
                else:
                    raise
            return response.choices[0].message.content.strip()

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
        return (message.get("content") or "").strip()
