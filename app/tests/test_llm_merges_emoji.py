"""Эмодзи описания: счёт вне маркеров пунктов и снятие с сохранением маркеров."""
from __future__ import annotations

from app.llm.merges.description import MergedDescription
from app.llm.merges.emoji import EmojiCleanup, EmojiUsage

NEUTRAL: str = chr(0x1F539)
PIN: str = chr(0x1F4CC)
FIRE: str = chr(0x1F525)


def usage(text: str) -> EmojiUsage:
    return EmojiUsage(MergedDescription(text))


def test_emoji_count_subtracts_every_bullet_marker() -> None:
    text: str = f"{FIRE} Hook {FIRE}\n{NEUTRAL} point\n{PIN} point with {NEUTRAL} inside"
    assert usage(text).count == 2
    assert usage(f"{NEUTRAL} one\n{NEUTRAL} two").count == 0


def test_non_structural_emoji_are_removed_and_markers_kept() -> None:
    text: str = f"{FIRE} Hook {FIRE} , text  here {FIRE}!\n\n  {NEUTRAL} point {FIRE} one\n{PIN} {FIRE}"
    cleanup: EmojiCleanup = usage(text).cleaned()
    assert cleanup.changed
    assert cleanup.description.text == f"Hook, text here!\n\n{NEUTRAL} point one\n{PIN}"   # отступ строки снимается


def test_text_without_emoji_is_unchanged_by_emoji_removal() -> None:
    cleanup: EmojiCleanup = usage("Hook text.  \n\n- plain point").cleaned()
    assert not cleanup.changed
    assert cleanup.description.text == "Hook text.\n\n- plain point"
