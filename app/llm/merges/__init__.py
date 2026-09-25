"""Функция merge (CLAUDE.md §2 строка про llm\\merges\\, §14 решение 23): один запрос к модели на слот.

Поведение и правила — из restreamer как есть, форма — объекты. Первый слой (задача 3.11) — ответ модели:
`answer.py` (`MergeAnswer.parse` — ответ в проверенный объект или отказ), `reject.py` (`MergeReject`, коды
отказа), `layout.py` (`DescriptionLayout` — тело и служебный хвост, восстановление числа абзацев),
`description.py` (`MergedDescription` — повтор абзацев, эхо тезиса и его починка, призыв в начале, починка
смешанного алфавита), `hook.py` (`BadHookLexicon` — негодный первый абзац). Второй слой (задача 3.11b) —
качество описания: `blocks.py` (`DescriptionBlocks` — тезис, пункты, ссылки, призыв; смесь алфавитов),
`service_lines.py` (`ServiceLineCatalog`, `ServiceLanguage` — служебные строки и их язык), `quality.py`
(`QualityRules`, `QualityDiagnostics` — коды причин и статус, шаги нормализации; сама нормализация —
`MergedDescription.quality_normalized`), `agenda.py` (`AgendaLexicon`), `rules.py` (пороги донора). Модель merge
видит только через разъём `app\\llm\\backend.py::LlmBackend`.
"""
