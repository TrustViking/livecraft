from __future__ import annotations

from app.core.errors import os_error_reason


def test_the_reason_is_the_text_of_the_system() -> None:
    assert os_error_reason(PermissionError(13, "Access is denied")) == "Access is denied"


def test_without_a_system_text_the_reason_is_the_name_of_the_error() -> None:
    assert os_error_reason(FileNotFoundError()) == "FileNotFoundError"
    assert os_error_reason(OSError("no errno")) == "OSError"
