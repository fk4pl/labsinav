"""Python sürümü uyarısı: 3.15+ ise Türkçe uyarı, 3.11–3.14 ise sessiz."""

from shared.python_check import unsupported_python_message


def test_tested_versions_have_no_warning() -> None:
    for version in ((3, 11, 0), (3, 13, 5), (3, 14, 9)):
        assert unsupported_python_message(version) is None


def test_newer_python_gets_turkish_warning() -> None:
    message = unsupported_python_message((3, 15, 0))
    assert message is not None
    assert "3.11–3.14" in message and "3.14 kurun" in message
    assert "3.15.0" in message
