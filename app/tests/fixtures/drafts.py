"""Черновики вкладок настройщика в тестах: черновик модели с полями, которые набрал бы человек."""
from __future__ import annotations

import dataclasses
from typing import TypeVar

DraftT = TypeVar("DraftT")


def draft_with(draft: DraftT, **changes: object) -> DraftT:
    """Тот же черновик с другими полями."""
    return dataclasses.replace(draft, **changes)
