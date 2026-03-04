"""LLM API backends for the CCB LLM Judge.

Supports Anthropic (Claude) and OpenAI (GPT) models.
Handles authentication, retries with exponential backoff, and response parsing.
Uses native SDKs if available, falls back to urllib.request.
"""

from __future__ import annotations

import json
import os
import re
import time


class JudgeBackendError(Exception):
    """Non-retryable backend failure."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _parse_json(raw: str) -> dict:
    """Extract and parse JSON from the model's text response.

    Handles responses wrapped in ```json ... ``` code blocks.
    """
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    raise JudgeBackendError(
        f"Failed to parse JSON from response: {text[:200]}...",
        status_code=None,
    )


class AnthropicBackend:
    """Minimal Anthropic API backend with retry logic.

    Args:
        model: Model identifier (e.g. 'claude-haiku-4-5-20251001').
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in response.
    """

    _MAX_RETRIES = 3

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ---- public API ----

    def call(self, system_prompt: str, user_prompt: str) -> dict:
        """Send a prompt pair and return the parsed JSON response.

        Retries up to 3 times on rate-limit (429) or server errors (>=500)
        with exponential backoff (2^n seconds).

        Raises:
            JudgeBackendError: On non-retryable failures or exhausted retries.
        """
        last_err: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                raw = self._raw_call(system_prompt, user_prompt)
                return _parse_json(raw)
            except JudgeBackendError as exc:
                if exc.status_code and (exc.status_code == 429 or exc.status_code >= 500):
                    last_err = exc
                    delay = 2 ** attempt
                    time.sleep(delay)
                    continue
                raise
        raise JudgeBackendError(
            f"Exhausted {self._MAX_RETRIES} retries: {last_err}",
            status_code=getattr(last_err, "status_code", None),
        )

    # ---- internals ----

    def _raw_call(self, system_prompt: str, user_prompt: str) -> str:
        """Call the API and return the raw text content."""
        try:
            return self._call_sdk(system_prompt, user_prompt)
        except ImportError:
            return self._call_urllib(system_prompt, user_prompt)

    def _call_sdk(self, system_prompt: str, user_prompt: str) -> str:
        """Call via the anthropic Python SDK."""
        import anthropic  # type: ignore[import-untyped]

        client = anthropic.Anthropic()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.RateLimitError as exc:
            raise JudgeBackendError(str(exc), status_code=429) from exc
        except anthropic.APIStatusError as exc:
            raise JudgeBackendError(str(exc), status_code=exc.status_code) from exc

        return response.content[0].text

    def _call_urllib(self, system_prompt: str, user_prompt: str) -> str:
        """Fallback: call via urllib.request with ANTHROPIC_API_KEY env var."""
        import urllib.request
        import urllib.error

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise JudgeBackendError(
                "ANTHROPIC_API_KEY not set and anthropic SDK not installed",
                status_code=None,
            )

        payload = json.dumps({
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read())
                return body["content"][0]["text"]
        except urllib.error.HTTPError as exc:
            raise JudgeBackendError(
                f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}",
                status_code=exc.code,
            ) from exc



class OpenAIBackend:
    """OpenAI API backend with retry logic.

    Uses a different model family from the Claude agent to avoid same-family
    evaluation bias.

    Args:
        model: Model identifier (e.g. 'gpt-4o', 'gpt-4o-mini').
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in response.
    """

    _MAX_RETRIES = 3

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ---- public API ----

    def call(self, system_prompt: str, user_prompt: str) -> dict:
        """Send a prompt pair and return the parsed JSON response.

        Retries up to 3 times on rate-limit (429) or server errors (>=500)
        with exponential backoff (2^n seconds).

        Raises:
            JudgeBackendError: On non-retryable failures or exhausted retries.
        """
        last_err: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                raw = self._raw_call(system_prompt, user_prompt)
                return _parse_json(raw)
            except JudgeBackendError as exc:
                if exc.status_code and (exc.status_code == 429 or exc.status_code >= 500):
                    last_err = exc
                    delay = 2 ** attempt
                    time.sleep(delay)
                    continue
                raise
        raise JudgeBackendError(
            f"Exhausted {self._MAX_RETRIES} retries: {last_err}",
            status_code=getattr(last_err, "status_code", None),
        )

    # ---- internals ----

    def _raw_call(self, system_prompt: str, user_prompt: str) -> str:
        """Call the API and return the raw text content."""
        try:
            return self._call_sdk(system_prompt, user_prompt)
        except ImportError:
            return self._call_urllib(system_prompt, user_prompt)

    def _call_sdk(self, system_prompt: str, user_prompt: str) -> str:
        """Call via the openai Python SDK."""
        import openai  # type: ignore[import-untyped]

        client = openai.OpenAI()
        try:
            response = client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except openai.RateLimitError as exc:
            raise JudgeBackendError(str(exc), status_code=429) from exc
        except openai.APIStatusError as exc:
            raise JudgeBackendError(str(exc), status_code=exc.status_code) from exc

        return response.choices[0].message.content or ""

    def _call_urllib(self, system_prompt: str, user_prompt: str) -> str:
        """Fallback: call via urllib.request with OPENAI_API_KEY env var."""
        import urllib.request
        import urllib.error

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise JudgeBackendError(
                "OPENAI_API_KEY not set and openai SDK not installed",
                status_code=None,
            )

        payload = json.dumps({
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read())
                return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            raise JudgeBackendError(
                f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}",
                status_code=exc.code,
            ) from exc


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

# Model prefixes that route to OpenAI
_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-")


def create_backend(
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> AnthropicBackend | OpenAIBackend:
    """Create the appropriate backend based on model identifier.

    Routing:
        - ``claude-*`` → AnthropicBackend
        - ``gpt-*``, ``o1-*``, ``o3-*``, ``o4-*`` → OpenAIBackend

    Raises:
        ValueError: If model name doesn't match any known provider.
    """
    name = model.lower()
    if name.startswith("claude"):
        return AnthropicBackend(model=model, temperature=temperature, max_tokens=max_tokens)
    if any(name.startswith(p) for p in _OPENAI_PREFIXES):
        return OpenAIBackend(model=model, temperature=temperature, max_tokens=max_tokens)
    raise ValueError(
        f"Cannot determine provider for model '{model}'. "
        f"Expected 'claude-*' (Anthropic) or 'gpt-*'/'o1-*'/'o3-*'/'o4-*' (OpenAI)."
    )
