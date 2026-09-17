"""Phase 0 verification: the package is intentionally implementation-free."""

from support_agent import __doc__


def test_package_imports() -> None:
    assert "implementation begins after Phase 1" in (__doc__ or "")
