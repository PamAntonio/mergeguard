"""Risk reason: SENSITIVE_PATH -> NEEDS_APPROVAL, plus one Muse Spark
call for a one-sentence reason. (Baseten cut.)"""

import os


def risk_reason(diff, changed_files):
    """One Spark call. Returns {'score', 'reason', 'areas', 'source'}."""
    from dotenv import load_dotenv
    load_dotenv()
    from verifier.audit import _client, _extract, _parse_json
    model = os.environ.get("AUDITOR_MODEL", "").strip() or "muse-spark-1.3"
    prompt = (
        "Rate the merge risk of this diff (security-sensitive areas like auth "
        "score high). Reply JSON only: "
        '{"score": 1, "reason": "one sentence", "areas": ["auth"]}\n'
        f"Changed files: {changed_files}\nDiff:\n{diff[:8000]}"
    )
    try:
        resp = _client().chat.completions.create(
            model=model, max_tokens=800, reasoning_effort="minimal",
            messages=[{"role": "user", "content": prompt}])
        data = _parse_json(_extract(resp))
        score = int(data.get("score", 0))
        return {"score": max(1, min(10, score)),
                "reason": str(data.get("reason", ""))[:300],
                "areas": list(data.get("areas") or []), "source": "muse-spark"}
    except Exception as exc:
        return {"score": None,
                "reason": f"Risk model unavailable ({type(exc).__name__}); "
                          "sensitive path still requires human approval.",
                "areas": [], "source": "fallback"}
