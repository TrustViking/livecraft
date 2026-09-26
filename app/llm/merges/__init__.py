"""Функция merge (CLAUDE.md §2 строка про llm\\merges\\, §14 решение 23): один запрос к модели на слот.

Модули снизу вверх. Правила: `rules.py` (все пороги), словари `hook.py` (`BadHookLexicon`), `agenda.py`
(`AgendaLexicon`), `service_lines.py` (`ServiceLineCatalog`, `ServiceLanguage`, `LanguageMatch` — одно правило
«язык явно не тот»), тексты промта `prompt_texts.py` (`MergePromptTexts`, `Placeholder`, `PromptTemplate`), отказ
`reject.py` (`MergeReject`, `MergeRejectCode` и таблица признаков `RejectTraits`). Описание ответа по заботам:
`description.py` (`MergedDescription`), `hook_echo.py` (`HookEcho`, `HookParagraph`), `opening.py`
(`DescriptionOpening`), `emoji.py` (`EmojiUsage`), `script_mix.py` (`ScriptMixProbe`, `HomoglyphRepair`), `blocks.py`
(`DescriptionBlocks`), `layout.py` (`DescriptionLayout`, `TailSplit`, `BodyRecovery`). Все словари и тексты одним
плоским объектом — `merge_rules.py` (`MergeLexicons`, `MergeRules`, `PublishGate`). Над ними: качество `quality.py`
(`QualityNormalization`, `QualityDiagnostics`), ответ `answer.py` (`MergeAnswer.parse`, схема `MergeAnswer.SCHEMA`),
промт — `source.py` (`MergeSource`), `contract.py` (`MergeContract`, `BulletRange`), `retry.py` (`RetryProfile`,
сигналы — по `MergeRejectCode`), `prompt.py` (`MergePrompt`); проверка ответа — `links.py` (`OfficialLinkSelection`),
`check.py` (`MergeCheck`, `FormattingRecovery`); исполнение — `attempt.py` (`MergeAttempt`), `job.py` (`MergeJob`),
`run.py` (`MergeRun`); санация принятого ответа — `publication.py` (`MergePublication`).
Модель merge видит только через разъём `app\\llm\\backend.py::LlmBackend`.
"""
