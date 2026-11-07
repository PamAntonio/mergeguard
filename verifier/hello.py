"""M0 hello checks: one tiny real call each to the Meta Model API,
Baseten, and MongoDB. Prints OK per service; exits non-zero if any
service is unconfigured or unreachable. Never prints a fake OK.

Run:  python -m verifier.hello
"""

import os
import sys

from dotenv import load_dotenv


def _extract_text(resp):
    """Return (text, field_name, debug) checking every text field."""
    choice = resp.choices[0]
    message = choice.message
    try:
        data = message.model_dump()
    except Exception:
        data = {}
    for field in ("content", "reasoning_content", "reasoning"):
        value = data.get(field) or getattr(message, field, None)
        if value and str(value).strip():
            return str(value).strip(), field, ""
    debug = (
        f"finish_reason={choice.finish_reason} "
        f"message_fields={sorted(data.keys())} "
        f"usage={resp.usage}"
    )
    return "", None, debug


def _chat_hello(label, key_name, url_name, model_name, default_model,
                max_tokens=512, reasoning_effort=None):
    api_key = os.environ.get(key_name, "").strip()
    base_url = os.environ.get(url_name, "").strip()
    if not api_key or not base_url:
        return label, False, f"missing {key_name}/{url_name} in .env"
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)
    model = os.environ.get(model_name, "").strip() or default_model
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": "Say OK"}],
        "max_tokens": max_tokens,
    }
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:
        body = getattr(exc, "body", None)
        status = getattr(exc, "status_code", None)
        return label, False, f"status={status} error={exc} body={body}"
    text, field, debug = _extract_text(resp)
    if not text:
        return label, False, f"empty response ({debug})"
    return label, True, f"model={model} field={field} replied {text[:40]!r}"


def check_meta():
    # Muse Spark is a reasoning model: it needs room for reasoning
    # tokens, or the visible reply comes back empty.
    return _chat_hello(
        "Meta Model API", "META_API_KEY", "META_BASE_URL",
        "AUDITOR_MODEL", "muse-spark-1.3",
        max_tokens=512, reasoning_effort="minimal",
    )


def check_baseten():
    return _chat_hello(
        "Baseten", "BASETEN_API_KEY", "BASETEN_BASE_URL",
        "RISK_MODEL", "meta-models/muse-spark-open-1026",
    )


def check_mongodb():
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        return "MongoDB", False, "missing MONGODB_URI in .env"
    from pymongo import MongoClient

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    finally:
        client.close()
    return "MongoDB", True, "ping succeeded"


def main():
    load_dotenv()
    results = []
    for check in (check_meta, check_baseten, check_mongodb):
        try:
            results.append(check())
        except Exception as exc:  # any error means not OK, never a pass
            results.append((check.__name__, False, f"{type(exc).__name__}: {exc}"))
    all_ok = True
    for label, ok, detail in results:
        print(f"{label}: {'OK' if ok else 'FAIL'} ({detail})")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
