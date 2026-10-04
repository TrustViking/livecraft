"""Запуск замка: `python -m app.tools.code_standard` из корня репозитория (команды — `command.py`)."""
from __future__ import annotations

import sys

from app.tools.code_standard.command import CommandRequest, StandardCommand
from app.tools.code_standard.locations import LockFiles

if __name__ == "__main__":
    raise SystemExit(StandardCommand(LockFiles.repository(), CommandRequest.parse(sys.argv[1:]), sys.stdout).run())
