"""Функция merge (CLAUDE.md §2 строка про llm\\merges\\, §14 решение 23): один запрос к модели на слот.

Поведение и правила — из restreamer как есть, форма — объекты. Первый слой (задача 3.11) — ответ модели:
`answer.py` (`MergeAnswer.parse` — ответ в проверенный объект или отказ), `reject.py` (`MergeReject`, коды
отказа), `layout.py` (`DescriptionLayout` — тело и служебный хвост, восстановление числа абзацев),
`description.py` (`MergedDescription` — повтор абзацев, эхо тезиса и его починка, призыв в начале, починка
смешанного алфавита), `hook.py` (`BadHookLexicon` — негодный первый абзац). Второй слой (задача 3.11b) —
качество описания: `blocks.py` (`DescriptionBlocks` — тезис, пункты, ссылки, призыв; смесь алфавитов),
`service_lines.py` (`ServiceLineCatalog`, `ServiceLanguage` — служебные строки и их язык), `quality.py`
(`QualityRules`, `QualityDiagnostics` — коды причин и статус, шаги нормализации; сама нормализация —
`MergedDescription.quality_normalized`), `agenda.py` (`AgendaLexicon`), `rules.py` (пороги донора). Третий слой
(задача 3.12) — промт: `prompt_texts.py` (`MergePromptTexts` — боевые шаблоны донора и встроенные тексты ресурсами),
`source.py` (`MergeSource`, `PreparedSourceDescription` — источник и его очищенное описание), `contract.py`
(`MergeContract` — compact / expanded / narrative, предел абзацев тела), `retry.py` (`RetryProfile` — инструкция
повтора по сигналу отказа), `prompt.py` (`MergePrompt` — текст промта; меньше двух источников — `MergePromptRefusal`).
Четвёртый слой (задача 3.12b) — проверка ответа: `links.py` (`OfficialLinkSelection` — официальные ссылки источников),
`check.py` (`MergeDiagnostics` — диагностика стиля и строки лога, `MergeCheck` — проверка покрытия в порядке донора,
`FormattingRecovery` — снятие лишних эмодзи и повторная проверка); правила над текстом ответа — `MergedDescription`.
Пятый слой (задача 3.13) — исполнение: `attempt.py` (`MergeAttempt` — одна попытка от запроса до проверки, итог
`MergeAttemptResult` сам выбирает профиль повтора; `MergeRules` — правила merge одним объектом на запуск; схема ответа
`MERGE_RESPONSE_SCHEMA`), `job.py` (`MergeJob` — merge слота с повторами, итог `MergeOutcome`: тексты модели или
источников), `run.py` (`MergeRun` — нейросеть, модель, настройки, счётчики `MergeTally` и остановка по квоте или настройке).
Шестой слой (задача 3.14) — санация принятого ответа: `publication.py` (`SanitizedDescription` — хвост, ссылки, призыв;
`PublishGate` — проверка перед публикацией; `MergePublication` — окончательные название и описание слота или блок),
`links.py::AuthoritativeLinks` — официальные ссылки описания из источников и хвоста ответа.
Модель merge видит только через разъём `app\\llm\\backend.py::LlmBackend`.
"""
