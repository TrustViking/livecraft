"""Решение по объекту эфира: какие решения ставят эфир на YouTube и какие действуют на площадке."""
from __future__ import annotations

from app.pipeline.decision import Decision

PUBLISHING: frozenset[Decision] = frozenset({Decision.CREATE, Decision.NO_STREAM})
ACTING: frozenset[Decision] = frozenset({Decision.CREATE, Decision.NO_STREAM, Decision.UPDATE})


def test_only_create_and_no_stream_publish_a_broadcast() -> None:
    """Создать эфир или дать ему поток — запуск ставит эфир на YouTube и берёт его ключ с площадки."""
    assert {decision for decision in Decision if decision.publishes} == PUBLISHING


def test_the_full_run_acts_on_the_platform_by_create_no_stream_and_update() -> None:
    """Совпавший, too_late, неоднозначный, ошибочный и не допущенный эфир площадку не меняют."""
    assert {decision for decision in Decision if decision.acts_on_platform} == ACTING
