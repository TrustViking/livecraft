"""Формы ключей одного запуска (CLAUDE.md §3 шаги 7, 9; §13 задача 5.1).

Одно чтение на уникальную ссылку за запуск: слоты режима А и пакеты режима Б с той же ссылкой получают ту же
прочитанную форму (пакет — со своими названиями вопросов и вариантами, `KeyForm.for_settings`). Не прочиталась —
тот же отказ каждому, кто спросит, без второго чтения. Прочиталась — строка `form_ready`, нет — `form_unreadable`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config.settings import FormSettings
from app.core.clock import Clock
from app.form.diagnostic import FormDiagnostic
from app.form.failure import FormEvent, FormFailure
from app.form.key_form import KeyForm
from app.form.reader import FormReader
from app.form.sender import FormSender
from app.form.structure import FormStructure
from app.form.transport import FormHttp
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import LivecraftPaths

LOGGER = get_logger(LogArea.FORM)


@dataclass
class FormBook:
    """Формы запуска по ссылке: прочитанная форма или отказ чтения."""

    reader: FormReader
    forms: dict[str, KeyForm | FormFailure] = field(default_factory=dict)

    @classmethod
    def for_run(cls, paths: LivecraftPaths, clock: Clock) -> FormBook:
        """Формы запуска на одной сессии requests; страницы для разбора — в logs\\ по часам программы."""
        return cls(reader=FormReader(http=FormHttp.session(), diagnostic=FormDiagnostic(paths.logs_dir, clock)))

    @property
    def sender(self) -> FormSender:
        """Отправитель ответов той же сессией, что читала формы: cookies чтения и отправки общие."""
        return FormSender(http=self.reader.http, diagnostic=self.reader.diagnostic)

    def form_for(self, settings: FormSettings) -> KeyForm | FormFailure:
        """Форма по настройкам: первое обращение к ссылке читает форму, следующие берут прочитанное."""
        known: KeyForm | FormFailure | None = self.forms.get(settings.url)
        if known is None:
            known = self._read(settings)
            self.forms[settings.url] = known
        if isinstance(known, FormFailure) or known.settings == settings:
            return known
        return known.for_settings(settings)

    def _read(self, settings: FormSettings) -> KeyForm | FormFailure:
        structure: FormStructure | FormFailure = self.reader.read(settings.url)
        if isinstance(structure, FormFailure):
            unreadable: LogEvent = structure.event(FormEvent.UNREADABLE).extended(url=settings.url)
            unreadable.emit(LOGGER, logging.WARNING)
            return structure
        form: KeyForm = KeyForm.build(settings, structure)
        form.ready_event.emit(LOGGER)
        return form
