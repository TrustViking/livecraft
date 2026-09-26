"""Операционная система, на которой идёт программа, — то, что нужно нескольким слоям (CLAUDE.md §11).

DPAPI сейфа и проверка живости процесса-владельца замка есть только на Windows: оба места спрашивают об этом
одним значением.
"""
from __future__ import annotations

from typing import Final

WINDOWS_PLATFORM: Final[str] = "win32"     # sys.platform на Windows
