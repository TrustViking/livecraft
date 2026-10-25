"""Файл secrets\\ в токене доступа и учёт полученного с токеном (CLAUDE.md §7.3, §14 решения 65, 67, 70).

`TokenFile` — простое имя и текст файла; отпечаток входа Google — по refresh_token: обновление доступа переписывает
файл входа, а refresh_token остаётся; вход, сделанный самим человеком, получает новый refresh_token — и становится
своим.
`ReceivedFiles` — учёт secrets\\token_received.json: имя и отпечаток каждого файла, полученного с токеном, и ключ и
отпечаток каждой полученной открытой настройки (ссылка на форму, чаты Telegram, контакты документа). В новый токен идёт
только своё — файл или настройка, которых в учёте нет или чей отпечаток с учётом не совпал (значение, которое человек
поменял в окне, — своё); вход Google — только сделанный через выбранный проект (§14 решение 67). Какие значения войдут в
токен, решают ползунки вкладки «Токены» (`TokenScope`).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.core.text_format import TEXT_ENCODING
from app.google.login_file import LoginFile
from app.google.oauth_client import OAuthClient
from app.paths import FileName, LivecraftPaths, write_text_atomically


class TokenFileKey(str, Enum):
    """Поля JSON: учёта полученного и файла входа Google."""

    FILES = "files"
    SETTINGS = "settings"
    REFRESH_TOKEN = "refresh_token"


@dataclass(frozen=True)
class TokenFile:
    """Файл secrets\\ в токене: простое имя и текст."""

    name: str
    text: str

    @classmethod
    def read(cls, path: Path) -> TokenFile:
        return cls(name=path.name, text=path.read_text(encoding=TEXT_ENCODING))

    @property
    def fingerprint(self) -> str:
        """sha256 (hex) refresh_token, если текст — вход Google, иначе sha256 текста. В лог не пишется."""
        source: str = self._refresh_token or self.text
        return hashlib.sha256(source.encode(TEXT_ENCODING)).hexdigest()

    @property
    def _refresh_token(self) -> str | None:
        """refresh_token входа Google; текст — не JSON или поля нет — None."""
        try:
            data: object = json.loads(self.text)
        except ValueError:
            return None
        refresh: object = data.get(TokenFileKey.REFRESH_TOKEN.value) if isinstance(data, dict) else None
        return refresh if isinstance(refresh, str) else None

    def write(self, folder: Path) -> None:
        """Файл в папке `folder` под своим именем — атомарно. Сбой — OSError."""
        write_text_atomically(folder / self.name, self.text, TEXT_ENCODING)


@dataclass(frozen=True)
class ReceivedFiles:
    """Учёт полученного с токеном: файл учёта, отпечатки полученных файлов по имени (`prints`) и отпечатки полученных
    открытых настроек по ключу настройки (`settings`: значение `SettingKey` → sha256 значения)."""

    path: Path
    prints: Mapping[str, str]
    settings: Mapping[str, str]

    @classmethod
    def load(cls, paths: LivecraftPaths) -> ReceivedFiles:
        """Учёт установки; нет файла или не читается — пусто; учёт прежних сборок без настроек — их не получали."""
        path: Path = paths.file(FileName.TOKEN_RECEIVED)
        try:
            raw: object = json.loads(path.read_text(encoding=TEXT_ENCODING))
        except (OSError, ValueError):
            raw = None
        files: dict[str, str] = cls._section(raw, TokenFileKey.FILES)
        return cls(path=path, prints=files, settings=cls._section(raw, TokenFileKey.SETTINGS))

    @classmethod
    def _section(cls, raw: object, key: TokenFileKey) -> dict[str, str]:
        """Раздел учёта `key`: имя → отпечаток; учёт не читается или раздела нет — пусто."""
        section: object = raw.get(key.value) if isinstance(raw, dict) else None
        return {str(name): str(value) for name, value in section.items()} if isinstance(section, dict) else {}

    def is_received(self, file: TokenFile) -> bool:
        """Файл получен с токеном: имя учтено и отпечаток совпал."""
        return self.prints.get(file.name) == file.fingerprint

    def is_received_setting(self, key: str, value: str) -> bool:
        """Открытая настройка `key` получена с токеном: значение не меняли с загрузки — отпечаток совпал."""
        return self.settings.get(key) == self._setting_print(value)

    def own(self, path: Path) -> TokenFile | None:
        """Свой файл: есть на диске и не получен с токеном; иначе None."""
        if not path.is_file():
            return None
        file: TokenFile = TokenFile.read(path)
        return None if self.is_received(file) else file

    def own_login(self, path: Path, project: OAuthClient | None) -> TokenFile | None:
        """Свой вход Google, сделанный через проект `project` (§14 решение 67); иначе, и без проекта, — None."""
        return self.own(path) if project is not None and LoginFile.of(path).is_through(project) else None

    def with_written(self, files: Iterable[TokenFile]) -> ReceivedFiles:
        prints: dict[str, str] = {**self.prints, **{file.name: file.fingerprint for file in files}}
        return ReceivedFiles(path=self.path, prints=prints, settings=self.settings)

    def with_settings(self, values: Mapping[str, str]) -> ReceivedFiles:
        """Учёт, в котором открытые настройки `values` — полученные; полученное заменяет полученное."""
        arrived: dict[str, str] = {key: self._setting_print(value) for key, value in values.items()}
        settings: dict[str, str] = {**self.settings, **arrived}
        return ReceivedFiles(path=self.path, prints=self.prints, settings=settings)

    def save(self) -> None:
        """Учёт — атомарно. Сбой — OSError."""
        data: dict[str, dict[str, str]] = {
            TokenFileKey.FILES.value: dict(self.prints), TokenFileKey.SETTINGS.value: dict(self.settings)
        }
        write_text_atomically(self.path, json.dumps(data, ensure_ascii=False), TEXT_ENCODING)

    def _setting_print(self, value: str) -> str:
        """sha256 (hex) значения открытой настройки. В лог не пишется."""
        return hashlib.sha256(value.encode(TEXT_ENCODING)).hexdigest()
