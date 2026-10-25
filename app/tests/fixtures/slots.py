"""Слоты из готовых источников тем же путём, что в прогоне с нейросетью без ответов модели: группы → тексты источников
(merge не нужен — тексты видео по правилам YouTube, нужен — «по номерам», отказ merge) → слоты."""
from __future__ import annotations

from collections.abc import Sequence
from zoneinfo import ZoneInfo

from app.intake.builder import SlotBuild, SlotBuilder
from app.sources.video import SourceVideo


def build_slots(videos: Sequence[SourceVideo], zone: ZoneInfo) -> SlotBuild:
    """Слоты источников в зоне программы; тексты — правилом группы без ответа модели (`video_texts`), стадия merge
    шла."""
    return SlotBuild.of([group.slot(group.video_texts) for group in SlotBuilder(zone).groups(videos)], True)
