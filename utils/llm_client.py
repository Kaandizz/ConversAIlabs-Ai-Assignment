import time
from typing import Any, Dict, Optional

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
    MAX_RETRIES,
)
from utils.logger import logger


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self.api_key = api_key or LLM_API_KEY
        self.base_url = base_url or LLM_BASE_URL
        self.model = model or LLM_MODEL
        self.temperature = LLM_TEMPERATURE
        self.max_retries = MAX_RETRIES
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else LLM_TIMEOUT_SECONDS
        self.logger = logger

        self._client = None
        self._init_client()

    _PLACEHOLDER_TOKENS = {"your", "xxx", "example", "changeme", "insert", "here"}

    def _is_placeholder_key(self, key: str) -> bool:
        if not key:
            return True
        key_lower = key.lower()
        for token in self._PLACEHOLDER_TOKENS:
            if token in key_lower:
                return True
        return False

    def _init_client(self) -> None:
        if self._is_placeholder_key(self.api_key):
            self.logger.warning(
                "LLM_API_KEY looks like a placeholder. "
                "Copy .env.example to .env and set your real API key."
            )
            return

        try:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
            self.logger.info(
                f"LLM client initialized: model={self.model} "
                f"base_url={self.base_url} timeout={self.timeout_seconds}s"
            )
        except ImportError:
            self.logger.error(
                "OpenAI SDK not installed. Run: pip install -r requirements.txt"
            )
            self._client = None

    def _is_nvidia(self) -> bool:
        return "nvidia.com" in self.base_url.lower()

    _NVIDIA_FAST_MODELS = [
        "meta/llama-3.1-8b-instruct",
        "microsoft/phi-3-mini-128k-instruct",
        "mistralai/mistral-7b-instruct-v0.3",
    ]

    _NVIDIA_FREE_MODELS = [
        "mistralai/codestral-22b-instruct-v0.1",
        "nvidia/llama-3.3-nemotron-super-49b-v1",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia/llama-3.1-nemotron-ultra-253b-v1",
        "nvidia/llama3-chatqa-1.5-70b",
        "nvidia/nemotron-3-super-120b-a12b",
        "meta/llama-3.1-70b-instruct",
        "meta/llama-3.1-8b-instruct",
        "mistralai/mistral-7b-instruct-v0.3",
        "microsoft/phi-3-mini-128k-instruct",
    ]

    def _format_error(self, exc: Exception) -> str:
        msg = str(exc)
        if self._is_nvidia() and "404" in msg:
            tips = (
                "NVIDIA NIM — 404 usually means: "
                "(1) wrong model slug (case-sensitive, use 'org/model-name'), "
                "or (2) the model is not activated on your account. "
                "Browse https://build.nvidia.com/models, select the model, "
                "and click 'Try Now' / 'Get API Key' to accept the TOS. "
                f"Known free models: {', '.join(self._NVIDIA_FREE_MODELS[:5])}..."
            )
            return f"{msg} [HINT: {tips}]"
        if self._is_nvidia() and ("timeout" in msg.lower() or "timed out" in msg.lower()):
            fast = ", ".join(self._NVIDIA_FAST_MODELS)
            tips = (
                f"Model {self.model!r} is slow or NIM queue is busy. "
                f"Try one of the fast/free small models: {fast}. "
                f"Increase LLM_TIMEOUT_SECONDS=240 in .env if you want to keep waiting."
            )
            return f"{msg} [HINT: {tips}]"
        return msg

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        if self._client is None:
            raise RuntimeError(
                "LLM client not available. Check API key and dependencies."
            )

        temp = temperature if temperature is not None else self.temperature

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temp,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if response_format:
            kwargs["response_format"] = response_format

        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                self.logger.debug(
                    f"LLM call: model={self.model} attempt={attempt+1}/{self.max_retries+1} "
                    f"max_tokens={max_tokens or 'unlimited'} timeout={self.timeout_seconds}s"
                )
                start = time.time()
                completion = self._client.chat.completions.create(**kwargs)
                elapsed = time.time() - start
                content = completion.choices[0].message.content or ""

                usage = getattr(completion, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
                completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

                self.logger.debug(
                    f"LLM response: {len(content)} chars in {elapsed:.1f}s "
                    f"(prompt={prompt_tokens}, completion={completion_tokens})"
                )
                return content

            except Exception as e:
                last_exception = e
                formatted = self._format_error(e)
                wait = 2 ** attempt
                self.logger.warning(
                    f"LLM call failed (attempt {attempt+1}/{self.max_retries+1}): {formatted}. "
                    f"Retrying in {wait}s..."
                )
                if attempt < self.max_retries:
                    time.sleep(wait)

        raise RuntimeError(
            f"LLM call failed after {self.max_retries + 1} attempts: "
            f"{self._format_error(last_exception) if last_exception else 'unknown'}"
        )
