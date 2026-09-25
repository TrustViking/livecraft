from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from app.resources import loader
from app.resources.loader import TextResource

REPO_TEXT_DIR: Path = Path(loader.__file__).resolve().parent / "text"
SERVICE_HINTS: str = "merge_service_hints.txt"
DONOR_DIGESTS: dict[str, str] = {
    "canonical_service_lines.json": "b2b5f82762308ad1",
    "lexicon_cta_hints.txt": "60a2f00b77f5b753",
    "merge_agenda_headings.txt": "e4a480c55af14ffd",
}


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


# --- 3.11b: объект JSON (донор: resource_loader.py::load_json_resource)
def test_data_reads_the_donor_service_lines() -> None:
    data = TextResource("canonical_service_lines.json").data
    assert list(data) == ["uk", "en", "ru", "other"]
    assert data["ru"]["cta"] == "Смотрите эфир и делитесь мнением."


def test_data_must_be_a_json_object(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    text_dir: Path = TextResource.text_dir()
    text_dir.mkdir(parents=True)
    (text_dir / "probe_list.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        _ = TextResource("probe_list.json").data


def test_data_is_read_once_and_read_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    text_dir: Path = TextResource.text_dir()
    text_dir.mkdir(parents=True)
    source: Path = text_dir / "probe_object.json"
    source.write_text('{"a": 1, "2": " x "}', encoding="utf-8")
    data = TextResource("probe_object.json").data
    assert dict(data) == {"a": 1, "2": " x "}
    source.write_text('{"a": 2}', encoding="utf-8")
    assert TextResource("probe_object.json").data["a"] == 1
    with pytest.raises(TypeError):
        data["a"] = 3  # type: ignore[index]


def test_allowed_latin_tokens_are_the_donor_list() -> None:
    """Донор: quality_diagnostics.py::_ALLOWED_LATIN_SCRIPT_TOKENS — значения без правки."""
    lines: tuple[str, ...] = TextResource("merge_allowed_latin_tokens.txt").lines
    assert lines == ("ai", "api", "docs", "gpt", "google", "nasa", "openai", "telegram", "youtube")
    first_line: str = TextResource("merge_allowed_latin_tokens.txt").path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#") and "restreamer" in first_line


def test_donor_resources_are_copied_byte_for_byte() -> None:
    """Файлы донора: побайтно, контрольные суммы restreamer 35324e5."""
    digests: dict[str, str] = {
        name: hashlib.sha256(TextResource(name).path.read_bytes()).hexdigest()[:16]
        for name in ("canonical_service_lines.json", "lexicon_cta_hints.txt", "merge_agenda_headings.txt")
    }
    assert digests == DONOR_DIGESTS
