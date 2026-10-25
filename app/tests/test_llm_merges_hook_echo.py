"""Эхо тезиса: первая строка тела повторяет тезис — находится и чинится; пункт, вклеенный в тезис, выносится."""
from __future__ import annotations

from app.llm.merges.description import MergedDescription
from app.llm.merges.hook_echo import HookEcho, HookParagraph, HookSplit

LONG_HOOK: str = (
    "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours "
    "and why the aid corridor schedule shifts across all active fronts."
)


def echo(text: str) -> bool:
    return HookEcho(MergedDescription(text)).found


def repaired(text: str) -> str | None:
    result: MergedDescription | None = HookEcho(MergedDescription(text)).repaired()
    return None if result is None else result.text


def test_exact_duplicate_hook_is_an_echo() -> None:
    hook: str = "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours."
    assert echo(f"{hook}\n\n{hook}\n\n🔹 New facts appear only here.")


def test_rephrased_hook_in_body_opener_is_an_echo() -> None:
    assert echo(
        "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours and why the aid "
        "corridor schedule shifts.\n\n"
        "The sanctions vote changes transport risk windows in the next 48 hours and shifts the aid corridor schedule, "
        "so we map those operational consequences in detail.\n\n"
        "🔹 Additional source facts start after this line."
    )


def test_different_hook_and_body_is_not_an_echo() -> None:
    assert not echo(
        "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours.\n\n"
        "🔹 Geneva timeline updates with new WHO cargo batches and hospital routing details.\n\n"
        "🔹 Lviv repair crews report transformer queue reductions after midnight."
    )


def test_short_paragraphs_are_skipped() -> None:
    assert not echo("Short opener line.\n\nShort opener line.\n\nAnother short line.")


def test_common_prefix_over_half_is_an_echo() -> None:
    hook: str = "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours."
    body_opener: str = hook[: int(len(hook) * 0.55)] + " — additional context that makes this paragraph long enough to pass the 40-char gate."
    assert echo(f"{hook}\n\n{body_opener}\n\n🔹 Some new bullet fact here.")


def test_last_sentence_echo_in_body_opener() -> None:
    assert echo(
        "«Він робив нам уколи і прикасався до нас» — 32 жертви Якуба Яхла вперше дають свідчення на камеру. "
        "⚖ Центральний конфлікт — безпека дітей і питання відповідальності.\n\n"
        "⚖ Центральний конфлікт — безпека дітей і питання відповідальності.\n"
        "🔹 Юридичне оновлення у справі.\n🔹 Свідчення дітей та міжнародний тиск.\n\n"
        "Дивіться ефір і діліться думками."
    )


def test_hook_thesis_not_repeated() -> None:
    assert not echo(
        "«Він робив нам уколи і прикасався до нас» — 32 жертви Якуба Яхла вперше дають свідчення на камеру. "
        "⚖ Центральний конфлікт — безпека дітей і питання відповідальності.\n\n"
        "🔹 Юридичне оновлення: суд визнав докази неналежними.\n🔹 Свідчення дітей та міжнародний тиск.\n\n"
        "Дивіться ефір і діліться думками."
    )


def test_repair_removes_echo_paragraph_and_preserves_bullets() -> None:
    result: str | None = repaired(f"{LONG_HOOK}\n\n{LONG_HOOK}\n\n🔹 Geneva timeline updated.\n🔹 Lviv repair crews active.")
    assert result is not None
    assert result.startswith(LONG_HOOK)
    assert "🔹 Geneva timeline updated." in result
    assert len(result.split("\n\n")) == 2


def test_repair_trims_echo_prefix_within_paragraph() -> None:
    echo_with_bullets: str = f"{LONG_HOOK}\n🔹 New cargo batch update.\n🔹 Hospital routing adjusted."
    result: str | None = repaired(f"{LONG_HOOK}\n\n{echo_with_bullets}\n\nSubscribe for more updates.")
    assert result is not None
    assert "🔹 New cargo batch update." in result
    assert f"{LONG_HOOK}\n🔹" not in result


def test_repair_returns_none_when_no_bullets_after_echo() -> None:
    prose: str = "This is another prose paragraph with no bullet markers at all in it anywhere."
    assert repaired(f"{LONG_HOOK}\n\n{LONG_HOOK}\n\n{prose}") is None


def test_repair_returns_none_for_short_description() -> None:
    assert repaired(f"{LONG_HOOK}\n\n{LONG_HOOK}") is None


def test_repair_handles_compact_two_paragraph_echo() -> None:
    first_bullet: str = "🔹 Geneva timeline updated with new WHO cargo batches and routing details."
    echo_with_bullets: str = f"{LONG_HOOK}\n{first_bullet}\n🔹 Lviv repair crews report transformer queue reductions after midnight."
    result: str | None = repaired(f"{LONG_HOOK}\n\n{echo_with_bullets}")
    assert result is not None
    assert not echo(result)
    assert result.count(first_bullet) == 1


def test_repair_handles_bullet_fused_into_hook() -> None:
    hook_clean: str = "«Он делал нам уколы и прикасался к нам» — свидетельства жертв Якуба Яхла становятся срочными."
    fused_bullet: str = "🔹 Встреча с послом Лазаро Ньяланду обсуждает обвинения"
    echo_body: str = (
        f"{hook_clean}\n{fused_bullet}\n"
        "🔹 По имеющимся данным, расследование расширяется на другие страны.\n"
        "📌 Сообщение со встречи дипломатического корпуса."
    )
    result: str | None = repaired(f"{hook_clean} {fused_bullet}\n\n{echo_body}\n\n#Танзания #ЯкубЯхл")
    assert result is not None
    assert not echo(result)
    assert result.count("🔹 Встреча с послом Лазаро Ньяланду") == 1
    assert "🔹 По имеющимся данным" in result
    assert "📌 Сообщение со встречи" in result


def test_repair_compact_two_paragraphs_without_bullets_returns_none() -> None:
    prose_echo: str = (
        f"{LONG_HOOK} — this is a prose restatement of the hook without any bullet markers "
        "and without any new facts or additional content that would allow repair."
    )
    assert repaired(f"{LONG_HOOK}\n\n{prose_echo}") is None


def test_repair_preserves_bullets_in_echo_paragraph_and_later_paragraphs() -> None:
    echo_with_bullets: str = f"{LONG_HOOK}\n🔹 Bullet from echo paragraph.\n🔹 Second bullet from echo paragraph."
    later: str = "🔹 Bullet from paragraph three.\n🔹 Another later fact."
    result: str | None = repaired(f"{LONG_HOOK}\n\n{echo_with_bullets}\n\n{later}")
    assert result is not None
    assert "🔹 Bullet from echo paragraph." in result
    assert "🔹 Bullet from paragraph three." in result


def test_no_echo_means_no_repair() -> None:
    assert repaired("First paragraph that is long enough to be checked by the rule.\n\n🔹 Different fact entirely here now.") is None


# --- вклеенный в тезис пункт
def test_hook_paragraph_multiline_split() -> None:
    assert HookParagraph("Hook line.\nmore\n🔹 bullet").split_trailing_bullet() == HookSplit("Hook line.\nmore", "🔹 bullet")
    assert HookParagraph("Hook line.\nmore").split_trailing_bullet() == HookSplit("Hook line.\nmore", None)


def test_hook_paragraph_single_line_split_needs_a_sentence_end_after_the_40th_char() -> None:
    long_sentence: str = "This hook sentence is definitely longer than forty chars."
    assert HookParagraph(f"{long_sentence} 🔹 fused").split_trailing_bullet() == HookSplit(long_sentence, "🔹 fused")
    assert HookParagraph("Short. 🔹 fused").split_trailing_bullet() == HookSplit("Short. 🔹 fused", None)
    assert HookParagraph(f"{long_sentence} word 🔹 fused").split_trailing_bullet().bullet is None
