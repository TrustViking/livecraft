from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from app.resources import loader
from app.resources.loader import ICON_FILE_NAME, ResourceBundle, ResourceError, TextResource

REPO_TEXT_DIR: Path = Path(loader.__file__).resolve().parent / "text"
SERVICE_HINTS: str = "merge_service_hints.txt"
# Стартовые данные (CLAUDE.md §14 решение 23): меняются только задачей продукта с названной причиной — тогда и здесь.
STARTING_DATA_DIGESTS: dict[str, str] = {
    "canonical_service_lines.json": "b2b5f82762308ad1",
    "language_aliases.txt": "356b90461236788a",
    "language_prefixes.txt": "35dc29fde824e932",
    "lexicon_authoritative_link_hints.txt": "93f1e5f72295d0fe",
    "lexicon_cta_hints.txt": "60a2f00b77f5b753",
    "lexicon_cta_prefix_hints.txt": "308a0dec35b909bf",
    "lexicon_cta_prefixes.txt": "3c847f9aced85bf1",
    "lexicon_official_link_hints.txt": "d000eb4738f32cff",
    "lexicon_semantic_stopwords.txt": "2ffdd0c948e5edc2",
    "merge_agenda_headings.txt": "e4a480c55af14ffd",
    "merge_prompt_source.txt": "30ebc461a47fb03d",
    "merge_service_hints.txt": "aa638ae8aadbd175",
    "openai_prices.json": "ae9529e55b62dbf4",
    "preview_name_latin.json": "b7077d93e214269f",
    "prompt_model_probe.txt": "d423f4b1988fe7f1",
    "sheet_header_date.txt": "159f0557f01d2750",
    "sheet_header_link.txt": "108c3afd6b5212a9",
    "sheet_header_preview.txt": "fd0e0c787ec68df2",
    "sheet_header_time.txt": "abfb210ebb25faa8",
    "ytdlp_private_markers.txt": "ce117f2c87f7fa73",
    "ytdlp_unavailable_markers.txt": "9b92d43d669d53e4",
}


def test_dev_mode_reads_the_folder_next_to_the_module() -> None:
    assert ResourceBundle(frozen=False, bundle_dir=None).text_dir == REPO_TEXT_DIR
    assert TextResource(SERVICE_HINTS).path == REPO_TEXT_DIR / SERVICE_HINTS


def test_frozen_mode_reads_the_pyinstaller_bundle(tmp_path: Path) -> None:
    assert ResourceBundle(frozen=True, bundle_dir=str(tmp_path)).text_dir == tmp_path / "app" / "resources" / "text"


def test_dev_mode_icon_is_the_shipped_ico_with_every_size() -> None:
    """Иконка программы (CLAUDE.md §14 решение 53): одна .ico на exe, ярлыки и окно — все размеры от 16 до 256."""
    icon: Path = ResourceBundle(frozen=False, bundle_dir=None).icon_file
    assert icon == REPO_TEXT_DIR.parent / "icon" / ICON_FILE_NAME
    with Image.open(icon) as image:
        assert sorted(image.info["sizes"]) == [(size, size) for size in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)]


def test_frozen_mode_icon_is_in_the_pyinstaller_bundle(tmp_path: Path) -> None:
    icon: Path = ResourceBundle(frozen=True, bundle_dir=str(tmp_path)).icon_file
    assert icon == tmp_path / "app" / "resources" / "icon" / ICON_FILE_NAME


def test_the_process_is_not_frozen_under_the_tests() -> None:
    assert ResourceBundle.of_process() == ResourceBundle(frozen=False, bundle_dir=None)


def test_service_hints_are_the_starting_lexicon() -> None:
    hints: tuple[str, ...] = TextResource(SERVICE_HINTS).lines
    assert hints[:3] == ("watch", "join", "share")
    assert "подпис" in hints and "залиште" in hints
    assert all(hint == hint.strip() and hint for hint in hints)


def test_lines_skip_blanks_and_comments_and_strip_edges(tmp_path: Path) -> None:
    (tmp_path / "probe_lines.txt").write_text("# комментарий\n\n  один  \r\n#ещё\nдва\n   \n", encoding="utf-8")
    assert TextResource("probe_lines.txt", tmp_path).lines == ("один", "два")


def test_lines_are_read_once_per_name(tmp_path: Path) -> None:
    source: Path = tmp_path / "probe_cache.txt"
    source.write_text("первое\n", encoding="utf-8")
    assert TextResource("probe_cache.txt", tmp_path).lines == ("первое",)
    source.write_text("второе\n", encoding="utf-8")
    assert TextResource("probe_cache.txt", tmp_path).lines == ("первое",)


def test_missing_resource_is_an_error_not_an_empty_lexicon(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _ = TextResource("no_such_resource.txt", tmp_path).lines


def test_body_drops_the_source_line_and_keeps_the_rest_as_is(tmp_path: Path) -> None:
    """Строка-источник «#…» — только первая; дальше текст как есть, с краями и переводами строк."""
    (tmp_path / "probe_body.txt").write_text("# откуда взят текст\n  первая\n\n# не источник\n", encoding="utf-8")
    assert TextResource("probe_body.txt", tmp_path).body == "  первая\n\n# не источник\n"


def test_body_without_a_source_line_is_the_whole_text(tmp_path: Path) -> None:
    (tmp_path / "probe_plain.txt").write_text("Ответь {model_name}\n", encoding="utf-8")
    assert TextResource("probe_plain.txt", tmp_path).body == "Ответь {model_name}\n"


def test_data_reads_the_starting_service_lines() -> None:
    data = TextResource("canonical_service_lines.json").data
    assert list(data) == ["uk", "en", "ru", "other"]
    assert data["ru"]["cta"] == "Смотрите эфир и делитесь мнением."


def test_data_must_be_a_json_object(tmp_path: Path) -> None:
    (tmp_path / "probe_list.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ResourceError):
        _ = TextResource("probe_list.json", tmp_path).data


def test_data_is_read_once_and_read_only(tmp_path: Path) -> None:
    source: Path = tmp_path / "probe_object.json"
    source.write_text('{"a": 1, "2": " x "}', encoding="utf-8")
    data = TextResource("probe_object.json", tmp_path).data
    assert dict(data) == {"a": 1, "2": " x "}
    source.write_text('{"a": 2}', encoding="utf-8")
    assert TextResource("probe_object.json", tmp_path).data["a"] == 1
    with pytest.raises(TypeError):
        data["a"] = 3  # type: ignore[index]


def test_allowed_latin_tokens_are_the_starting_list() -> None:
    """Латинские слова, допустимые в тексте кириллицей, — значения без правки; первая строка файла — комментарий."""
    lines: tuple[str, ...] = TextResource("merge_allowed_latin_tokens.txt").lines
    assert lines == ("ai", "api", "docs", "gpt", "google", "nasa", "openai", "telegram", "youtube")
    first_line: str = TextResource("merge_allowed_latin_tokens.txt").path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#")


def test_starting_data_resources_are_unchanged() -> None:
    """Стартовые данные лежат побайтно такими, какими их приняли: случайная правка лексикона видна сразу."""
    digests: dict[str, str] = {
        name: hashlib.sha256(TextResource(name).path.read_bytes()).hexdigest()[:16] for name in STARTING_DATA_DIGESTS
    }
    assert digests == STARTING_DATA_DIGESTS
