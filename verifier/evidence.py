"""Evidence gathering: diff, real test run, event-log reader.

Implemented in M1/M2. M0 only pins down which paths never count as
evidence: the demo-shop `.claims/` folder holds the agent's final
message, so changes there must be ignored in diffs.
"""

# Path segments that are ignored in diffs (exact segment match).
IGNORED_PATH_SEGMENTS = frozenset({".claims"})


def is_ignored_path(path):
    """Return True if `path` is inside a `.claims/` folder."""
    parts = [p for p in str(path).replace("\\", "/").split("/") if p not in ("", ".")]
    return any(part in IGNORED_PATH_SEGMENTS for part in parts)


def exclude_ignored(paths):
    """Return the paths from `paths` that are not ignored in diffs."""
    return [p for p in paths if not is_ignored_path(p)]
