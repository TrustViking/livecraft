"""Файл входа Google и проект, через который вход сделан (CLAUDE.md §9, §14 решение 67).

Файл входа — `secrets\\sheets.token.json` оператора или `secrets\\<ник>.token.json` канала — пишет google-auth
(`Credentials.to_json`); в нём лежит id клиента Google, через который вошли. Программа работает только через выбранный
проект: вход, сделанный через другой, — как входа нет. `LoginFile` — единственное чтение id клиента из файла входа:
его берут вход в Google, строки проекта в окне и токен доступа.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.text_format import TEXT_ENCODING
from app.google.oauth_client import ClientKey, OAuthClient


@dataclass(frozen=True)
class LoginFile:
    """Файл входа Google (`path`) и id клиента, через который вошли (`client_id`; файла нет, он не JSON или поля
    нет — None)."""

    path: Path
    client_id: str | None

    @classmethod
    def of(cls, path: Path) -> LoginFile:
        if not path.is_file():
            return cls(path=path, client_id=None)
        try:
            data: object = json.loads(path.read_text(encoding=TEXT_ENCODING))
        except ValueError:
            return cls(path=path, client_id=None)
        client_id: object = data.get(ClientKey.CLIENT_ID.value) if isinstance(data, dict) else None
        return cls(path=path, client_id=client_id if isinstance(client_id, str) and client_id else None)

    @property
    def exists(self) -> bool:
        """Вход есть: файл с id клиента."""
        return self.client_id is not None

    def is_through(self, client: OAuthClient) -> bool:
        """Вход сделан через проект `client`."""
        return self.client_id == client.client_id
