# REFACTORING_STANDARD.md — эталон кода livecraft и исполнение этапа R

Составил Claude (ведущий программист проекта) 25-09-2026 по снимку кода `50b4217` (ветка `feature/livecraft`, после 3.14c) из архива Артура, вместе с `REFACTORING.md` и `CLAUDE.md` того же дня. Факты сверены Коворком с кодом `50b4217` в тот же день разбором ast на машине Артура; неточности исправлены по месту, сводка исправлений — раздел 12.

**Место среди документов.**
- `CLAUDE.md` задаёт требования к коду и продукту; при любом расхождении прав он.
- `REFACTORING.md` содержит разбор по областям и целевые объекты. Он остаётся в силе, кроме поправок раздела 7 этого файла.
- Этот файл исполнительный. Он определяет «эталон» измеримыми правилами, описывает замок, который держит эти правила автоматически, перечисляет находки сверх `REFACTORING.md`, задаёт состав и порядок задач этапа R, порядок работы Коворка и Codex и содержит готовый промт на первую задачу замка. В составе и порядке задач R прав этот файл.

**Обозначения.** Знак ✔ означает: проверено по коду снимка разбором синтаксиса (ast) и чтением. Числа даны на дату снимка; перед промтом каждая задача перепроверяет их по текущему коду.

---

## 0. Что Коворк делает с этим файлом сразу

1. Кладёт файл в корень репозитория: `D:\_projects\livecraft\REFACTORING_STANDARD.md`.
   - Коммитит его тем же способом, что `CLAUDE.md`, когда Codex не работает.
   - В `CLAUDE.md` §16 добавляет строку: «этап R ведётся по `REFACTORING.md` с поправками и порядком `REFACTORING_STANDARD.md`».
2. Принимает R1.1 (промт уже выдан) обычным порядком.
3. Выдаёт R2.1a. Промт — в разделе 11; перед выдачей Коворк сверяет его факты с кодом после R1.1.
4. Дальше ведёт этап по разделу 8. Каждый промт задачи R получает раздел «ДОЛГИ К СНЯТИЮ» и блок «ПРАВИЛА ЭТАПА R» (раздел 9).

---

## 1. Итог

- **План `REFACTORING.md` верен по существу.** Его цифры подтверждены независимым разбором (раздел 3).
- **Прошлый рефакторинг не дошёл до цели, потому что «эталон» не был определён измеримо и ничем не удерживался.** Поэтому эталон теперь — 21 правило с точным способом замера (раздел 5). Их держит замок: инструмент и тест с реестром долгов, который может только сокращаться (раздел 6). Реестр должен дойти до нуля; после этого замок остаётся навсегда.
- **Найдено 15 проблем сверх `REFACTORING.md`** (раздел 4). Среди них:
  - дефект D8: отметки времени в именах логов и в замке считаются по поясу машины, это расходится с инвариантом 4;
  - противоречие плана с правилом ООП о `Protocol` (N15).
- **Задачи порезаны до размера не больше M:** 42 задачи вместо 25. Каждая закрывается за один проход Codex.
  - Замок идёт сразу после R1.1.
  - `LogEvent` появляется в начале этапа, а не в конце.
- **Решений Артура план не требует** (раздел 10).

---

## 2. Почему прошлый рефакторинг не дошёл до цели

1. **Эталон описан словами, а не замерами.** Слова «методы ~30 строк», «никакого хардкода», «общее — в один объект» Codex и приёмка понимают по-разному. «Сделано» нельзя было проверить одной командой.
2. **Замеры жили вне репозитория.** Скрипт `_an/metrics.py` лежал в песочнице Коворка. Codex не мог его запустить, и тест не мог сделать его условием.
3. **Не было храповика.** Ничто не мешало следующей задаче завести новую копию `LOGGER_NAME`, новую `_flag`, новый шаблон `\s+`. Так и набралось 35 объявлений логгера и 13 копий шаблона пробелов.
4. **Перенос шёл «по месту».** Каждый модуль переводился в объекты сам по себе. В промтах не было требования искать повтор за пределами своего модуля, поэтому общее не собиралось.
5. **Крупные задачи.** Задачу объёма L Codex закрывает частично, а остаток расползается по следующим задачам.

Ответы: на пункты 1–3 — разделы 5 и 6; на пункт 4 — правила E8, E9, E11 и раздел «ДОЛГИ К СНЯТИЮ»; на пункт 5 — раздел 8.

---

## 3. Сверка `REFACTORING.md` с кодом

| Показатель | `REFACTORING.md` | Сверка ✔ | Примечание |
|---|---|---|---|
| Модули кода / строки | 112 / 18 060 | 112 / 18 060 | |
| Свободные функции (публичные) | 163 (94) | 163 (94) | |
| Объявления имени логгера | 35 | 35 вызовов `get_logger` | |
| Одинаковые регулярки | 9 шаблонов / 31 объявление | 9 / 31 | внутри функций не компилируется ни одна ✔ |
| Определения длиннее 30 строк | 9 | 9 | счёт от `def` до последней строки с докстрокой; так закрепляется в E3 |
| Разнотипные кортежи-результаты | 16 | 16 | из них 2 — ключи сортировки (исключения E13); долг 14 |
| `str(x or "")` | 88 (над `str`) | 97 синтаксически | замок считает синтаксически; границы задаются списком модулей (E15) |
| `"\n"` / `"\n\n"` / `","` | 16 / 12 / 16 | 16 / 12 / 16 | |
| `"none"` / `"-"` / `yes`–`no` | 11 / 12 / 6 пар | 11 / 12 / 6 | |
| `"utf-8"` константой | 10 | 10 | |

**Что уже хорошо (подтверждаю ✔):**
- 166 неизменяемых dataclass против 10 изменяемых;
- 47 перечислений;
- нет класса, состоящего из одних статических методов;
- в `app\ui\messages_ru.py` 222 имени, ни одного неиспользуемого; повтор текста один — «нет» под четырьмя именами (`READINESS_FIELD_ABSENT`, `SOURCE_PROBE_NONE`, `LLM_PROBE_NO_FALLBACK`, `LLM_PROBE_NONE`), это `NONE_TEXT` из `REFACTORING.md` 4.7 (R3.5b);
- чисел в телах функций всего 20, и 16 из них — двойка.

---

## 4. Находки сверх `REFACTORING.md`

**N1 ✔ Хардкод в телах функций.**
- В телах функций 1027 непустых строковых литералов (в 76 модулях) и 20 чисел. Из строк:
  - около 510 — куски строк лога;
  - около 289 — идентификаторы (ключи JSON, поля ответов, имена событий);
  - около 122 — разделители;
  - около 30 — английский текст;
  - остальное — имена файлов в `app\paths.py` и части шаблонов.
- Больше всего литералов в модулях:

  | Модуль | Литералов |
  |---|---|
  | `app\config\loader.py` | 72 |
  | `app\llm\merges\job.py` | 53 |
  | `app\llm\backends\openai.py` | 51 |
  | `app\llm\merges\publication.py` | 48 |
  | `app\llm\merges\check.py` | 47 |
  | `app\main.py` | 47 |
  | `app\secretsafe\crypto.py` | 39 |
  | `app\sources\metadata.py` | 35 |
  | `app\sources\language.py` | 28 |
  | `app\packages\package.py` | 25 |
  | `app\paths.py` | 25 |

- В таблице показателей `REFACTORING.md` этого пункта нет. Правило E5; чинится в каждой задаче, остатки — R8.1 и R8.2.

**N2 ✔ Кириллица в строках кода вне `messages_ru`: 46 литералов в 8 модулях.**
- `app\llm\merges\description.py` — 27: карта омоглифов, классы букв, шаблон имён.
- `app\texts\description_marks.py` — 7.
- `app\sheets\plan.py` — 4.
- `app\llm\merges\blocks.py` — 2.
- `app\llm\merges\service_lines.py:41-42` — 2 (`[іїєґ]`, `[ыэъ]`).
- `app\setup\fields\language_choice.py:28` — 2: свёртка «ё → е». В плане этого нет.
- `app\core\sheet_text.py:38` — 1: `[^a-zа-я0-9]+`.
- `app\texts\analysis_text.py:20` — 1.

Класс кириллицы нужен и в `core`, а `core` не может импортировать `texts`. Поэтому алфавит живёт в `app\core\alphabet.py`, а не в `app\texts\` (поправка П1). Правило E6; задачи R3.2b и R3.6.

**N3 ✔ 35 свободных функций обслуживают ровно один класс своего модуля.** По §0 это методы этого класса или, если правило повторяется, общий примитив. Правило E1(б).
- `app\main.py::_quoted` → `RunRequest`.
- `app\config\loader.py`: `normalize_account_name`, `handle_problem`, `account_name_problem`, `_is_google_account`, `_is_language_code` → `_ConfigParser`.
- `app\sources\metadata.py`: `_optional_text`, `_keys` → `SourceMetadata`.
- `app\texts\tail.py`: `merge_hashtag_lines`, `dedupe_cta_lines` → `TailFragments`.
- `app\texts\description_marks.py`: `starts_with_cta_prefix`, `_hint_pattern` → `CtaLexicon`.
- `app\texts\official_links.py::official_link_urls` → `OfficialLinksBlocks`.
- `app\texts\analysis_text.py::_tidy` → `_CleanedParagraph`.
- `app\llm\merges\contract.py`: `capitalized_runs` → `SourceTextSet`; `_expanded_bullet_range`, `_range_label` → `MergeContract`.
- `app\llm\merges\description.py`: `_semantic_token_set`, `_without_emoji_in_line`, `_lines_repeat` → `MergedDescription`.
- `app\llm\merges\prompt.py::language_full_name` → `MergePrompt`.
- `app\llm\merges\quality.py::_core_language_mismatch` → `QualityDiagnostics`.
- `app\llm\merges\retry.py::_unique_in_order` → `RetryProfile`.
- `app\llm\merges\blocks.py`: `_script_mix_probe_text`, `_is_suspicious_token` → `DescriptionBlocks`.
- `app\llm\merges\attempt.py::_bullet_line_count` → `MergeAttempt` (мёртвый код, R1.2).
- `app\llm\backends\openai_response.py::_int_field` → `OpenAiUsage`.
- `app\llm\backends\openai_errors.py::_text_attr` → `OpenAiFailure`.
- `app\llm\backends\openai_rate_limits.py`: `parse_reset_seconds`, `_header_items` → `RateLimitSnapshot`.
- `app\llm\merges\attempt.py::_flag` → `MergeAttemptResult`, `app\llm\merges\check.py::_flag` → `MergeDiagnostics` (обе уходят в словарь значений лога, R3.1).
- `app\llm\merges\blocks.py::_lines` → `_BlocksBuilder` (копия `nonempty_lines`, R3.2a).
- `app\tools\source_probe.py`: `_languages`, `_duration` → `SourceProbeReport`.

**N4 ✔ 59 статических методов в 40 классах.** Это свободные функции, спрятанные в класс. Часть из них — копии общих примитивов:

| Копии | Общий примитив |
|---|---|
| `LanguageProfile._unique`, `retry.py::_unique_in_order`, `url_text.py::dedupe_nonempty` и 6 выражений `dict.fromkeys` (`check.py`, `retry.py`, `sources\language.py`, `setup\fields\language_choice.py`) | `unique_in_order` |
| `blocks.py::_collapse` (`DescriptionLayout._collapse` — не копия: сливает лишние абзацы тела) | `collapse_spaces` |
| `OfficialLinksBlocks._nonempty_lines`, `TailBlock._lines`, `blocks.py::_lines` | `nonempty_lines` |
| `TailBlock._is_hashtags` | `is_hashtags_line` |
| `VaultFile._decode_wrapped_key`, `VaultFile._decode_salt`, `EncryptedField._decode` | `Base64Field` |
| `SanitizedDescription._is_bullet` | `BulletLine` |

Больше всего статических методов в `SourceMetadata`, `LanguageProfile`, `DescriptionLayout` и `ServiceLanguage` — по 3. Правило E2.

**N5 ✔ Шестое нарушение слоёв, кольцо observability ↔ secretsafe.**
- `app\observability\logging_setup.py:27-28` под `TYPE_CHECKING` импортирует `app.secretsafe.value.SecretValue` и `app.secretsafe.vault.Vault` ради `install_secret_filter(vault)` (строка 153).
- Пакет `secretsafe` при этом сам пишет лог через `get_logger`.
- Исправление в R4.1a: фильтр строит сейф (`Vault.log_filter() -> logging.Filter`), а `RunLog.protect` принимает любой `logging.Filter`.

**N6 ✔ «Сейчас» берётся в 11 местах, разными способами.**
- `app\main.py:151,243`;
- `app\runtime\single_instance.py:215,253`;
- `app\observability\logging_setup.py:52`;
- `app\core\dates.py:60`;
- `app\llm\backends\openai.py:159` (`time.monotonic`);
- `app\llm\backends\openai_rate_limits.py:64,95` (`time.time`);
- `app\tools\sheets_probe.py:178`;
- `app\tools\llm_probe.py:125`.

Из них вытекает **дефект D8**. Имя файла лога (`logging_setup.py:52`), время в замке и в `startup.log` (`single_instance.py:215,253`) и `format_now_local` берут пояс машины (`datetime.now().astimezone()`). Инвариант 4 требует киевского времени во всех файлах и именах; на машине в другом поясе имена логов разойдутся с отчётом.

Исправление в R3.7: один объект `app\core\clock.py::Clock`. Отметки считаются по поясу программы. До чтения настроек это пояс поставочного шаблона (`ShippedSettings`), после — `LivecraftSettings.zone`. Правило E17.

**N7 ✔ Проверка «время с поясом» написана 4 раза, с тремя разными английскими текстами.**
- `app\packages\package.py:113`;
- `app\slots\intake.py:68`;
- `app\sheets\plan.py:61`;
- `app\core\dates.py:53`;
- плюс родственная `app\core\sheet_text.py:94-96`.

Исправление в R3.7: одна `require_aware` в `app\core\dates.py` с одним текстом.

**N8 ✔ Константы-копии, которых нет в плане.**

| Константа | Где | Что делать |
|---|---|---|
| `COST_FORMAT = "{:.6f}"` | `llm\backends\openai.py`, `llm\usage.py`, `tools\llm_probe.py` | одна константа |
| `STAGE_PRIMARY` | `llm\merges\attempt.py`, `job.py` | одна константа |
| `LAYOUT_EMPTY` | `llm\merges\publication.py`, `texts\composer.py` | одна константа |
| `DETAIL_MAX_CHARS = 200` | `llm\merges\reject.py`, `sources\ytdlp.py` | одна «обрезка подробности для лога» |
| `LINK_EDGE_CHARS` / `URL_EDGE_CHARS` и `LINK_TRAILING_PUNCTUATION` / `URL_TRAILING_PUNCTUATION` | `core\url_text.py`, `texts\tail.py` | уходят в `WebLink` |
| `ISO_TIMESPEC` / `UTC_TIMESPEC` | `slots\slot.py`, `tools\llm_probe.py` | в `core\dates.py` |
| `"unknown"` (7 объявлений) | `openai.py`, `openai_rate_limits.py`, `usage.py`, `retry.py` ×2, `service_lines.py`, `sources\language.py` | логовые — в словарь лога, языковые — код языка |
| `READONLY` | две вкладки настройщика | в тему настройщика |
| `404` | `openai_errors.py`, `sources\preview.py` | `http.HTTPStatus` |
| `ProbeExit` (`OK` 0, `ERRORS` 1, `CONFIG` 2) | три пробника `app\tools\*_probe.py` повторяют `ExitCode` | общий каркас пробников, R4.2b |

`RETRYABLE_STATUSES` тоже переходит на `http.HTTPStatus` из stdlib (поправка П9).

У значения `"."` три смысла: `loader.py::KEY_SEPARATOR`, `url_text.py::HOST_DOT`, `settings_draft.py::DECIMAL_POINT`. Это законные исключения с обоснованием. Правило E8.

**N9 ✔ `Any` в аннотациях: 148 вхождений в 25 модулях (171 строка вместе с импортами).** Вне модулей-границ E14 — 21 вхождение в 11 модулях:
- merge: `service_lines.py` — 4, `prompt_texts.py` — 3, `prompt.py`, `attempt.py`, `answer.py` — по 1;
- настройщике: `setup\panels\channels_panel.py` — 3, `setup\fields\settings_draft.py` и `channel_draft.py` — по 1;
- `app\llm\backend.py` — 3;
- `app\sources\preview.py` — 2;
- `app\tools\llm_probe.py` — 1.

Сырой JSON доходит до предметного слоя. Правило E14.

**N10 ✔ Крупные классы вне плана.**
- `app\sources\language.py::LanguageProfile` — 22 члена и 3 статических метода.
- `app\sources\metadata.py::SourceMetadata` — 19 членов, 3 статических метода и 3 свободные функции рядом.

Оба переходят в R5.1b. Из тех, что план уже разбирает:

| Класс | Членов | Задача |
|---|---|---|
| `Readiness` | 32 | R5.3 |
| `ChannelsTab` | 26 | R7 |
| `MergedDescription` | 25 | R6.2a |
| `LivecraftPaths` | 25 | R4.2a |
| `_ConfigParser` | 24 | R5.2a |
| `MergeJob` | 21 | R6.4b |
| `QualityDiagnostics` | 21 | R6.2b |

Правило E18.

**N11 ✔ Структурные клоны.** Поиск по нормализованному синтаксису (имена стёрты) подтвердил клоны из плана:
- `PreviewDownloader.download` ↔ `SheetsReader.read_values`;
- `url_text.py::strip_tracking_params` ↔ `normalize_official_link_display`;
- `TailReader.url_tail` ↔ `hashtag_tail`;
- `TailScan.take_urls` ↔ `take_hashtags`;
- `_ConfigParser._string` ↔ `_bool`;
- `__init__` трёх вкладок настройщика.

Новые клоны:
- `app\llm\selection.py::ModelChoice.select` ↔ `_after_denial` → R6.4a (`ModelPair`);
- `app\llm\merges\check.py::MergeCheck.run` ↔ `run_with_recovery` → R6.4b;
- `app\secretsafe\vault.py::Vault.get` ↔ `origin_of` → R5.4 (`Vault.entry`);
- `app\texts\tail.py::TailReader.is_standalone_cta_line` ↔ `app\texts\description_marks.py::CtaLexicon.looks_like_cta_line` → R6.3b.

По определению E11 (окно 3, от 40 узлов) сверка Коворка находит 6 групп в 13 местах — это шесть клонов плана; четыре новых клона видны при окне 2 и 22 узлах. Точные числа даёт замок.

Правило E11.

**N12 ✔ Код в `app\setup\tabs\__init__.py`, 126 строк.**
- Константы Tk: отступ, цвет проблемы, коды клавиш 86/65/88/67, имена событий.
- Классы `ProblemLine`, `EditShortcut`, `EditShortcuts`.

Всё это уходит в модули темы и событий Tk (R7.2). Правило E19.

**N13 ✔ Пустые обёртки сверх `REFACTORING.md` 4.8.**
- `app\resources\loader.py::TextResource.lines` → `_read_lines`, `TextResource.data` → `_read_data`: два слоя на одно действие.
- `app\texts\tail.py::TailFragments.hashtags_line` → `merge_hashtag_lines`.
- `app\llm\merges\prompt.py::MergePrompt.language_name` → `language_full_name`.
- `app\llm\merges\description.py::MergedDescription.has_duplicate_paragraphs` и `contains_agenda_heading` — пересылки через `self.text`; определение E12 их не ловит, их снимает R6.2a чтением.

Правило E12.

**N14 ✔ Модули длиннее 400 строк.** Кроме названных в плане (`config\loader.py` 876, `llm\merges\description.py` 595), это `app\llm\merges\job.py` (458) и `app\llm\merges\check.py` (425). Правило E18.

**N15 ✔ Противоречие плана с правилом ООП.**
- Блок ООП, который вставляется в каждый промт, разрешает общий интерфейс (`Protocol` или базовый класс) только там, где его задаёт CLAUDE.md.
- `REFACTORING.md` вводит три новых `Protocol`: `ExplainedError` (4.5), `SlotTextsSource` (5.3), `SetupPanel` (6.7). Codex упрётся в противоречие.
- Решение без `Protocol` — поправка П3.

**N16 ✔ Кольца модулей вне плана и пакет вне карты слоёв** (сверка Коворка 25-09-2026).
- Кольца с учётом импортов под `TYPE_CHECKING`, которых нет в плане:
  - `app\secretsafe\crypto.py` ↔ `app\secretsafe\value.py` (ради `SecretValue.encrypt`) → R5.4;
  - `app\sheets\plan.py` ↔ `app\sheets\rows.py` (ради `SheetRow`) → R5.1a;
  - `app\llm\backends\openai.py` ↔ `openai_model.py` ↔ `openai_response.py` ↔ `openai_rate_limits.py` → R6.4a (в плане названо только `openai` ↔ `openai_response`).
- `slots` ↔ `packages` и `observability` ↔ `secretsafe` — кольца пакетов, а не модулей: их ловят рёбра «пакет → пакет» E16.
- Пакет `app\runtime\` (замок одного экземпляра, будущие автообновления) на карте 5.1 не назван. Его место — уровень 2 рядом с `run`: он импортирует только `core` и `observability`.

**N17 ✔ Порядок цепочки контура A и вход `MergeJob`.**
- В цепочке 6A `llm` стоит раньше `intake`, а R4.1b переносит `SlotGroup` в `app\intake\`. `MergeJob(group: SlotGroup)` тогда импортировал бы `intake` — нарушение E16.
- Решение Коворка: в R4.1b вход `MergeJob` — ключ слота и видео источников, а не `SlotGroup`; `SlotTexts.from_sources` получает тексты, а не `SourceVideo`, — шов не знает `sources`.

---

## 5. Эталон: 21 правило

Каждое правило соответствует требованию Артура. У каждого есть точный замер, допустимые исключения (только с обоснованием) и цель «ноль». Все пороги лежат в `app\tools\code_standard\standard.json`, а не в коде.

Если не сказано иное, правила проверяют `app\**\*.py`, кроме `app\tests\`. Правило E20 проверяет только `app\tests\`.

**Ключ нарушения** — `путь::квалифицированное имя`. Путь пишется от корня репозитория и всегда с обратной косой чертой, независимо от ОС, чтобы реестр совпадал у Codex на Windows и у Коворка в контейнере. Пример: `app\config\loader.py::_ConfigParser._string`.

| Правило | Требование Артура | Сейчас ✔ |
|---|---|---|
| E1 Свободные функции | реальный код, а не набор функций | (а) 25, (б) 35, (в) 7 |
| E2 Статические методы | то же | 59 в 40 классах |
| E3 Длина определения | методы короткие | 9 |
| E4 Параметры | объект запроса вместо россыпи | 7 |
| E5 Литералы в телах | ноль хардкода | 1027 строк + 20 чисел |
| E6 Кириллица в коде | весь текст вне кода | 46 |
| E7 Текст исключений | весь текст вне кода | 58 |
| E8 Одно значение — одно объявление | общие константы в одном месте | 36 ключей / 174 объявления |
| E9 Регулярки | повторы — в общий объект | 9 / 31 |
| E10 Логгеры | повторы — в общий объект | 35 |
| E11 Структурные клоны | повторяющиеся конструкции — в объект | 6 групп / 13 мест |
| E12 Пустые обёртки | убрать двойные и тройные обёртки | 7: (а) 2, (б) 2, (в) 3 |
| E13 Кортежи-состояния | состояние — в полях | 16, из них 2 исключения |
| E14 Сырые данные | объекты вместо словарей | 21 в 11 модулях вне границ (всего 148 в 25) |
| E15 Защитные преобразования | убрать лишнее | 82 в 24 модулях вне границ (всего 97 в 30) |
| E16 Слои и кольца | код для развития | 8 рёбер «пакет → пакет», 5 колец модулей |
| E17 Время | один объект | 11 |
| E18 Размеры | упростить | модулей 4, классов 8 |
| E19 Код в `__init__` | порядок в пакетах | 1 |
| E20 Тесты | тесты тоже эталон | см. ниже |
| E21 Имя определено дважды | — | 0 |

**Точные определения.**

- **E1 Свободные функции.** Функция уровня модуля — нарушение, если выполняется любой признак:
  - (а) в аннотациях её параметров или результата назван класс, объявленный в app;
  - (б) все её использования в коде app — внутри одного класса того же модуля;
  - (в) в коде app её никто не использует; тесты не считаются.

  Исключения: точки входа (`app\main.py::run_cli`, `main` пробников — до R4.2b) и функции, которые называет CLAUDE.md. Это `normalize_handle`, `safe_trim_right`, `parse_sheet_datetime` (§0), а для контура B — `mask_stream_key` (§6, инвариант 6) и `parse_iso_start` (§4).

  Замок не должен давать ложных нарушений. Пропуск из-за совпадения имён допустим, но его надо описать в докстроке правила.

  Из названных исключений правило сейчас ловит три: `safe_trim_right` (а), `mask_stream_key` (в), `parse_iso_start` (в). Остальные оно не ловит, и в `exceptions.json` они не заносятся.

- **E2 Статические методы.** Любой `@staticmethod` — нарушение. Он становится одним из трёх:
  - методом экземпляра, если работает с полями;
  - методом объекта-значения, которому принадлежит правило (`Base64Field.decode`);
  - общим примитивом, если повторяется.

- **E3 Длина определения.** От строки `def` до последней строки, включая докстроку, не больше 30. Сейчас нарушают 9 определений:
  - `app\core\safe_trim.py::safe_trim_right` — 57;
  - `app\llm\json_text.py::extract_json_object_candidates` — 34;
  - `app\llm\merges\check.py::MergeDiagnostics.of` — 34;
  - `app\main.py::run_cli` — 33;
  - `app\llm\backends\openai.py::LlmExchange._call` — 33;
  - `app\paths.py::build_paths` — 32;
  - `app\texts\tail.py::EmbeddedTail.of` — 32;
  - `app\llm\merges\publication.py::MergePublication.of` — 32;
  - `app\texts\official_links.py::OfficialLinksBlocks.of` — 31.

- **E4 Параметры.** Не больше 4 без `self`/`cls`. Каждый из позиционных, именованных, `*args` и `**kwargs` считается за один. Сейчас нарушают 7 функций:
  - `app\llm\errors.py::LlmRequestError.__init__` — 6;
  - `app\setup\tabs\keys_tab.py::KeyRowView.__init__` — 6;
  - `app\llm\backend.py::LlmRequest.from_settings` — 5;
  - `app\llm\merges\check.py::MergeCheckRequest.of` — 5;
  - `app\llm\merges\job.py::MergeJob._result` — 5;
  - `app\llm\merges\publication.py::MergePublication.of` — 5;
  - `app\llm\selection.py::ModelChoice._chosen` — 5.

- **E5 Литералы в телах.** В теле функции или метода (включая вложенные, без докстрок) и в значениях параметров по умолчанию нет:
  - строковых литералов, кроме `""`;
  - числовых литералов, кроме `0` и `1` (запись `-1` — это минус и `1`).

  Части f-строк считаются. Значение ключа в реестре — число литералов в функции. Отчёт делит их по видам: лог, идентификатор, разделитель, текст, число.

  Куда уходят литералы:

  | Вид | Куда |
  |---|---|
  | строки лога | `LogEvent` и перечисления событий |
  | ключи JSON и поля ответов | перечисления ключей: `SettingKey`, `ChannelKey`, ключи манифеста, поля yt-dlp и OpenAI |
  | разделители | общий словарь |
  | английский текст | причина-перечисление или константа класса ошибки |
  | флаги командной строки | `CliFlag` |
  | имена файлов | константы `paths.py` / `DataDir` |
  | числа | именованные константы или настройки |

- **E6 Кириллица в коде.** Строки с кириллицей допустимы только в двух модулях: `app\ui\messages_ru.py` и `app\core\alphabet.py` (классы букв и карта свёртки). Лексиконы лежат файлами в `app\resources\text\`. Докстроки и комментарии не считаются.

- **E7 Текст исключений.** Нарушением считается `raise X(…)`, у которого любой прямой аргумент (позиционный или именованный) — строковый литерал или f-строка. Сейчас таких мест 58:
  - `app\config\loader.py` — 22;
  - `app\secretsafe\crypto.py` — 17;
  - `app\secretsafe\store.py` — 4;
  - остальные — по 1–2 в 10 модулях.

  Исключение, которое может дойти до человека, несёт причину-перечисление, а текст для человека берёт из `messages_ru`. Текст для разработчика (нарушение инварианта кода) — константа класса ошибки или модуля. С задачи R3.5a нарушением E7 считается и класс исключения app без `reason` (Enum), `human` и `log_line` (контракт ошибок, П3).

- **E8 Одно значение — одно объявление на смысл.** Константа — присваивание уровня модуля или класса с именем прописными и литеральным значением.
  - Строка или байты (не член `Enum`) нарушают правило, если то же значение объявлено константой в другом модуле. Ключ — значение.
  - Число нарушает правило, если в другом модуле объявлена константа с тем же именем и тем же значением; члены `Enum` здесь считаются. Ключ — `имя = значение`: одинаковые числа под разными именами — разные пороги.
  - Величина — число модулей. Одинаковое значение с разным смыслом — исключение с обоснованием.
  - Сейчас 31 строковое значение и 5 числовых ключей (`SECONDS_PER_MINUTE`, `DETAIL_MAX_CHARS` и `OK` / `ERRORS` / `CONFIG` — копии `ExitCode` в пробниках), всего 174 объявления.

- **E9 Регулярки.**
  - `re.compile` и другие `re.*` с шаблоном-литералом — только на уровне модуля.
  - Строка шаблона встречается во всём app один раз.
  - Классы букв собираются из `app\core\alphabet.py`.

- **E10 Логгеры.** `get_logger` получает только член `LogArea`. `logging.getLogger` вызывается только в `app\observability\`.

- **E11 Структурные клоны.**
  - Нормализация: стираются имена, атрибуты, имена аргументов и значения констант; тип константы остаётся.
  - Нарушение — окно из 3 подряд идущих операторов одного блока размером не меньше 40 узлов ast, которое встречается в двух разных функциях.
  - Ключ — отсортированный список `путь::имя` участников.
  - Пороги лежат в `standard.json`. После R8.2 Коворк ужесточает их по отчёту: при окне 2 и 22 узлах сейчас около 50 групп (сверка Коворка; точное число даёт замок).

- **E12 Пустые обёртки.** Нарушение любого из трёх видов:
  - (а) Пересылка. Тело — один `return` вызова, аргументы которого — ровно параметры функции, каждый по разу и без преобразований. `self` в вызове не участвует. Вызывается не встроенная функция (`len`, `bool`, `str`, `int`, `float`, `tuple`, `list`, `set`, `frozenset`, `dict`, `sorted`, `any`, `all`, `min`, `max`, `sum`) и не конструктор класса.
  - (б) Два слоя. Свойство или метод без параметров, чьё тело — `return self._<имя>()`.
  - (в) Чужое тело. Метод, чьё тело — один вызов свободной функции того же модуля, у которой нет других пользователей в app.

  Исключение — публичный вход фасада модуля по §11.

- **E13 Кортежи-состояния.** Аннотация результата `tuple[A, B, …]` без `...` на верхнем уровне — нарушение; вместо кортежа нужен объект-значение. Исключения — ключи сортировки: `app\setup\fields\language_choice.py::LanguageOption.sort_key`, `app\slots\slot.py::SlotKey.sort_key`.

- **E14 Сырые данные.** `Any`, `dict[str, Any]`, `Mapping[str, Any]` в аннотациях допустимы только в модулях-границах из `standard.json`. Это модули, которые разбирают JSON, ответы SDK или работают через ctypes:
  - `app\config\` (после R5.2 — только `json_node.py`);
  - `app\llm\json_text.py`;
  - `app\llm\backends\openai*.py`;
  - `app\secretsafe\crypto.py`, `app\secretsafe\dpapi.py`;
  - `app\sources\ytdlp.py`, `app\sources\metadata.py`;
  - `app\resources\loader.py`;
  - `app\sheets\client.py`;
  - `app\google\auth.py`;
  - `app\packages\package.py`.

- **E15 Защитные преобразования.** `str(<выражение> or "")` допустимо только в модулях-границах из E14.

- **E16 Слои и кольца.**
  - Импорты между пакетами app идут только по карте из `standard.json`: раздел 5.1 `REFACTORING.md` с поправками П1 и П2.
  - Импорт под `TYPE_CHECKING` и импорт внутри функции тоже считаются.
  - Кольца импорта между модулями запрещены.
  - Ключи: `пакет -> пакет` и `кольцо: модуль | модуль`.
  - Сейчас (сверка Коворка, N16): рёбра `observability -> secretsafe` и `slots -> config, google, packages, secretsafe, setup, sheets, sources`; кольца модулей `secretsafe\crypto` ↔ `secretsafe\value`, `sheets\plan` ↔ `sheets\rows`, `llm\backends\openai` ↔ `openai_model` ↔ `openai_response` ↔ `openai_rate_limits`, `llm\merges\description` ↔ `llm\merges\quality`, `llm\merges\job` ↔ `llm\merges\run`. Кольца пакетов `slots` ↔ `packages` и `observability` ↔ `secretsafe` видны как рёбра.

- **E17 Время.** `datetime.now`, `datetime.utcnow`, `datetime.today`, `date.today`, `time.time`, `time.monotonic`, `time.perf_counter` — и вызовы, и ссылки на них — только в `app\core\clock.py`.

- **E18 Размеры.**
  - Модуль — не больше 400 строк. Исключение — каталог `app\ui\messages_ru.py`, оно задано в `standard.json`.
  - Класс — не больше 20 членов: методы, свойства и поля с аннотацией.

- **E19 `__init__.py`.** Разрешены только докстрока, `from __future__`, импорты-реэкспорт и `__all__`.

- **E20 Тесты.**
  - Модули тестов не импортируют друг друга; общее — только в `conftest.py` и `app\tests\fixtures\`.
  - Нет строк с именами логгеров вида `"livecraft.<область>"` (область — член `LogArea`; имена файлов `livecraft.json`, `livecraft.exe` — не логгеры).
  - Нет подмен приватных имён и глобальных `os` / `shutil`.
  - `dataclasses.replace` над объектами программы — только в `app\tests\fixtures\`.

  Сейчас ✔: 7 файлов с 11 импортами друг друга и 20 строк с именами логгеров (ещё 21 строка — имена файлов `livecraft.json`, `livecraft.exe`). Остальное посчитает замок.

- **E21 Имя верхнего уровня определено в модуле дважды.** Правило переносится из `app\tests\test_module_definitions.py`. Перегрузки `@overload` и вложенные имена не считаются. Как и прежний тест, правило проверяет весь `app`, включая `app\tests\`.

---

## 6. Замок

**Назначение.** Замок превращает эталон в одну команду и в тест. Реестр долгов фиксирует нарушения, которые есть в коде на момент создания замка. Тест падает на любом новом или выросшем нарушении, а также на долге, который уже снят в коде, но остался в реестре. Поэтому реестр может только сокращаться. Этап R закончен, когда реестр пуст; замок после этого остаётся в проекте навсегда.

**Состав.**
- `app\tools\code_standard\` — инструмент разработки. В поставку не идёт, как пробники.
  - Из app импортирует только свой пакет и `app.ui.messages_ru` (модуль без зависимостей). Поэтому он работает на любом Python 3.10+ без пакетов проекта: и в `.venv_livecraft` у Codex, и в оболочке Коворка на машине Артура (Python 3.10) прямо на репозитории, без копирования снимка.
  - Возможности Python 3.11+ (`StrEnum`, `tomllib`, `typing.Self` вне `TYPE_CHECKING`, `datetime.UTC`, `ExceptionGroup`, `except*`) и синтаксис 3.12+ в нём не используются.
- `app\tools\code_standard\standard.json` — стандарт как данные: пороги, модули-исключения, модули-границы, карта слоёв, модуль времени.
- `app\tests\data\code_standard\debt.json` — реестр долгов: `правило -> ключ -> величина`.
- `app\tests\data\code_standard\exceptions.json` — постоянные исключения: `правило -> ключ -> обоснование` (русская строка, не пустая).
- `app\tests\test_code_standard.py` — тест замка.

**Объекты.** Имена ориентировочные, Codex уточняет их в рамках §0. `Protocol` не используется (П3).

| Объект | Что делает |
|---|---|
| `Rule(str, Enum)` | коды E1–E21; подписи для человека — в `messages_ru` |
| `Standard` | загружается из `standard.json`; ключи файла — перечисление |
| `SourceTree` / `ModuleSource` | разбирают каждый файл один раз; дают путь, текст, дерево, пакет, квалифицированные имена; `SourceTree` строится и из словаря «путь → текст» для образцов в тесте |
| `FunctionShape`, `CodeValues`, `ModuleShape`, `CloneFinder`, `TestShape` | классы проверок, разбитые по заботам; каждый отдаёт `Measurement` своих правил |
| `Measurement` | правило и `ключ -> величина` |
| `Ledger` | реестр: `load`, `save`, `diff(current) -> LedgerDiff` с полями `new`, `grown`, `shrunk`, `gone` |
| `Exceptions` | постоянные исключения |
| `StandardReport` | таблица «правило, сейчас, в реестре, исключений, цель 0» с разбивкой E5 по видам |

**Команды.** Все запускаются как `python -m app.tools.code_standard …`.

| Команда | Что делает |
|---|---|
| без флагов | печатает отчёт, код 0 |
| `--init` | создаёт реестр, только если его ещё нет |
| `--write-debt` | переписывает реестр по текущему коду, только если ничего не появилось и не выросло; иначе печатает список роста и выходит с кодом 1 |
| `--compare <git-ref или путь к реестру>` | сравнивает реестр с его прежней версией: добавленное и выросшее — список и код 1; снятое — список |
| `--files <пути>` | печатает долги этих файлов, для раздела «ДОЛГИ К СНЯТИЮ» |

**Тест замка.**
- По каждому правилу нет нового и выросшего относительно реестра и исключений.
- В реестре нет устаревших записей; при падении тест подсказывает команду `--write-debt`.
- Каждое исключение ещё ловится правилом и имеет обоснование.
- Чувствительность: для каждого правила есть образец-нарушитель и чистый образец, и замок находит ровно ожидаемое.
- Сам пакет `app\tools\code_standard\` проходит все правила без долгов.
- Инструмент импортирует из app только свой пакет и `app.ui.messages_ru`.
- Весь тест укладывается в 15 секунд.

**Отчёт замка** заменяет таблицу раздела 2 `REFACTORING.md` и песочничные `_an/metrics.py`. Его вывод — обязательная часть отчёта каждой задачи R.

---

## 7. Поправки к `REFACTORING.md`

- **П1.** `alphabet.py` лежит в `app\core\`, а не в `app\texts\`: класс кириллицы нужен `core\sheet_text.py:38` (N2). Туда же — карта свёртки «ё → е» из `language_choice.py`. Раздел 4.2.
- **П2.** Уточнения карты слоёв 5.1:
  - `observability` не импортирует `secretsafe` (N5);
  - `app\tools\code_standard` импортирует только себя и `app.ui.messages_ru`;
  - файл `test_architecture.py` не создаётся: карта лежит в `standard.json`, её проверяет правило E16;
  - `runtime` — уровень 2 рядом с `run` (N16);
  - `observability` не импортирует и `paths`: `RunLog.open` (R4.2a) получает папку логов, а не `LivecraftPaths`.
- **П3.** Новых `Protocol` нет (N15). Вместо них:
  - **Контракт ошибок** — соглашение, которое держит замок (E7 с R3.5a): у каждого исключения app есть `reason` (Enum), `human` из `messages_ru` и `log_line`, а `str()` равен `human`.
  - **Выбор текстов слота.** `SlotBuild` принимает готовые `SlotTexts`. Какие тексты — решает оркестратор `app\intake\`: при `--no-llm` — `SlotTexts.from_sources`, иначе — метод `MergeJob`. Задача 3.15 подключает merge в одном месте, интерфейс не нужен.
  - **Панели настройщика.** Одинаковый API трёх панелей (`title`, `notices`, `is_dirty`, `save() -> PanelEdit`) держит тест моделей панелей. `PanelEdit[P]` — обобщённый dataclass, а не интерфейс.
- **П4.** `LogEvent`, словарь значений лога и перечисления событий создаются в R3.1, а не в R8.1. Каждая следующая задача переводит строки лога в тех функциях, которые пишет или переписывает. R8.1 доводит остатки.
- **П5.** Все задачи L разрезаны до M и меньше (раздел 8). У каждой есть «ДОЛГИ К СНЯТИЮ».
- **П6.** Раздел 2 `REFACTORING.md` заменяется отчётом замка. `str(x or "")` считается синтаксически.
- **П7.** R8.2 заканчивается пустым реестром. Коворк переносит правила E1–E21 (по строке на правило и ссылку на `standard.json`) и карту слоёв в CLAUDE.md §5 и §11. Это уточнение уже принятых стандартов §11, а не новое решение.
- **П8.** Куда относятся задачи раздела 6.6: `safe_trim` (`TrimReason`, `TrimBoundary`) — R3.2c, `official_links` — R6.3a, `tail` — R6.3b.
- **П9.** HTTP-коды берутся из `http.HTTPStatus` (stdlib), а не числами: `RETRYABLE_HTTP_STATUSES` и `NOT_FOUND` ×2. Это R3.4.
- **П10.** Семь тестов, которые сами обходят исходники, переводят свой обход на `SourceTree` замка (R2.1b); их утверждения не меняются. Это:
  - `test_core_url_text.py::test_core_modules_import_nothing_from_app_outside_core`;
  - `test_core_url_text.py::test_import_check_sees_nested_and_relative_imports`;
  - `test_google_auth.py::test_scopes_live_only_in_the_auth_module`;
  - `test_llm_backend.py::test_neutral_modules_name_no_backend`;
  - `test_llm_merges_answer.py::test_the_emoji_pattern_has_one_source`;
  - `test_llm_merges_quality.py::test_merge_patterns_have_no_literal_range_characters` (защищает `app\llm\merges\` от литералов `\uXXXX`, которые оставляет инструмент записи Codex);
  - `test_module_definitions.py` — становится правилом E21 уже в R2.1a.

---

## 8. Этап R: состав и порядок

Одна строка — одна задача, один проход Codex, объём не больше M. Колонка «Снимает» называет правила, которые после задачи должны быть на нуле во всём app. Долги в своих файлах снимает каждая задача по разделу «ДОЛГИ К СНЯТИЮ».

**Волна 1–2. Исправления, замок, сетка**

| Задача | Что | Откуда | Снимает | Объём |
|---|---|---|---|---|
| R1.1 | Дефекты D1–D7 (промт выдан) | 3 | — | M |
| R2.1a | Замок: каркас, реестр, команды; правила E1–E4, E12, E13, E18, E19, E21 | этот файл, 5–6 | E21 держит с нуля | M |
| R2.1b | Замок: правила E5–E11, E14–E17, E20; семь тестов с обходом исходников — через `SourceTree` | 5–6, П10 | — | M |
| R1.2 | Мёртвый код | 4.9 | E1(в), кроме исключений | M |
| R2.2a | Пакет `app\tests\fixtures\`; тесты merge перестают импортировать друг друга | 6.8 | импорты тестов в E20 | M |
| R2.2b | Фабрики, `LogCapture`, подделки портов; имена логгеров строкой; `normalized_check` через программу | 6.8 | E20 | M |
| R2.3 | Сверки с донором — в `app\tools\donor_compare\` одной командой | R2.3 | — | M |

**Волна 3. Общие объекты**

| Задача | Что | Откуда | Снимает | Объём |
|---|---|---|---|---|
| R3.1 | `LogArea`, словарь значений лога, `LogEvent`, перечисления событий; все логгеры; `_flag`, `YES` / `NO`, «пусто» | 4.1, П4 | E10 | M |
| R3.2a | Пробелы, абзацы, строки: `paragraphs.py`, `collapse_spaces`, `nonempty_lines`, `unique_in_order` (N4) | 4.2 | — | M |
| R3.2b | `app\core\alphabet.py` (П1), `hashtags.py`, `similarity.py::TextPair` | 4.2 | — | M |
| R3.2c | `BulletLine`, заголовок «🌐 …:», конец предложения, тройная обёртка префикса; `safe_trim` через `TrimReason` и `TrimBoundary` | 4.2, 4.8, 6.6 | E3 `safe_trim_right` | M |
| R3.3a | `app\core\web_link.py::WebLink`; `url_text.py` — фасад | 4.3 | — | M |
| R3.3b | `SourceLink`, `LinkedText`, `YouTubeVideoId`; `slot_id` — в `SlotKey` | 4.3 | E9 | M |
| R3.4 | `RetryLoop`, `AttemptFailure`, `http.HTTPStatus` (П9) | 4.4 | клон повторов в E11 | M |
| R3.5a | Контракт ошибок (П3); тексты причин — в `messages_ru` | 4.5 | E7 | M |
| R3.5b | Общий словарь констант, `AtomicFile`, `TextResource.body`; копии из N8 | 4.7, N8 | E8, кроме исключений | M |
| R3.6 | Данные и лексиконы — в ресурсы, объекты лексиконов, `ServiceHints`, `PhraseLexicon`, шаблон `livecraft.json`; свёртка «ё → е» | 4.6, N2 | E6 | M |
| R3.7 | `app\core\clock.py::Clock`, `require_aware`, дефект D8 | N6, N7 | E17 | S |

**Волна 4. Слои и запуск**

| Задача | Что | Откуда | Снимает | Объём |
|---|---|---|---|---|
| R4.1a | `app\run\` (`ExitCode`, `RunMode`, `RunPart`); кольцо observability ↔ secretsafe; `TextLanguageDetector` → `app\texts` | 5.2, N5 | — | M |
| R4.1b | `app\intake\`; `slots` — только шов (`Preview` — значение); выбор текстов слота (П3); вход `MergeJob` — ключ слота и видео (N17) | 5.2, 5.3, N17 | E16 между пакетами | M |
| R4.2a | `LivecraftPaths.locate` / `DataDir`, `RunLog`, `Console` | 6.1 | E3 `build_paths` | M |
| R4.2b | `Launch`, `RunRequest` / `CliFlag`, общий каркас пробников | 6.1 | E1 в `main.py`, E3 `run_cli` | M |

**Волна 5. Контур A, конфиг, готовность, сейф**

| Задача | Что | Откуда | Снимает | Объём |
|---|---|---|---|---|
| R5.1a | `AdmittedRow`, `SkippedRow`, `PlannedRows`, `HeaderAliases`, `Counts`; кольцо `sheets\plan` ↔ `rows` | 6.4, N16 | — | M |
| R5.1b | `SourceFacts`, `PreparedSources`, свойства `SourceVideo`; разрезка `LanguageProfile` и `SourceMetadata` | 6.4, N10 | — | M |
| R5.1c | `IntakeResult` опрашивает стадии, `StreamSlot.texts`, `PackagePeriod`; затем контрольный прогон режима А (Артур) | 6.4 | — | M |
| R5.2a | `KeyPath` / `JsonNode` вместо `_ConfigParser`; `from_node` у настроек; `SettingKey` | 6.2 | — | M |
| R5.2b | `ChannelHandle`, `ChannelConfig.problem`, `ConfiguredChannels`, `ChannelKey`; разрезка `loader.py` с фасадом | 6.2 | E18 `loader.py` | M |
| R5.3 | `SettingsFile`, `ChannelsFile`, `ConfigRead`; `Need`, `PartState`; одна строка на нужду; `Readiness.log` | 6.2, 6.3 | E18 `Readiness` | M |
| R5.4 | Сейф: `Vault.overlaid_by`, `only`, `entry` (клон `get` / `origin_of`), `missing_of`; `VaultOrigin`, `FieldSpec`, `Base64Field`, `VaultFile.new`; кольцо `crypto` ↔ `value` | 6.2, N11, N16 | — | S |

**Волна 6. Merge и нейросеть.** Каждая задача проходит сверку с донором.

| Задача | Что | Откуда | Снимает | Объём |
|---|---|---|---|---|
| R6.1a | Порядок модулей, `merge_rules.py`, `MergeLexicons`, все пороги — в `rules.py` | 6.5 | кольца merge в E16 | M |
| R6.1b | Коды отказа одной таблицей, `MergeAnswer.SCHEMA`, `min_bullets`, `MergeSkipReason` / `MergeStopReason` | 6.5 | — | M |
| R6.2a | `MergedDescription` по заботам: `HookEcho`, `DescriptionOpening`, `EmojiUsage` | 6.5 | E18 `description.py` | M |
| R6.2b | `script_mix.py`, `QualityNormalization`; кортежи — значениями; `QualityDiagnostics` | 6.5 | — | M |
| R6.3a | `LinkCandidate`, `RankedLinks`, `SourceDescriptionLines`; правило ссылок блока — в `OfficialLinksBlocks` | 6.5, 6.6 | — | M |
| R6.3b | `PublicationBody`, `GateVerdict`, `TailCollector`; правила призыва — у `CtaLexicon` (клон N11) | 6.5, 6.6 | — | M |
| R6.4a | Разъём: `LlmFailure`, `TokenCounts`, `LlmResponse`, `ModelPair` (клон N11), `openai_request.py`, один цикл flex, `ResponseSchema`, `ParsedJson`; кольцо четырёх модулей `openai*` | 6.5, N16 | — | M |
| R6.4b | Попытка: `MergeRun.request`, `MergeAttempt(run)`, `MergeAttemptResult.outcome`, `MergeOutcome`; клон `run` / `run_with_recovery`; `MergeDiagnostics` | 6.5, N11 | E18 `job.py`, `check.py` | M |

**Волна 7. Настройщик.** Можно делать в любой момент после R5.3.

| Задача | Что | Откуда | Снимает | Объём |
|---|---|---|---|---|
| R7.1a | Модели панелей (П3), `PanelEdit`, `KeysPanel.from_paths`, `DraftField` | 6.7 | — | M |
| R7.1b | `LanguagePicker`, `LanguageDirectory`; `ChannelDraft.languages` — кортеж; тесты языка без Tk; `SetupWindowDriver` | 6.7 | — | M |
| R7.2 | Вид: `TabShell`, `FormGrid`, `DraftVariables`, `SetupTheme`, `TkEvent` (из `tabs\__init__.py`), `SetupWindow.open`; одно правило «несохранённое» | 6.7, N12 | E19 | M |

**Волна 8. Завершение**

| Задача | Что | Снимает | Объём |
|---|---|---|---|
| R8.1 | Остатки строк лога → `LogEvent` | E5 по виду «лог» | M |
| R8.2 | Остатки всех правил; реестр пуст; перенос стандарта в CLAUDE.md (П7) | всё | M |

**Порядок.**
1. R1.1 → R2.1a → R2.1b → R1.2 → R2.2a → R2.2b → R2.3.
2. Затем R3.1, потому что логи нужны всем. После неё: R3.2a → R3.2b → R3.2c; R3.3a → R3.3b; R3.4; R3.5a → R3.5b; R3.6; R3.7.
3. R4.1a → R4.1b → R4.2a → R4.2b.
4. R5.1a → R5.1b → R5.1c → R5.2a → R5.2b → R5.3 → R5.4.
5. R6.1a → … → R6.4b.
6. Волна 7 — в любой момент после R5.3. R8.1 и R8.2 — последними.
7. После R6.4b можно делать задачи продукта 3.14b и 3.15. Их код сразу проходит замок, то есть с первого дня пишется по эталону.

**Итог:** 42 задачи. Боевых прогонов на этапе R не нужно. Исключение — контрольный прогон режима А после R5.1c: он показывает, что пакет и консоль не изменились.

---

## 9. Порядок работы Коворка и Codex на задаче R

**Коворк перед промтом:**
1. Читает строку задачи в разделе 8, соответствующий раздел `REFACTORING.md` и разделы CLAUDE.md, которых задача касается. Сверяет символы grep'ом по текущему коду.
2. На снимке кода в контейнере запускает `python -m app.tools.code_standard --files <файлы SCOPE LOCK>`. Из вывода берёт в раздел «ДОЛГИ К СНЯТИЮ»:
   - все долги по теме задачи;
   - долги функций, которые задача переписывает.
3. Пишет промт по шаблону. Раздел «ДОЛГИ К СНЯТИЮ» идёт после ПЕРЕНОС и перед ШАГИ. Перед тремя обязательными блоками вставляется блок «ПРАВИЛА ЭТАПА R» (ниже), дословно.

**Приёмка:**
1. `git show --stat` — изменены только файлы из SCOPE LOCK.
2. `python -m app.tools.code_standard --compare <предыдущий коммит>`:
   - ничего не добавлено и не выросло;
   - все долги из «ДОЛГИ К СНЯТИЮ» сняты.
3. В отчёте Codex тест замка зелёный, а отчёт замка приведён до и после.
4. Для `app\llm\merges\` и `app\texts\` — сверка с донором без расхождений.
5. ООП Коворк проверяет чтением. Замок не видит, правильный ли объект выбран владельцем правила.
6. После приёмки — строка в CLAUDE.md §16 с числами отчёта замка.

**Блок «ПРАВИЛА ЭТАПА R» — дословно в каждый промт, начиная с R1.2.** В R2.1a и R2.1b вместо него действуют правила самих задач.

```text
ПРАВИЛА ЭТАПА R (REFACTORING.md, REFACTORING_STANDARD.md):
- Поведение программы не меняется, кроме явно названного в ЗАДАЧЕ; строки лога донора — побайтно.
- Задача, которая касается app\llm\merges\ или app\texts\, прогоняет сверку с донором на тех же входах и доказывает 0 расхождений (после R2.3 — одной командой python -m app.tools.donor_compare).
- Замок эталона зелёный: .\.venv_livecraft\Scripts\python.exe -m pytest app\tests\test_code_standard.py -q. Реестр долгов app\tests\data\code_standard\debt.json только сокращается и пишется только командой .\.venv_livecraft\Scripts\python.exe -m app.tools.code_standard --write-debt; новые записи в app\tests\data\code_standard\exceptions.json — только те, что названы в этом промте.
- Все долги из раздела ДОЛГИ К СНЯТИЮ сняты. В функциях и методах, которые задача пишет или переписывает, нет долгов ни по одному правилу, для которого в коде уже есть общий объект (LogEvent, словарь значений лога, общий словарь констант, перечисления ключей, WebLink, RetryLoop, Clock и т. д.).
- Новый код сразу соответствует эталону (REFACTORING_STANDARD.md, раздел 5). Новый долг — не решение, а остановка по случаю (в).
- В разделе 4 отчёта — вывод .\.venv_livecraft\Scripts\python.exe -m app.tools.code_standard до и после задачи.
```

---

## 10. Решения

**Нужно решение Артура:** нет. План приводит код к уже принятым CLAUDE.md §0, §4, §10 и §11. Контракты, инварианты, зависимости и живые каналы он не затрагивает.

**Решено без Артура, по строке на решение:**
- Эталон — 21 измеримое правило. Его держит замок с реестром, который только сокращается; после этапа замок остаётся навсегда.
- Замок — инструмент разработки на stdlib в `app\tools\code_standard\` плюс тест. Новых зависимостей нет, в поставку он не идёт.
- Алфавит лежит в `app\core\` (П1).
- Новых `Protocol` нет, потому что правило ООП разрешает их только там, где их задаёт CLAUDE.md (П3).
- `LogEvent` создаётся в начале этапа (П4).
- Дефект D8 исправляется по инварианту 4: отметки в именах и записях лога и замка ставятся по поясу программы; до чтения настроек — по поясу поставочного шаблона.
- HTTP-коды берутся из `http.HTTPStatus` (stdlib).
- Этап разрезан на 42 задачи объёмом не больше M.

**Боевой прогон:** до R5.1c не нужен. После R5.1c — обычный запуск режима А на боевой таблице; смотреть, что пакет в `bcast\` и консоль те же, что до этапа.

---

## 11. Промт R2.1a и план R2.1b

Перед выдачей Коворк сверяет раздел ФАКТЫ с кодом после приёмки R1.1. Числа могут немного сдвинуться; Codex объясняет расхождение в отчёте.

```text
ПРОЕКТ: D:\_projects\livecraft, ветка feature/livecraft. Промт составил Коворк по коду на 25-09-2026 (снимок 50b4217, сверен с кодом после R1.1). Перед началом прочитай CLAUDE.md целиком; §0 (ООП), §6 (инварианты), §7.4 (секреты) и §11 (стандарты) обязательны без исключений. Прочитай REFACTORING_STANDARD.md, разделы 5 и 6: там точные определения правил и устройство замка; ниже — то, что нужно для этой задачи.

ЗАДАЧА: в репозитории появляется замок эталона кода — команда python -m app.tools.code_standard и тест app\tests\test_code_standard.py с реестром долгов, который может только сокращаться; в этой задаче — каркас замка и правила формы функций и классов E1, E2, E3, E4, E12, E13, E18, E19, E21.
ЗАЧЕМ: этап R (REFACTORING.md, REFACTORING_STANDARD.md). Эталон ООП должен проверяться одной командой и не откатываться: каждая следующая задача R снимает названные долги реестра, новый код без долгов. Правила E5–E11, E14–E17, E20 добавит следующая задача R2.1b на этом же каркасе.

ФАКТЫ ИЗ КОДА (снимок 50b4217; R1.1 мог сдвинуть числа на единицы):
- app\tools\ сейчас держит пробники llm_probe.py, sheets_probe.py, source_probe.py; в поставку app\tools\ не идёт. Пакета app\tools\code_standard\ нет.
- app\ui\messages_ru.py — все тексты для человека, модуль ничего не импортирует из app.
- app\tests\test_module_definitions.py::find_duplicate_definitions, _app_modules, _is_overload и три теста — проверка «имя верхнего уровня определено в модуле дважды»; @overload и вложенные имена не считаются; тест обходит весь app, включая app\tests. Сейчас нарушений 0.
- Ожидаемые числа по правилам (разбор ast, только app без app\tests):
  E1 свободные функции: признак (а) 25, (б) 35, (в) 7 (функции могут попадать под несколько признаков);
  E2 статические методы: 59 в 40 классах;
  E3 определения длиннее 30 строк: 9 — safe_trim.py::safe_trim_right 57, json_text.py::extract_json_object_candidates 34, check.py::MergeDiagnostics.of 34, main.py::run_cli 33, openai.py::LlmExchange._call 33, paths.py::build_paths 32, tail.py::EmbeddedTail.of 32, publication.py::MergePublication.of 32, official_links.py::OfficialLinksBlocks.of 31;
  E4 больше 4 параметров: 7 — errors.py::LlmRequestError.__init__ 6, keys_tab.py::KeyRowView.__init__ 6, backend.py::LlmRequest.from_settings 5, check.py::MergeCheckRequest.of 5, job.py::MergeJob._result 5, publication.py::MergePublication.of 5, selection.py::ModelChoice._chosen 5;
  E12 пустые обёртки: 7 — (а) publication.py::PublishGate.has_duplicate_paragraphs, description_marks.py::starts_with_cta_prefix; (б) resources\loader.py::TextResource.lines, TextResource.data; (в) description_marks.py::CtaLexicon.starts_with_prefix, tail.py::TailFragments.hashtags_line, prompt.py::MergePrompt.language_name;
  E13 кортежи-результаты: 16, из них 2 — ключи сортировки (они в ИСКЛЮЧЕНИЯ), в реестр — 14;
  E18 модули длиннее 400 строк: 4 — config\loader.py 876, llm\merges\description.py 595, job.py 458, check.py 425 (app\ui\messages_ru.py — исключение стандарта); классы больше 20 членов: 8 — Readiness 32, ChannelsTab 26, MergedDescription 25, LivecraftPaths 25, _ConfigParser 24, LanguageProfile 22, MergeJob 21, QualityDiagnostics 21;
  E19 код в __init__.py: 1 — app\setup\tabs\__init__.py;
  E21: 0 (по всему app, включая app\tests).

ОБЪЕКТЫ (имена можно уточнить в рамках §0; Protocol не используется — CLAUDE.md его здесь не задаёт):
- Rule(str, Enum) — коды E1..E21 (в этой задаче работают E1, E2, E3, E4, E12, E13, E18, E19, E21; остальные члены объявлены и проверяются в R2.1b); подпись правила для человека — в messages_ru.
- Standard — стандарт из app\tools\code_standard\standard.json: max_definition_lines 30, max_parameters 4, max_module_lines 400, max_class_members 20, module_size_exempt [app\ui\messages_ru.py], список встроенных функций, которые не делают вызов обёрткой (len, bool, str, int, float, tuple, list, set, frozenset, dict, sorted, any, all, min, max, sum); ключи файла — перечисление, не строки по месту.
- SourceTree и ModuleSource — корень репозитория, каждый .py разбирается один раз: путь (ключ всегда с обратной косой чертой: app\x\y.py), текст, дерево ast, пакет, квалифицированные имена определений; SourceTree строится и из словаря «путь -> текст» (образцы в тестах).
- Классы проверок по заботам: FunctionShape (E1, E2, E3, E4, E12, E13), ModuleShape (E18, E19, E21) — каждый отдаёт Measurement своих правил. В R2.1b добавятся CodeValues, CloneFinder, TestShape — оставь для них место в той же форме.
- Measurement — правило и отображение «ключ -> величина» (целое: длина, число параметров, число членов, 1).
- Ledger — реестр app\tests\data\code_standard\debt.json («правило -> ключ -> величина»): load, save, diff(current) -> LedgerDiff (new, grown, shrunk, gone).
- Exceptions — app\tests\data\code_standard\exceptions.json («правило -> ключ -> обоснование»), обоснование — непустая русская строка.
- StandardReport — таблица: правило, подпись, сейчас, в реестре, исключений, цель 0.
- Точные определения правил:
  E1: функция уровня модуля — нарушение, если (а) в аннотациях её параметров или результата назван класс, объявленный в app вне app\tests; или (б) все её использования в коде app — внутри одного класса того же модуля; или (в) в коде app её никто не использует (тесты не считаются). Ложных нарушений правило давать не должно; пропуск из-за совпадения имён допустим и описывается в докстроке правила. Ключ «путь::имя», величина 1; в отчёте виден признак.
  E2: каждый @staticmethod в классе app — нарушение; ключ «путь::Класс.метод».
  E3: от строки def до последней строки определения, включая докстроку, больше 30 строк; величина — число строк.
  E4: параметров без self и cls больше 4 (позиционные, именованные, *args, **kwargs — каждый по одному); величина — число.
  E12: (а) тело без докстроки — один return вызова, аргументы вызова — ровно параметры функции (без self/cls), каждый по разу и без преобразований, self в вызове не участвует, вызываемое — не встроенная функция из стандарта и не конструктор класса (имя с заглавной буквы или cls); (б) свойство или метод без параметров, тело — return self._<имя>() без аргументов; (в) метод, тело которого — один return вызова свободной функции того же модуля, у которой нет других использований в app.
  E13: аннотация результата tuple[...] с двумя и более элементами, среди которых на верхнем уровне нет «...», — нарушение (tuple[A, tuple[B, ...]] — тоже нарушение).
  E18: модуль длиннее max_module_lines строк (кроме module_size_exempt) — ключ «путь», величина — строки; класс, у которого в теле больше max_class_members определений def/async def и полей с аннотацией, — ключ «путь::Класс», величина — число.
  E19: в __init__.py допустимы только докстрока, from __future__, импорты и присваивание __all__; ключ «путь», величина — число прочих операторов.
  E21: имя верхнего уровня определено в модуле больше одного раза (def, class, присваивание); @overload и вложенные имена не считаются; правило обходит весь app, включая app\tests (как прежний тест); ключ «путь::имя».

ПЕРЕНОС:
- app\tests\test_module_definitions.py::find_duplicate_definitions, _app_modules, _is_overload -> правило E21 (ModuleShape); три теста файла -> образцы чувствительности E21 в test_code_standard.py; файл test_module_definitions.py удаляется. Поведение проверки сохраняется как есть.

ШАГИ:
1. Назови объекты и поля, которые создаёшь. Создай пакет app\tools\code_standard\ (__init__.py с докстрокой, __main__.py для python -m, модули пакета по заботам) и standard.json. Пакет из app импортирует только себя и app.ui.messages_ru и работает на Python 3.10 без пакетов проекта (так его запускает Коворк на машине Артура): нет StrEnum, tomllib, typing.Self вне TYPE_CHECKING, datetime.UTC, ExceptionGroup, except* и синтаксиса 3.11+.
2. Пакет с первого дня пишется без литералов в телах функций и без чисел по месту: ключи standard.json и реестра — перечисления, тексты — messages_ru, пороги — standard.json (правило E5 появится в R2.1b и сразу проверит сам замок).
3. SourceTree, ModuleSource, правила E1, E2, E3, E4, E12, E13, E18, E19, E21 по определениям выше; обход app без app\tests и __pycache__; E21 обходит и app\tests, как прежний тест.
4. Ledger, Exceptions, StandardReport.
5. Команды python -m app.tools.code_standard: без флагов — отчёт, код 0; --init — создать реестр, только если его нет; --write-debt — переписать реестр по текущему коду, только если ничего не появилось и не выросло (иначе список роста, код 1); --compare <git-ref или путь к файлу реестра> — добавленное и выросшее против прежнего реестра — список и код 1, снятое — список (git — через subprocess, git show <ref>:app/tests/data/code_standard/debt.json); --files <пути> — долги этих файлов. Тексты вывода и справки флагов — в app\ui\messages_ru.py, коды выхода — своё перечисление пакета.
6. app\tests\test_code_standard.py: (а) по каждому правилу этой задачи нет нового и выросшего относительно реестра и исключений; (б) нет устаревших записей реестра — сообщение называет команду --write-debt; (в) каждое исключение ещё ловится правилом и имеет непустое обоснование; (г) чувствительность — для каждого из 9 правил образец-нарушитель и чистый образец строками в тесте через SourceTree из словаря, замок находит ровно ожидаемое; (д) пакет app\tools\code_standard\ не имеет ни одного долга; (е) пакет импортирует из app только себя и app.ui.messages_ru; (ж) ключи реестра — с обратной косой чертой при любом разделителе ОС; (з) Ledger.diff и отказ --write-debt при росте; (и) пакет не использует возможностей Python 3.11+ из шага 1 (разбор ast самого пакета).
7. Выполни --init. В exceptions.json занеси только те пункты списка ИСКЛЮЧЕНИЯ, которые правило действительно ловит; лишнее исключение — падение теста.
8. Сверь числа отчёта с разделом ФАКТЫ. Расхождение больше единиц — найди причину: изменения R1.1 (назови) или ошибка сканера (почини сканер). Каждое расхождение — строкой в отчёте.
9. Нарушения, которые замок нашёл в коде app, не чинить: они уходят в реестр.

ИСКЛЮЧЕНИЯ (exceptions.json; обоснование — как написано; по сверке Коворка правило ловит каждое из них):
- E1: app\core\safe_trim.py::safe_trim_right — «чистое преобразование, названное в CLAUDE.md §0»;
- E1: app\observability\logging_setup.py::mask_stream_key — «нужна контуру B (CLAUDE.md §6, инвариант 6)»;
- E1: app\core\dates.py::parse_iso_start — «нужна контуру B (CLAUDE.md §4)»;
- E13: app\setup\fields\language_choice.py::LanguageOption.sort_key, app\slots\slot.py::SlotKey.sort_key — «ключ сортировки (REFACTORING_STANDARD.md, E13)».
Точки входа (app\main.py::run_cli, main пробников), normalize_handle и parse_sheet_datetime правило E1 не ловит: они используются в коде app, в exceptions.json их нет.

SCOPE LOCK:
- создать: app\tools\code_standard\ (любые модули пакета), app\tools\code_standard\standard.json, app\tests\test_code_standard.py, app\tests\data\code_standard\debt.json, app\tests\data\code_standard\exceptions.json;
- изменить: app\ui\messages_ru.py — только добавить тексты замка;
- удалить: app\tests\test_module_definitions.py.
DO NOT TOUCH: всё, что не в SCOPE LOCK, в том числе D:\_projects\restreamer, D:\_projects\broadcaster, D:\_projects\planers, CLAUDE.md, README.md, requirements.txt, REFACTORING.md, REFACTORING_STANDARD.md и весь остальной код app (замок только читает код).

ПРОВЕРКИ (PowerShell из корня репо):
- до начала и после: .\.venv_livecraft\Scripts\python.exe -m pytest app\tests -q
- .\.venv_livecraft\Scripts\python.exe -c "import app.main"
- .\.venv_livecraft\Scripts\python.exe -m app.tools.code_standard — отчёт, код 0; весь вывод — в раздел 4 отчёта
- .\.venv_livecraft\Scripts\python.exe -m app.tools.code_standard --write-debt сразу после --init — реестр не изменился (git diff по debt.json пуст)
- после коммита: .\.venv_livecraft\Scripts\python.exe -m app.tools.code_standard --compare HEAD — ничего не добавлено
- Measure-Command { .\.venv_livecraft\Scripts\python.exe -m pytest app\tests\test_code_standard.py -q } — не больше 15 секунд
КОММИТ: после зелёных проверок — один коммит в feature/livecraft, сообщение "R2.1a: замок эталона — каркас, реестр долгов, правила формы функций и классов", без Co-Authored-By. Push и теги не делать.

РЕЖИМ — ПОЛНАЯ АВТОНОМИЯ. Ты работаешь под управлением Коворка (Claude Cowork); Артур только ставит цели и принимает итог. Вопросов по ходу не задавай, подтверждений не жди, работу на середине не останавливай — выполни задачу целиком за один проход.
Все технические вопросы решаешь сам и до конца:
- символ, путь или сигнатура не такие, как в промте, — найди фактический эквивалент grep'ом по текущему коду и работай с ним;
- тест падает — найди причину и почини в пределах SCOPE LOCK; падение, которое было до тебя и лежит вне области, — в отчёт, не чинить;
- неясно, как вызвать или устроить, — прочитай соседний код и выбери решение, совместимое с текущим кодом и CLAUDE.md;
- промт расходится с кодом в мелочи (имя, сигнатура, порядок) — следуй коду и CLAUDE.md, расхождение — в отчёт.
Каждое такое решение — одной строкой в разделе отчёта «Решил сам».
Останавливаться можно только в трёх случаях: (а) нужно изменить контракт или инвариант CLAUDE.md; (б) нужно править файл вне SCOPE LOCK или из DO NOT TOUCH; (в) проблема не решилась ни одним из испробованных способов. Тогда эту часть не обходи и не заглушай, всё остальное доделай, а в разделе отчёта «Нужно решение» опиши: что мешает, какие способы пробовал и чем кончился каждый, что предлагаешь.
Вместо решения запрещено: заглушки, pass или TODO на месте логики, skip и xfail, ослабление проверок в тестах, перехват Exception вне main.run_cli, новые зависимости, «временные» обходы.

КОД — В СТИЛЕ ООП (объектно-ориентированное программирование), CLAUDE.md §0. Это условие приёмки: процедурный код не принимается даже с зелёными тестами.
- Данные и правила над ними живут вместе, в объекте предметной области (SheetPlan, SheetRow, SourceVideo, StreamSlot, PlannedBroadcast, Channel, KeyForm, Vault и т.д.). Объект сам себя проверяет, сам решает и сам строит свою запись.
- Правило, которое переводит один объект в другой, — метод объекта-владельца правила, а не функция по месту вызова.
- Новая проверка — новое поле и правило в самом объекте, а не функция рядом с вызовом.
- Состояние — в полях объекта, а не в кортежах и словарях, которые передаются между функциями. Много связанных параметров — объект запроса или конфига, а не длинный список аргументов.
- Объект с незаполненными полями не выбрасывается и не чинится молча: причина — подробно в лог, кратко в консоль; дальше по конвейеру он не идёт.
- Свободная функция — только чистое преобразование без знания о предметных объектах (normalize_handle, safe_trim, parse_sheet_datetime). Любое другое исключение — строкой-обоснованием в отчёте.
- Класс без своих данных со статическими методами, «менеджер» или «хелпер» поверх процедуры — не ООП. Глубокое наследование не нужно; общий интерфейс — Protocol или базовый класс только там, где его задаёт CLAUDE.md.
- Образец: D:\_projects\planers\app\pipeline\plan.py::PlannedBroadcast. Из restreamer переносятся поведение и правила, но не форма кода.
- Перед правкой назови объект и поля, которые меняешь.

ОТЧЁТ В КОНЦЕ — обязателен, разделы в этом порядке:
1. Изменённые файлы: каждый файл полным путём и что в нём изменилось.
2. Объекты и поля: какие классы, поля и методы добавлены или изменены.
3. Решил сам: каждое самостоятельное решение одной строкой — что встретил, что выбрал, почему.
4. Проверки: команды и итог pytest до и после — «новых падений относительно baseline нет» либо список падений с причинами; результаты задачных проверок.
5. Новые вызовы reveal(): каждый с обоснованием (CLAUDE.md §7.4) либо «нет».
6. Замечено вне области: что увидел, но не трогал, либо «нет».
7. Нужно решение: только случаи (а), (б), (в) либо «нет».
8. Коммит: хеш и сообщение.
```

**План R2.1b.** Коворк пишет этот промт после приёмки R2.1a, на принятом каркасе и в той же форме.

- **Правила.**
  - E5 — с разбивкой по видам в отчёте: лог, идентификатор, разделитель, текст, число.
  - E6 — разрешённые модули: `app\ui\messages_ru.py`, `app\core\alphabet.py`.
  - E7 — пока только `raise` с литералом; проверку контракта ошибок добавит R3.5a.
  - E8 — по уточнённому определению раздела 5 (строки — по значению, числа — по имени и значению); E9, E10.
  - E11 — окно 3, от 40 узлов; пороги в `standard.json`.
  - E14 и E15 — список модулей-границ из раздела 5.
  - E16 — карта в `standard.json`, уровни по разделу 5.1 `REFACTORING.md` с П1 и П2:

    | Уровень | Пакеты | Может импортировать |
    |---|---|---|
    | 0 | `core`, `version` | ничего из app |
    | 1 | `paths`, `observability`, `resources`, `ui` | уровень 0; `ui\messages_ru` — ничего |
    | 2 | `run`, `runtime` | 0–1 |
    | 3 | `secretsafe`, `config`, `google` | 0–2 |
    | 4 | `slots` | 0–1 |
    | 5 | `packages` | 0–4 |
    | 6A | цепочка `texts` → `sheets` → `sources` → `llm` → `intake` | 0–5 и предыдущие звенья цепочки |
    | 6B | `platforms`, `form`, `records`, `pipeline`, `output` | 0–5, контур A — никогда |
    | 7 | `setup`, `main`, `tools` | всё; `tools\code_standard` — только себя и `ui.messages_ru` |

    Кольца модулей запрещены.
  - E17 — модуль времени `app\core\clock.py`; пока его нет, все 11 мест — долг.
  - E20 — по разделу 5; имена файлов `livecraft.json`, `livecraft.exe` — не имена логгеров.
- **Семь тестов с обходом исходников (П10)** переводят обход на `SourceTree`; их утверждения не меняются. Проверка «core ничего не импортирует вне core» становится частным случаем E16.
- **Ожидаемые числа** — по разделу 5. Чувствительность проверяется для каждого нового правила. Сам замок остаётся без долгов, в том числе по E5.

---

## 12. Сверка Коворка с кодом (25-09-2026)

Коворк перепроверил разделы 3–5 и 11 по коду `50b4217` разбором ast на машине Артура (Python 3.10, прямо на репозитории) и исправил по месту:

- **Совпало ✔:** 112 модулей / 18 060 строк; свободные функции 163 (94); E1 (а) 25 и (в) 7; E2 — 59; E3 — 9 с тем же списком; E4 — 7 с тем же списком; E5 — 1027 строк и 20 чисел (16 двоек), таблица модулей N1; E6 — 46 в 8 модулях по тем же строкам; E7 — 58; E9 — 9 / 31, в функциях ни одного; E10 — 35; E15 — 97; E18 — те же 4 модуля и 8 классов; E19 — 1; E20 — 7 файлов, 11 импортов, 20 строк; E21 — 0; 166 / 10 dataclass, 47 перечислений; все строки N5, N7, N12, N14.
- **Исправлено:** E1 (б) — 35, а не 30 (добавлены `_flag` ×2, `blocks.py::_lines`, два помощника `source_probe.py`); E2 — 40 классов; E7 — определение: литерал любым прямым аргументом (так и выходит 58); E8 — определение уточнено, 36 ключей / 174 объявления; E11 — 6 групп / 13 мест при окне 3 и 40 узлах; E12 — ровно 7; E13 — 16, два ключа сортировки — исключения; E14 — 21 вне границ (148 всего), N9 переписан; E15 — 82 вне границ; E16 — 8 рёбер и 5 колец модулей (N16); E17 и N6 — 11 мест; N4 — `DescriptionLayout._collapse` не копия `collapse_spaces`; повтор текста в `messages_ru` один («нет» ×4).
- **Решено Коворком:** замок работает на Python 3.10+ (запуск прямо на репозитории без снимка); E21 проверяет и `app\tests\`, как прежний тест, — иначе проверка тестов пропала бы; в R2.1a в `exceptions.json` идут только исключения, которые правило действительно ловит; `runtime` — уровень 2 карты; `RunLog.open` получает папку логов; вход `MergeJob` после R4.1b — ключ слота и видео (N17).
- Промт R2.1a после приёмки R1.1 сверяется ещё раз: R1.1 правит `crypto.py`, `dpapi.py`, `auth.py`, `loader.py` и сдвигает E5 и E7.
