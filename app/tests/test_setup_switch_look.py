"""Вид ползунка «да / нет» без Tk (app\\setup\\fields\\switch_look.py; CLAUDE.md §14 решение 37): цвета и положение
бегунка во всех состояниях, размеры по масштабу экрана."""
from __future__ import annotations

import pytest

from app.setup.fields.switch_look import SLIDE_FRAMES, SwitchBox, SwitchLook
from app.setup.tabs.tab_theme import SWITCH_FOCUS_RING, WINDOW_BACKGROUND, RgbColor

ON: SwitchLook = SwitchLook.of(True, 1.0, WINDOW_BACKGROUND)
OFF: SwitchLook = SwitchLook.of(False, 1.0, WINDOW_BACKGROUND)


def test_at_100_percent_the_track_is_34_by_20_with_a_ring_margin_around() -> None:
    """Дорожка — две трети прежних 51×31 (смотр окна 29-09-2026: ползунок был крупным); рамка фокуса вокруг — 2."""
    assert (ON.track.right - ON.track.left, ON.track.bottom - ON.track.top) == (34, 20)
    assert ON.canvas == SwitchBox(0, 0, 38, 24) and ON.track == SwitchBox(2, 2, 36, 22)


def test_the_size_follows_the_screen_scale() -> None:
    look: SwitchLook = SwitchLook.of(True, 1.5, WINDOW_BACKGROUND)
    assert (look.track.right - look.track.left, look.track.bottom - look.track.top) == (51, 30)


def test_on_is_green_with_the_knob_on_the_right() -> None:
    assert (ON.track_color, ON.border_color, ON.knob_color) == ("#34c759", "#34c759", "#ffffff")
    assert ON.knob == SwitchBox(18, 4, 34, 20)          # белый круг 16 с отступом 2 справа
    assert ON.shadow == SwitchBox(18, 5, 34, 21)


def test_off_is_pale_white_with_a_thin_border_and_the_knob_on_the_left() -> None:
    assert (OFF.track_color, OFF.border_color) == ("#e9e9eb", "#d1d1d6")
    assert OFF.knob == SwitchBox(4, 4, 20, 20)


def test_a_disabled_switch_mixes_its_colours_with_the_window_half_way() -> None:
    disabled: SwitchLook = SwitchLook(is_on=True, position=1.0, is_enabled=False, background="#000000")
    assert disabled.track_color == RgbColor.of("#34c759").mixed(RgbColor.of("#000000"), 0.5).text == "#1a642c"
    assert disabled.knob_color == "#808080"
    assert disabled.knob == ON.knob                      # положение то же


def test_the_focus_ring_has_the_theme_colour_only_in_focus() -> None:
    assert ON.ring_color == WINDOW_BACKGROUND
    assert SwitchLook(is_on=True, position=1.0, has_focus=True).ring_color == SWITCH_FOCUS_RING


def test_the_knob_slides_step_by_step_and_stops_at_its_place() -> None:
    """Включили: бегунок едет вправо на шаг за кадр (весь путь — около 150 мс) и останавливается; цвет дорожки идёт
    от бледного к зелёному по тому же положению."""
    look: SwitchLook = SwitchLook(is_on=True, position=0.0)
    lefts: list[int] = []
    while (stepped := look.stepped()) != look:
        look = stepped
        lefts.append(look.knob.left)
    assert lefts == sorted(lefts) and lefts[-1] == ON.knob.left
    assert len(lefts) == SLIDE_FRAMES == 10
    half: SwitchLook = SwitchLook(is_on=True, position=0.5)
    assert half.track_color == RgbColor.of("#e9e9eb").mixed(RgbColor.of("#34c759"), 0.5).text
    assert SwitchLook(is_on=False, position=0.05).stepped().position == 0.0


@pytest.mark.parametrize(("text", "channels"), [("#34c759", (52, 199, 89)), ("#ffffff", (255, 255, 255))])
def test_a_colour_reads_and_writes_the_tk_notation(text: str, channels: tuple[int, ...]) -> None:
    color: RgbColor = RgbColor.of(text)
    assert color.channels == channels and color.text == text
