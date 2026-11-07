from verifier.evidence import exclude_ignored, is_ignored_path


def test_claims_folder_is_ignored():
    assert is_ignored_path(".claims/task-b.md")
    assert is_ignored_path(".claims/.gitkeep")


def test_normal_paths_are_not_ignored():
    assert not is_ignored_path("shop/tax.py")
    assert not is_ignored_path("tests/test_tax.py")
    assert not is_ignored_path("shop/claims.py")


def test_exclude_ignored_filters_claims_only():
    paths = ["shop/tax.py", ".claims/task-b.md", "tests/test_tax.py"]
    assert exclude_ignored(paths) == ["shop/tax.py", "tests/test_tax.py"]
