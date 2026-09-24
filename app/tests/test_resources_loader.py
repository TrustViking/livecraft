from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.resources import loader
from app.resources.loader import TextResource

REPO_TEXT_DIR: Path = Path(loader.__file__).resolve().parent / "text"
SERVICE_HINTS: str = "merge_service_hints.txt"


def test_dev_mode_reads_the_folder_next_to_the_module() -> None:
    assert TextResource.text_dir() == REPO_TEXT_DIR
    assert TextResource(SERVICE_HINTS).path == REPO_TEXT_DIR / SERVICE_HINTS


def test_frozen_mode_reads_the_pyinstaller_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert TextResource.text_dir() == tmp_path / "app" / "resources" / "text"


def test_service_hints_are_the_donor_lexicon() -> None:
    hints: tuple[str, ...] = TextResource(SERVICE_HINTS).lines
    assert hints[:3] == ("watch", "join", "share")
    assert "подпис" in hints and "залиште" in hints
    assert all(hint == hint.strip() and hint for hint in hints)


def test_lines_skip_blanks_and_comments_and_strip_edges(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    text_dir: Path = TextResource.text_dir()
    text_dir.mkdir(parents=True)
    (text_dir / "probe_lines.txt").write_text("# комментарий\n\n  один  \r\n#ещё\nдва\n   \n", encoding="utf-8")
    assert TextResource("probe_lines.txt").lines == ("один", "два")


def test_lines_are_read_once_per_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    text_dir: Path = TextResource.text_dir()
    text_dir.mkdir(parents=True)
    source: Path = text_dir / "probe_cache.txt"
    source.write_text("первое\n", encoding="utf-8")
    assert TextResource("probe_cache.txt").lines == ("первое",)
    source.write_text("второе\n", encoding="utf-8")
    assert TextResource("probe_cache.txt").lines == ("первое",)


def test_missing_resource_is_an_error_not_an_empty_lexicon(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(FileNotFoundError):
        _ = TextResource("no_such_resource.txt").lines
