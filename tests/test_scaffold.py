"""Phase 0 verification: the package is intentionally implementation-free."""

from support_agent import __doc__


def test_package_imports() -> None:
    assert "Evaluation-first infrastructure" in (__doc__ or "")
