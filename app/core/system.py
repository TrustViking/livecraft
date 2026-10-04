"""Операционная система, на которой идёт программа, — то, что нужно нескольким слоям (CLAUDE.md §11).

DPAPI сейфа, проверка живости процесса-владельца замка и язык интерфейса по языку Windows есть только на Windows: эти
места спрашивают об этом одним значением.
"""
from __future__ import annotations

from typing import Final

WINDOWS_PLATFORM: Final[str] = "win32"     # sys.platform на Windows
