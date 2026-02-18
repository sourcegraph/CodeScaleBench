#!/usr/bin/env python3
"""List Gemini models available for the configured API key and optionally test a model.

Uses GEMINI_API_KEY or GOOGLE_API_KEY (same env vars as the Gemini harness and
OpenHands/LiteLLM). Run this to confirm which models your key can access before
running OpenHands or the Gemini harness with a specific model.

Usage:
    python3 scripts/list_gemini_models.py --check-key     # validate API key only
    python3 scripts/list_gemini_models.py                 # list models
    python3 scripts/list_gemini_models.py --test-model gemini-2.0-flash
    python3 scripts/list_gemini_models.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _check_api_key() -> str | None:
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key or not key.strip():
        return None
    return key.strip()


def _import_genai():
    try:
        from google import genai
        return genai
    except ImportError:
        return None


def validate_key() -> tuple[bool, str | None]:
    """Test if the current env's API key is accepted by the Gemini API.
    Returns (True, None) if valid, (False, error_message) otherwise.
    """
    from google import genai
    client = genai.Client()
    try:
        # One successful API call is enough (list models is cheap and key-scoped)
        for _ in client.models.list():
            break
        return True, None
    except Exception as e:
        return False, str(e)


def list_models(page_size: int = 100) -> list[dict]:
    """Return list of model info dicts from the Gemini API.
    Uses GEMINI_API_KEY or GOOGLE_API_KEY from the environment (same as Client()).
    """
    from google import genai
    client = genai.Client()
    result = []
    for model in client.models.list():
        # Model may be a protobuf or pydantic object; normalize to dict-like
        name = getattr(model, "name", None) or str(model)
        if name and name.startswith("models/"):
            name = name[7:]  # strip prefix for display and --test-model
        if hasattr(model, "display_name"):
            display = getattr(model, "display_name", "")
        else:
            display = ""
        result.append({"name": name, "display_name": display})
    return result


def test_model(model_id: str) -> tuple[bool, str]:
    """Try a minimal generate_content call; return (success, message).
    Uses GEMINI_API_KEY or GOOGLE_API_KEY from the environment (same as Client()).
    """
    from google import genai
    client = genai.Client()
    try:
        response = client.models.generate_content(
            model=model_id,
            contents="Reply with exactly: OK",
        )
        text = (response.text or "").strip()
        if "OK" in text or response.candidates:
            return True, "Model responded successfully."
        return True, f"Model responded (no 'OK' in text): {text[:200]}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List Gemini models for the configured API key and optionally test one."
    )
    parser.add_argument(
        "--check-key",
        action="store_true",
        help="Only validate that GEMINI_API_KEY/GOOGLE_API_KEY is accepted; exit 0 if valid.",
    )
    parser.add_argument(
        "--test-model",
        metavar="MODEL",
        help="Test this model with a minimal generate_content call.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output model list as JSON.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Page size for list (default 100).",
    )
    args = parser.parse_args()

    api_key = _check_api_key()
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY or GOOGLE_API_KEY.", file=sys.stderr)
        return 1

    genai = _import_genai()
    if genai is None:
        print(
            "ERROR: google-genai not installed. Install with: pip install google-genai",
            file=sys.stderr,
        )
        return 1

    if args.check_key:
        valid, err = validate_key()
        if valid:
            print("Key is valid.")
            return 0
        print("Key is invalid or not accepted:", err, file=sys.stderr)
        return 1

    if args.test_model:
        ok, msg = test_model(args.test_model)
        if ok:
            print(f"OK: {msg}")
            return 0
        print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    try:
        models = list_models(page_size=args.page_size)
    except Exception as e:
        print(f"ERROR listing models: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(models, indent=2))
        return 0

    print("Models available for your API key (use --test-model <name> to verify):")
    print("")
    for m in models:
        name = m.get("name", "")
        display = m.get("display_name", "")
        if name:
            print(f"  {name}" + (f"  ({display})" if display else ""))
    if not models:
        print("  (none listed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
