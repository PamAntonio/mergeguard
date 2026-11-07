"""One test per hard-rule flag code (SPEC section 7), on fake diffs."""

from verifier.rules import Flag, decide, evaluate


def codes(flags):
    return {f.code for f in flags}


def test_tests_failed():
    flags = evaluate(diff_text="", changed_files=[], test_exit_code=1)
    assert codes(flags) == {"TESTS_FAILED"}


def test_test_deleted():
    diff = (
        "diff --git a/tests/test_tax.py b/tests/test_tax.py\n"
        "--- a/tests/test_tax.py\n"
        "+++ b/tests/test_tax.py\n"
        "@@ -1,2 +1,1 @@\n"
        "-def test_tax_rounding():\n"
        " def test_tax_basic():\n"
    )
    assert "TEST_DELETED" in codes(evaluate(diff))


def test_test_edited():
    diff = (
        "diff --git a/tests/test_tax.py b/tests/test_tax.py\n"
        "--- a/tests/test_tax.py\n"
        "+++ b/tests/test_tax.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-    assert add_tax(10.00, 0.0725) == Decimal(\"10.73\")\n"
        "+    assert add_tax(10.00, 0.0725) == Decimal(\"10.72\")\n"
        " def test_tax_basic():\n"
    )
    assert "TEST_EDITED" in codes(evaluate(diff))


def test_pure_test_addition_is_not_edited():
    diff = (
        "diff --git a/tests/test_tax.py b/tests/test_tax.py\n"
        "--- a/tests/test_tax.py\n"
        "+++ b/tests/test_tax.py\n"
        "@@ -1,1 +1,3 @@\n"
        "+def test_new_case():\n"
        "+    assert True is True\n"
        " def test_tax_basic():\n"
    )
    assert "TEST_EDITED" not in codes(evaluate(diff))


def test_test_skipped():
    diff = (
        "diff --git a/tests/test_tax.py b/tests/test_tax.py\n"
        "--- a/tests/test_tax.py\n"
        "+++ b/tests/test_tax.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+@pytest.mark.skip(reason='later')\n"
        " def test_tax_rounding():\n"
    )
    assert "TEST_SKIPPED" in codes(evaluate(diff))


def test_stubbed():
    diff = (
        "diff --git a/shop/tax.py b/shop/tax.py\n"
        "--- a/shop/tax.py\n"
        "+++ b/shop/tax.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+    raise NotImplementedError\n"
        " def add_tax(amount, rate):\n"
    )
    assert "STUBBED" in codes(evaluate(diff))


def test_fake_pass():
    diff = (
        "diff --git a/tests/test_tax.py b/tests/test_tax.py\n"
        "--- a/tests/test_tax.py\n"
        "+++ b/tests/test_tax.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+    assert True\n"
        " def test_tax_rounding():\n"
    )
    assert "FAKE_PASS" in codes(evaluate(diff))


def test_protected_file():
    diff = (
        "diff --git a/pytest.ini b/pytest.ini\n"
        "--- a/pytest.ini\n"
        "+++ b/pytest.ini\n"
        "@@ -1,1 +1,2 @@\n"
        "+addopts = -x\n"
        " [pytest]\n"
    )
    assert "PROTECTED_FILE" in codes(evaluate(diff))


def test_sensitive_path():
    diff = (
        "diff --git a/shop/auth.py b/shop/auth.py\n"
        "--- a/shop/auth.py\n"
        "+++ b/shop/auth.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-    return bool(user.get('logged_in'))\n"
        "+    return bool(user.get('logged_in')) and bool(user.get('verified'))\n"
    )
    assert codes(evaluate(diff)) == {"SENSITIVE_PATH"}


def test_claim_no_evidence():
    flags = evaluate(
        diff_text="", changed_files=[], test_exit_code=0,
        claim_text="Done. All tests pass.",
        steps=[{"n": 1, "kind": "edit", "tool": "edit",
                "detail": "edited shop/tax.py", "files": ["shop/tax.py"]}],
    )
    assert codes(flags) == {"CLAIM_NO_EVIDENCE"}


def test_claim_with_evidence_is_clean():
    flags = evaluate(
        diff_text="", changed_files=[], test_exit_code=0,
        claim_text="Done. All tests pass.",
        steps=[{"n": 2, "kind": "tool_call", "tool": "bash",
                "detail": "pytest -q", "result": "8 passed", "ok": True}],
    )
    assert flags == []
    assert decide(flags) == "MERGE"


def test_decide_order():
    assert decide([Flag("SENSITIVE_PATH", "medium", "x")]) == "NEEDS_APPROVAL"
    assert decide([Flag("TEST_SKIPPED", "high", "x")], attempts=3) == "BLOCK"
    assert decide([], fix_loop_ran=True) == "FIXED_THEN_MERGE"


def test_claims_folder_never_flagged():
    diff = (
        "diff --git a/.claims/task-b.md b/.claims/task-b.md\n"
        "--- a/.claims/task-b.md\n"
        "+++ b/.claims/task-b.md\n"
        "@@ -0,0 +1,1 @@\n"
        "+All tests pass. assert True\n"
    )
    assert evaluate(diff, test_exit_code=0) == []
