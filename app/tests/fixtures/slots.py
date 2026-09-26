"""Слоты из готовых источников тем же путём, что в прогоне без нейросети: группы → тексты источников → слоты."""
from __future__ import annotations

from collections.abc import Sequence
from zoneinfo import ZoneInfo

from app.intake.builder import SlotBuild, SlotBuilder
from app.sources.video import SourceVideo


def build_slots(videos: Sequence[SourceVideo], zone: ZoneInfo) -> SlotBuild:
    """Слоты источников в зоне программы; тексты — источников по правилам YouTube, как у `PlanIntake`."""
    return SlotBuild.of([group.slot(group.source_texts) for group in SlotBuilder(zone).groups(videos)])
