"""Hard rules, no AI (SPEC section 7).

Every flag is decided from the diff, the real test exit code, the
claim text, and the event-log steps. AI can add flags but never
remove one; anything in FIX_LOOP_CODES sends the change back.
"""

import re
from dataclasses import dataclass

from verifier.evidence import is_ignored_path

FIX_LOOP_CODES = frozenset({
    "TESTS_FAILED", "TEST_DELETED", "TEST_SKIPPED", "TEST_EDITED", "STUBBED",
    "FAKE_PASS", "PROTECTED_FILE", "CLAIM_NO_EVIDENCE",
})
SENSITIVE_WORDS = ("auth", "payment", "billing", "migration")

_CLAIM_PASS_RE = re.compile(
    r"(all\s+)?tests?\s+(pass|passed|passing)\b|test suite\s+(passes|passed)",
    re.IGNORECASE,
)
_RAN_TESTS_RE = re.compile(r"pytest|unittest|nosetests", re.IGNORECASE)
_SKIP_RE = re.compile(r"mark\.(skip|skipif|xfail)|pytest\.skip|unittest\.skip|\bskipif\b|\bxfail\b")
_FAKE_PASS_RE = re.compile(r"assert\s+True\b|sys\.exit\(\s*0\s*\)|os\._exit")
_STUB_RE = re.compile(r"raise\s+NotImplementedError")
_TEST_DEF_RE = re.compile(r"def\s+test_")


@dataclass
class Flag:
    code: str
    severity: str
    detail: str
    source: str = "rule"
    step: object = None

    def to_dict(self):
        return {
            "source": self.source, "code": self.code,
            "severity": self.severity, "detail": self.detail,
            "step": self.step,
        }


def _is_test_path(path):
    parts = str(path).replace("\\", "/").split("/")
    name = parts[-1]
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")


def _parse_diff(diff_text):
    """Return {path: {"added": [...], "removed": [...], "deleted": bool}}."""
    files = {}
    current = None
    old_path = None
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git"):
            current, old_path = None, None
        elif line.startswith("--- "):
            old_path = line[4:].strip()
            if old_path.startswith("a/"):
                old_path = old_path[2:]
        elif line.startswith("+++ "):
            new_path = line[4:].strip()
            if new_path == "/dev/null":
                current = old_path
                if current:
                    files.setdefault(current, {"added": [], "removed": [], "deleted": True})
                    files[current]["deleted"] = True
            else:
                if new_path.startswith("b/"):
                    new_path = new_path[2:]
                current = new_path
                files.setdefault(current, {"added": [], "removed": [], "deleted": False})
        elif current is not None and line.startswith("+"):
            files[current]["added"].append(line[1:])
        elif current is not None and line.startswith("-"):
            files[current]["removed"].append(line[1:])
    return files


def _claim_says_tests_pass(claim_text):
    return bool(_CLAIM_PASS_RE.search(claim_text or ""))


def _steps_ran_tests(steps):
    for step in steps or []:
        text = " ".join(str(step.get(k, "")) for k in ("tool", "detail", "result"))
        if _RAN_TESTS_RE.search(text):
            return True
    return False


def evaluate(diff_text="", changed_files=None, test_exit_code=None,
             claim_text="", steps=None, audit_flags=None):
    """Apply every hard rule and return a list of Flag."""
    flags = []
    parsed = _parse_diff(diff_text)
    if changed_files is None:
        changed_files = list(parsed.keys())
    changed = [p for p in changed_files if not is_ignored_path(p)]

    if test_exit_code is not None and test_exit_code != 0:
        flags.append(Flag("TESTS_FAILED", "high",
                          f"real test run exited with code {test_exit_code}"))

    for path in changed:
        entry = parsed.get(path, {"added": [], "removed": [], "deleted": False})
        added = entry["added"]
        removed = entry["removed"]
        is_test = _is_test_path(path)

        if is_test and (entry["deleted"] or any(_TEST_DEF_RE.search(l) for l in removed)):
            flags.append(Flag("TEST_DELETED", "high", f"test removed in {path}"))
        if is_test and removed and not entry["deleted"]:
            flags.append(Flag("TEST_EDITED", "high", f"existing test lines changed/removed in {path}"))
        if is_test and any(_SKIP_RE.search(l) for l in added):
            flags.append(Flag("TEST_SKIPPED", "high", f"skip/xfail added in {path}"))
        if not is_test and any(_STUB_RE.search(l) for l in added):
            flags.append(Flag("STUBBED", "high", f"NotImplementedError added in {path}"))
        if any(_FAKE_PASS_RE.search(l) for l in added):
            flags.append(Flag("FAKE_PASS", "high", f"fake pass added in {path}"))

        low = path.lower()
        if (low == "pytest.ini" or low.endswith("/pytest.ini")
                or low == "tests/conftest.py" or low.endswith("/tests/conftest.py")
                or low.startswith(".github/") or "/.github/" in low
                or (low.endswith("pyproject.toml")
                    and any("pytest" in l for l in added + removed))):
            flags.append(Flag("PROTECTED_FILE", "high", f"protected file changed: {path}"))
        if any(word in low for word in SENSITIVE_WORDS):
            flags.append(Flag("SENSITIVE_PATH", "medium", f"sensitive path changed: {path}"))

    if _claim_says_tests_pass(claim_text) and not _steps_ran_tests(steps):
        flags.append(Flag("CLAIM_NO_EVIDENCE", "high",
                          "claim says tests pass but no step ran the tests"))

    for flag in audit_flags or []:
        flags.append(flag)
    return flags


def decide(flags, attempts=0, fix_loop_ran=False):
    """Decision, always in SPEC section 7 order."""
    codes = {f.code for f in flags}
    needs_fix = bool(codes & FIX_LOOP_CODES) or any(
        f.source == "audit" and f.severity == "high" for f in flags)
    if needs_fix:
        return "BLOCK" if attempts >= 3 else "FIX_LOOP"
    if "SENSITIVE_PATH" in codes:
        return "NEEDS_APPROVAL"
    return "FIXED_THEN_MERGE" if fix_loop_ran else "MERGE"
