"""Поток эфира на площадке: метка программы, адрес и ключ (CLAUDE.md §6 инварианты 1, 6)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StreamInfo:
    """Привязанный поток. Ключ — полностью; вывод его маскирует (`mask_stream_key`)."""

    stream_id: str
    title: str               # метка программы: сюда пишется slot_id
    ingestion_address: str   # stream_url
    stream_name: str         # ключ потока
    description: str = ""    # описание ключа в Студии; в нём — метка заглушки обложки (PlaceholderMark.token)
