# REFACTORING.md — доводка рефакторинга livecraft

Составил Коворк 25-09-2026 по коду `50b4217` (ветка `feature/livecraft`, после задачи 3.14c).
Документ — разбор всего кода и план этапа R «доводка рефакторинга». Требования к коду и продукту по-прежнему задаёт
`CLAUDE.md`; при расхождении прав он. Каждая задача R перед промтом перепроверяется grep'ом по текущему коду: номера
строк ниже — на дату снимка.

Обозначения: **✔** — проверено Коворком лично по коду (и, где сказано, по донору `D:\_projects\restreamer`, коммит
`35324e5`); без знака — найдено разбором кода по областям с номерами строк, подтверждается при нарезке задачи.

---

## 0. Итог

**Что уже хорошо.** Методы короткие: длиннее 30 строк только 9 из ~1400. Классов-«хелперов» без данных нет. Перехват
`Exception` один — в `main.run_cli`. Секреты держатся (`reveal()` только в разрешённых местах). Правила merge и санации
совпадают с донором на сверках 3.11–3.14. Объекты предметной области есть почти везде.

**Что не доведено.** Прошлый рефакторинг перевёл код в объекты *по месту*, но не собрал **общее**. В каждом модуле
заново объявлены одни и те же вещи: имена логгеров (35 раз), «да/нет/пусто» для строк лога, переводы строк и
разделители, шаблоны пробелов, абзацев, хештегов, кириллицы; три копии цикла повторов сетевых обращений; четыре копии
правила «строка — пункт»; ссылка разбирается заново в каждой функции; лексиконы местами лежат в коде. Отсюда пять
системных дыр:

1. **Нет общих объектов нижнего слоя** — повторяющиеся конструкции живут копиями (раздел 4).
2. **Слои и шов §4 нарушены**: оркестратор контура A лежит в пакете шва `app\slots`, `StreamSlot` зависит от
   `app\sources`, коды выхода — в пакете настройщика (раздел 5).
3. **Допуск выражен флагами, а не типом**: допущенный ряд и отсеянный — один класс с `Optional`-полями, поэтому ниже по
   цепочке 14 проверок `metadata is not None` и `or ""` над гарантированными значениями.
4. **Крупные процедурные остатки**: `app\config\loader.py` (876 строк, 19 свободных функций и парсер из 24 методов),
   `app\main.py` (18 свободных функций), `app\core\url_text.py` (14 функций над одной строкой-ссылкой),
   `MergedDescription` (24 члена, пять разных забот).
5. **Правила утекли в вид**: логика выбора языка канала и жизненный цикл сейфа живут во вкладках Tk.

**Найдено 7 настоящих дефектов** (не формы, а поведения) — раздел 3; один из них роняет запуск и окно настройщика.

**План** — этап R из 25 задач в восьми волнах (раздел 8): исправления → страховочная сетка тестов → общие объекты →
слои и запуск → контур A и конфиг → merge → настройщик → завершение. Поведение merge и санации не меняется: каждая задача,
которая их касается, доказывает это сверкой с донором. Решений Артура план не требует (раздел 9). После этапа R — 3.14b и
3.15.

---

## 1. Как проводился разбор

- Снимок кода `50b4217` целиком (112 модулей кода — 18 060 строк; 77 модулей тестов — 18 849 строк, 1510 тестовых
  функций, 2473 случая).
- Метрики по всему `app\` разбором синтаксиса (ast): дубли констант по значению, свободные функции, пересылки, клоны
  тел функций и повторяющиеся последовательности операторов, длины методов, кортежи-состояния, литералы в телах функций,
  кириллица вне `messages_ru`.
- Чтение кода целиком по семи областям: merge (ответ и проверка), merge (исполнение) и разъём нейросети, тексты + core +
  инфраструктура, конфиг + сейф + запуск, настройщик, контур A (таблица, источники, слоты, пакет, пробники), тесты.
- Проверка Коворком ключевых находок по коду и донору (знак ✔).

---

## 2. Картина в цифрах

| Показатель | Сейчас | Цель этапа R |
|---|---|---|
| Свободные функции уровня модуля | 163 (94 публичных) ✔ | только чистые преобразования без знания о предметных объектах (§0) |
| Объявления имени логгера (`LOGGER_NAME` / строка в `get_logger`) | 35 (18 констант `LOGGER_NAME`) ✔ | 0 — одно перечисление `LogArea` |
| `_flag` / `YES`, `NO` / «пусто» в логе (`"none"`, `"-"`) | 4 / 6 пар / 23 ✔ | по одному источнику |
| Одинаковые регулярные выражения в разных модулях | 9 шаблонов, 31 объявление ✔ | 0 |
| Переводы строк и разделители (`"\n"`, `"\n\n"`, `","`, `", "`) | 16 + 12 + 16 + 11 ✔ | по одному источнику на смысл |
| `"utf-8"` объявлено константой | 10 модулей ✔ | 1 |
| Защитные `str(x or "")` над значениями типа `str` | 88 в 30 модулях ✔ | 0 вне границы с внешними данными |
| Методы и функции длиннее 30 строк | 9 ✔ | 0 |
| Функции, возвращающие разнотипный кортеж | 16 ✔ | только ключи сортировки |
| Методы `log_line` / `log_lines` / `summary_line` на f-строках | 46 ✔ | строка лога — объект `LogEvent` |
| Циклы повторов сетевых обращений | 3 копии ✔ (четвёртая придёт с YouTube) | 1 — `RetryLoop` |
| Классы исключений / стилей текста ошибки | 8 / 3 (русский, английский, машинный) ✔ | один контракт `ExplainedError` |
| Проверки `metadata is not None` над готовым источником | 11 ✔ | 0 — свойства `SourceVideo` |
| Модули тестов, импортирующие другие модули тестов | 7 файлов, 11 импортов ✔ | 0 — пакет `app\tests\fixtures\` |
| Имена логгеров строкой в тестах (`"livecraft.llm"` и т. п.) | 20 ✔ | 0 |
| Нарушения слоёв (раздел 5) | 5 групп ✔ | 0, держит `test_architecture.py` |

---

## 3. Дефекты поведения — чинятся первыми (задача R1.1)

**D1 ✔ Ссылка на форму с «]» роняет запуск и окно настройщика.**
`app\config\loader.py::FormSettings.url_problem:301` зовёт `urlsplit(self.url)` без перехвата. На
`https://docs.google.com]/forms/x` Python бросает `ValueError: Invalid IPv6 URL` (проверено). Его не ловят ни
`app\setup\readiness.py::Readiness.check` (ловит `ConfigError`), ни `app\setup\panels\settings_panel.py::SettingsPanel.apply`.
Итог: запуск падает с трассировкой и кодом 1 вместо строки «исправьте ссылку в настройщике», кнопка «Сохранить» в окне
бросает исключение. Та же ошибка, что у донора со ссылкой `https://[bad` (исправлена в 3.12b в
`app\core\url_text.py::split_url`). Исправление: разбор через `split_url`; `None` → `SettingProblem` ссылки; тест.

**D2 ✔ Текст отправляет нажать несуществующую кнопку.** `app\ui\messages_ru.py::SETUP_INPUT_EMPTY:275` —
«нажмите «Сбросить к поставке»». Такой кнопки нет: подпись сброса — `SETUP_KEYS_BUTTON_RESET_TO_SUPPLIED`
(«Вернуть значение программы») или `SETUP_KEYS_BUTTON_DELETE_OWN` («Удалить своё значение»), выбирает
`app\setup\panels\keys_panel.py::KeyRow._reset_label`. Исправление: текст берёт подпись из строки поля; своего значения
нет — текст без совета про сброс. Докстрока `app\secretsafe\store.py:81` — туда же.

**D3 ✔ Токен входа пишется не атомарно, а сбой записи называется «не читается».**
`app\google\auth.py::GoogleLogin.save:135-141` пишет `write_text` напрямую: оборванная запись оставит испорченный токен,
и следующий запуск получит `TOKEN_UNREADABLE`. Сбой записи и удаления (`save`, `drop`) тоже докладывается как
`AuthErrorReason.TOKEN_UNREADABLE` — человек получит неверную подсказку. Исправление: `app\paths.py::write_text_atomically`;
причина `TOKEN_UNWRITABLE` с русским текстом.

**D4 ✔ Английский технический текст на экране.** `VaultFormatError` (`app\secretsafe\crypto.py`, 23 места `raise`
с английскими строками вида `field 'x': 'nonce' must be 12 bytes`) и `DpapiUnavailable`
(`app\secretsafe\dpapi.py:102,120`) попадают в человеческие строки через `{error}`: `msg.VAULT_FILE_BROKEN`
(`app\setup\readiness.py:229`, `app\setup\tabs\keys_tab.py:247`, `app\tools\sheets_probe.py:106`,
`app\tools\llm_probe.py:132`) и `msg.READINESS_GAP_VAULT_BROKEN` (`readiness.py:285`). Исправление: причина — перечисление
(`VaultFormatReason`, `DpapiFailure`) с русским текстом в `messages_ru`; английская подробность — только в лог.

**D5 ✔ Язык канала в `channels.json` проверяется слишком мягко.** `app\config\loader.py::_is_language_code:578`
пропускает любой строчный текст: `"uk-ua"`, `"ukr"`. Язык слота — всегда двухбуквенный код
(`app\sources\language.py::normalize_language`), такой канал молча не получит ни одного слота. Настройщик защищён
списком pycountry, файл, поправленный руками, — нет. Исправление: код языка — известный двухбуквенный код ISO 639-1
(`pycountry`, тот же справочник, что у вкладки), иначе проблема поля с понятным текстом.

**D6 ✔ Пробник источников идёт не тем путём, что программа.** `app\tools\source_probe.py::SourceProbe._probe:177-179`
качает обложку, даже если язык не определился; боевой путь `app\sources\video.py::SourceCatalog._video:171-184` качает её
только источнику с языком. Докстрока пробника обещает «тем же путём». Исправление: то же правило (полностью уходит в
общий объект задачей R5.1).

**D7 Число паузы «nan» получает неверный текст.** `app\setup\fields\settings_draft.py::SettingsDraft._pause_seconds:96`
отсекает нечисло своим правилом с текстом `CONFIG_PROBLEM_NUMBER_MIN`, хотя у загрузчика есть точный
`CONFIG_PROBLEM_NUMBER_FINITE` (`loader.py::_ConfigParser._number:775`). Исправление: правило одно — у загрузчика.

---

## 4. Сквозные проблемы и общие объекты

Здесь собрано то, что повторяется по всему коду. Для каждой темы — факт, общий объект, что уходит.

### 4.1 Логи

**Факт ✔.** Имя логгера объявлено 35 раз тремя способами: строкой в `get_logger("llm")` (9 модулей merge,
`"texts"` ×3, `"vault"` ×2), константой `LOGGER_NAME` в 18 модулях, где она нужна только следующей строке, с аннотацией
типа и без. Словарь значений в строках лога заново объявлен в каждом модуле: `_flag` — 4 одинаковые функции
(`app\llm\merges\attempt.py:74`, `check.py:78`, `job.py:67`, `publication.py:63`), `YES`/`NO` — 6 пар, «пусто» — `"none"`
×11 и `"-"` ×12, разделитель списка `","` ×16. Строки лога собираются руками в 46 методах `log_line` / `log_lines` /
`summary_line` на f-строках и около 110 шаблонах `key=%s`; вывод пачки строк циклом
`for line in X.log_lines: LOGGER.info("%s", line)` — 5 раз.

**Общие объекты** (`app\observability\`):
- `LogArea(str, Enum)` — области: `LLM`, `SHEETS`, `SOURCES`, `SLOTS`, `INTAKE`, `PACKAGES`, `TEXTS`, `VAULT`, `SETUP`,
  `RUNTIME`, `MAIN`, `AUTH`, `TOOLS`; `get_logger(area)`. Имена в логе не меняются.
- `log_values.py` — один словарь значений: `yes_no(value)`, `LOG_NONE = "none"` (донорское написание — не трогать ради
  сверки логов), `LOG_ABSENT = "-"`, `LOG_LIST_JOINER = ","`, `log_list(values, empty)`.
- `LogEvent` — неизменяемая строка лога «событие key=value»: `of(name, **fields)`, `extended(**fields)`,
  `emit(logger, level)`; одно правило записи значения (bool → yes/no, пусто → «none»/«-» по выбору, Enum → value,
  последовательность → через «,»). Порядок ключей — порядок аргументов; строки донора остаются побайтно.
  Методы `log_line` возвращают `LogEvent`. Отдельная задача в конце (R8.1): она касается всех модулей.

### 4.2 Текстовые примитивы

**Факт ✔.** Один и тот же примитив объявлен заново почти в каждом модуле текста и merge:
- шаблон пробелов `\s+` — 13 модулей; «схлопнуть пробелы и обрезать края» — 18 мест;
- разбивка на абзацы `\n\s*\n` — 4 модуля, плюс ручной разбор вместо `split_paragraphs` в 4 местах;
  `normalize_newlines(x).split("\n")` — 11 мест; «непустые строки без краёв» — 6 реализаций;
- хештег — одно тело `#[^\s#]+` в трёх видах и шести модулях (`analysis_text.py:19` = `description_marks.py:41`;
  `layout.py:24` = `tail.py:26`; `blocks.py:46` = `service_lines.py:39`); правило «абзац — только хештеги» дважды
  (`layout.py::TailBlock._is_hashtags` = `tail.py::is_hashtags_line`);
- класс кириллицы `А-Яа-яЁёІіЇїЄєҐґ` — в 8 шаблонах; `CYRILLIC_PATTERN` / `LATIN_PATTERN` — дважды (`blocks.py`,
  `description.py`); «смысловое слово» `SEMANTIC_TOKEN_PATTERN` — дважды; Жаккар — дважды (`description.py::_jaccard`,
  внутри `paragraphs.py::has_duplicate_paragraphs`);
- заголовок блока «🌐 …:» — два определения (`analysis_text.py::HEADING_LINE_PATTERN` и
  `description_marks.py::is_official_links_heading`), конец предложения `.!?…` — три (`safe_trim.py`, `tail.py`,
  `layout.py`);
- «строка — пункт списка» — 4–7 реализаций в трёх вариантах (`description_marks.py::is_bullet_line`,
  `bullet_marker_for_line`, `publication.py::SanitizedDescription._is_bullet`, `description.py::_line_starts_with_bullet`,
  `quality.py:153`), `f"{marker} "` собирается в четырёх местах при готовом `BULLET_PREFIXES`.

**Общие объекты** (`app\texts\`):
- `paragraphs.py` — единственный дом: `LINE_BREAK`, `PARAGRAPH_BREAK`, `WHITESPACE_RUN_PATTERN`,
  `PARAGRAPH_BREAK_PATTERN`, `collapse_spaces`, `nonempty_lines`, `split_paragraphs`, `unique_by`, `has_duplicate_paragraphs`.
- `hashtags.py` — `HASHTAG_BODY` и собранные из него именованные шаблоны (`IN_TEXT`, `WORD`, `AFTER_SPACE`,
  `RUN_AT_END`), `is_hashtags_line`.
- `alphabet.py` — классы букв и `CoreLanguage` (uk, en, ru — сейчас объявлены дважды:
  `blocks.py::SCRIPT_MIX_LANGUAGES`, `service_lines.py::CORE_LANGUAGES`).
- `similarity.py::TextPair` — `jaccard`, `prefix_ratio`, `semantic_tokens`.
- `description_marks.py::BulletLine` — `marker`, `content`, `is_bullet`, `has_marker_prefix`; варианты донора остаются
  **отдельными именованными методами** (у санации заголовок «🌐 …:» считается пунктом, у проверки ответа — нет; сливать
  нельзя).
- `SENTENCE_END_CHARS` — в `app\core\safe_trim.py` (core не может брать из texts), тексты собирают шаблон из неё.

### 4.3 Ссылки

**Факт ✔.** `app\core\url_text.py` — 14 свободных функций, каждая заново разбирает строку-ссылку; проверка «не
http(s) или без хоста» повторена 6 раз, снятие обрамления — 4, снятие `www.` — 3. Потребители разбирают ссылку в третий
раз: `app\llm\merges\links.py` импортирует голый `urlsplit` и держит свою копию `split_url` (`_url_parts`); обход «ссылки
текста → кандидат → без YouTube» дословно повторён в `links.py:145-148` и `description.py:478-481`. Конструкция
«`SourceUrl.of` → если YouTube без id, пишем строку лога» повторена трижды у вызывающих. Знание «видео YouTube» разнесено
по четырём модулям: хосты — `url_text.py`, id и короткая ссылка — модуль разбора таблицы `sheet_text.py`, адрес watch —
`slots\slot.py`, шаблон id ещё раз — `sources\metadata.py:27`.

**Общие объекты:**
- `app\core\web_link.py::WebLink` (значение: `text`, `parts`) — конструкторы `of`, `unwrapped`, `find_all`; свойства
  `host`, `bare_host`, `is_web`, `is_https`, `has_query`, `is_youtube`, `is_social`, `is_complete`; правила
  `without_tracking`, `display_root`, `key`, `candidate`, `official_display`, `sanitized`. Разные предобработки донора
  (два набора обрамления) — разные именованные конструкторы, без слияния.
- `app\texts\source_link.py::SourceLink` (`url`, `is_youtube`, `dropped_youtube`; `of`, `of_video`) — сам пишет
  донорскую строку `non_authoritative_youtube_tail_url_dropped`. `LinkedText(text, changed_links)` вместо кортежа
  `sanitize_urls_in_text`.
- `app\core\youtube_video.py::YouTubeVideoId` — `of(text)`, `short_url`, `watch_url`; хосты там же. В `sheet_text.py`
  остаётся только разбор таблицы.
- Правило `slot_id` — в `app\slots\slot.py::SlotKey` (сейчас `app\core\dates.py::build_slot_id` гоняет дату по кругу
  «в текст → разбор → в текст», а контракт шва §4 живёт в core).

### 4.4 Повторы сетевых обращений

**Факт ✔.** Один цикл «попытка → счётчик → `has_retry_left` → `delay_sec` → строка лога → `sleep`» написан трижды:
`app\sheets\client.py::SheetsReader.read_values:206-225`, `app\sources\preview.py::PreviewDownloader.download:173-192`,
`app\llm\backends\openai.py::LlmExchange._with_retries:274-293`. Тройка полей `policy`/`rng`/`sleep` объявлена трижды,
`RETRYABLE_STATUSES = {429, 500, 502, 503, 504}` — дважды, `SheetsFailure` и `PreviewFailure` — один и тот же объект
с побайтно одинаковой строкой лога. Контур B (`YouTubePlatform._execute`) принесёт четвёртую копию.

**Общий объект** (`app\core\retry.py`): `RetryLoop(policy, rng, sleep).run(attempt, should_retry, on_retry)` →
`RetryRun` (результат или отказ, число обращений); `AttemptFailure` (`reason`, `status`, `is_retryable`, `error_name`,
`log_line`); `RETRYABLE_HTTP_STATUSES`. Порядок счёта, паузы и строки `*_retry` / `*_failed` остаются как есть.

### 4.5 Ошибки

**Факт ✔.** 8 классов исключений без общего контракта: у `LlmRequestError` и `SheetsReadError` причина — перечисление
с русским `human`; у `ConfigError` причина — готовый текст плюс `kind`; у `AuthError` `str()` машинный; у
`VaultFormatError`, `VaultDecryptError`, `DpapiUnavailable`, `AnotherInstanceRunning` — английский текст (см. D4).
Русский текст отказа замка собирает `main` (`_say_lock_rejected`), а не ошибка. `error.strerror or type(error).__name__`
повторено 4 раза.

**Общий контракт** (`app\core\errors.py`): Protocol `ExplainedError` — `reason: Enum`, `human: str`, `log_line: str`;
`str(error) == error.human` у всех. Protocol, а не базовый класс: §0 разрешает базовый класс только там, где его задаёт
CLAUDE.md. Чистая функция `os_error_reason(error)`. `LlmRequestError` получает неизменяемое значение `LlmFailure`
вместо шести приватных полей и девяти свойств-прокладок (задача R6.4).

### 4.6 Данные и лексиконы в коде

**Факт ✔.** Решение 23 требует выносить встроенные списки донора в ресурсы; не вынесены:
- `app\texts\description_marks.py::CTA_PREFIX_HINTS:49` — основы слов призыва («долуч», «підпис», «подпис»,
  «коментар», «комментар», «comment») и сравнение со строками ресурса по равенству: правка ресурса молча сменит правило;
- `app\llm\merges\links.py::AUTHORITATIVE_CONTEXT_HINTS:156`;
- `app\llm\merges\description.py::SAFE_HOMOGLYPHS`, `LANGUAGE_HOMOGLYPHS:95-108` — карта омоглифов;
- `description.py::SOURCE_LINE_PATTERN`, `SOURCE_DUMP_PAIRS`, `META_LINE_PATTERN` — маркеры пересказа;
- `app\sheets\plan.py::LINK_ALIASES`, `DATE_ALIASES`, `TIME_ALIASES:36-40` — названия колонок шапки таблицы;
- `app\sources\ytdlp.py::PRIVATE_MARKERS`, `UNAVAILABLE_MARKERS:49-50`; `app\sources\language.py::LANGUAGE_ALIASES`,
  `LANGUAGE_PREFIXES:38-48`;
- `app\llm\backends\openai_model.py::MODEL_PRICES`, `MODEL_ALIASES`, `SERVICE_TIER_MULTIPLIERS:87-107`
  (ключи — строки, повторяющие `ServiceTier`; `PRICE_SNAPSHOT_DATE` не используется);
- куски текста промта в коде: `app\llm\merges\source.py::SOURCE_HEADER`, `TITLE_PREFIX`, `DESCRIPTION_PREFIX`,
  `retry.py::INSTRUCTION_HEADER`, `backend.py::PROBE_PROMPT`;
- поставочный `livecraft.json` — данные, а лежит текстом в `app\ui\messages_ru.py::CONFIG_SETTINGS_TEMPLATE:139-184`.

Лексикон `merge_service_hints.txt` — единственный без объекта: имя ресурса объявлено дважды
(`prompt_texts.py:35`, `sources\language.py:33`), файл читается трижды за запуск (`prompt_texts.py:94`, `check.py:99`,
`language.py:106`) и ходит голым кортежем через три слоя ✔.

**Решение.** Всё перечисленное — ресурсы `app\resources\text\` побайтно из донора; у каждого лексикона — объект с
`load()` и своими правилами (`ServiceHints`, `HeaderAliases`, `HomoglyphMap`, `OpenAiPriceBook`, …). Общая конструкция
«нормализовать текст → любая фраза лексикона — подстрока» (`BadHookLexicon.matches`, `OfficialLinkHints.has_context`,
`analysis_text.py:54`) — значение `PhraseLexicon(phrases)` полем лексиконов (композиция). `TextResource.body` — «весь
текст без строки-источника» вместо ручного `path.read_text` в `prompt_texts.py:98-102` и `tools\llm_probe.py:62-65`.

### 4.7 Общие константы

- Кодировка текстовых файлов программы — 10 констант ✔ → `app\paths.py::TEXT_ENCODING`, по умолчанию у
  `write_text_atomically` (кодировка вывода yt-dlp и `PLAINTEXT_ENCODING` сейфа — другой смысл, остаются).
- Имя программы `"livecraft"` — 3 места ✔ → `app\version.py::APP_NAME`.
- Разделители перечня для человека `", "` и `"; "` — 8 объявлений → `messages_ru.LIST_JOINER`, `ITEM_JOINER`.
- «Нет» для человека — 4 текста с одним смыслом → `messages_ru.NONE_TEXT`.
- Единицы времени и точность ISO — `app\core\dates.py`.
- «Временный файл рядом + `os.replace`» — дважды (`paths.py::write_text_atomically`,
  `packages\package.py::SlotPackage._write_atomically`) → `app\paths.py::AtomicFile`.

### 4.8 Лишние обёртки и защитные преобразования

- Тройная пересылка ✔: `CtaLexicon.starts_with_prefix` → `description_marks.py::starts_with_cta_prefix` →
  `paragraphs.py::starts_with_any_prefix` (параметры `use_casefold`, `collapse_whitespace` в коде программы не передаются
  никем). Правило становится телом `CtaLexicon.starts_with_prefix`, две функции уходят.
- Пересылки с одним вызывающим: `PublishGate.has_duplicate_paragraphs`, `MergedDescription.contains_agenda_heading`,
  `PublishHeadings.official_links` / `recommended_materials`, `MergePrompt.contract_block_with(None)`,
  `config\loader.py::load_settings` / `load_channels` (`parse_*(_read_json(path))`),
  `SetupApp.run` → `SetupWindow.mainloop` → `root.mainloop`, свойства `MergeJob.videos` / `language` / `slot_id` / `rules`,
  девять свойств-геттеров `LlmRequestError`.
- `str(x or "")` над значениями типа `str` — 88 мест в 30 модулях ✔. Снимаются в файлах каждой задачи R и итоговой
  зачисткой R8.2; тесты, которые закрепляют `None` (`test_core_safe_trim.py:23`, `test_texts_paragraphs.py:62`,
  `test_texts_analysis_text.py:11`), уходят вместе с ними.

### 4.9 Мёртвый код

Удаляется задачей R1.2. Проверено, что в коде программы не вызывается (только тестами):
- ✔ `app\llm\merges\retry.py::RetryProfile.expanded` с константами `EXPANDED_*`, `MergePromptTexts.expanded_retry` и
  ресурсом `merge_retry_expanded_lines.json`: у донора `_build_expanded_retry_profile` тоже вызывается только из тестов
  (`merge_orchestrator.py` берёт `_standard_expanded_retry_profile` и целевые профили);
- ✔ строка `merge_bullet_count_mismatch` (`attempt.py::MergeAttempt._log_diagnostics:277-282`, `_bullet_line_count`):
  считает маркеры одного и того же нормализованного текста дважды и не срабатывает никогда; у донора
  (`merge_executor.py:223-235`) — то же самое, это не ошибка переноса;
- ✔ `description.py::ECHO_CHECK_PLACEHOLDER` и проверка с ней в `hook_echo_repaired:339` — равна
  `self.has_hook_echo_in_body` (правило смотрит только на абзацы 0 и 1);
- ✔ ветка `MergePromptRefusal` в `job.py::MergeJob._outcome:294` — до промта `skip_reason` уже требует двух описанных
  источников, а `MergePrompt.of` отказывает только при менее чем двух;
- ✔ поля `LlmResponse.usage`, `attempts`, `notes`, `incomplete_reason`, `hit_max_output` и `LlmResponse.log_line` —
  читает только тест; каждый откат и так пишется в лог в `_fall_back`;
- `MergePrompt.source_texts_for_quality`, `MergeSource.quality_text`, `has_description`,
  `PreparedSourceDescription.cleaned_chars`, `QualityDiagnostics.log_line` и поля
  `official_links_heading_mismatch` / `normalization_applied`, `MergeRun.is_stopped`, `RateLimitSnapshot.is_empty`,
  `PRICE_SNAPSHOT_DATE`;
- `reject.py::SOURCE_COVERAGE_CODE_PATTERN`, `VALIDATION_CODE_ALIASES`, `MergeReject.normalized_validation_codes` —
  коды гейта выдаёт только `QualityReasonCode`, ни один не подходит под шаблон и алиасы (перед удалением — grep донора
  по `semantic_source_`);
- `app\core\dates.py::parse_datetime_text`, `parse_local_datetime_text_utc` (к тому же считает время по часам машины,
  а не по `LivecraftSettings.zone` — переносить без пересмотра нельзя), `format_now_local` (замок дважды пишет ту же
  конструкцию сам); `safe_trim.py::align_trimmed_suffix`, `SafeTrimResult.original_length` / `trimmed_length`;
  `sheet_text.py::column_letters_to_index`; `sheets\rows.py::PlanRow.date_text` / `time_text`;
  `sources\metadata.py::canonical_url`; `config\loader.py::LivecraftConfig.served_languages`, `channel_by_handle`,
  `auth_targets`, `AUTH_ALL`, `ConfigError.is_template_needed`, `load_livecraft_config`;
- ✔ фикстура `conftest.py::vault_store` — не использует ни один тест.

Остаются, хотя сейчас без потребителя: `logging_setup.py::mask_stream_key` и `dates.py::parse_iso_start` — их называет
CLAUDE.md для контура B (§6 инвариант 6, §4).

---

## 5. Слои и шов — целевая карта

### 5.1 Карта

| Уровень | Пакеты | Может импортировать из `app` |
|---|---|---|
| 0. База | `core`, `version` | ничего |
| 1. Инфраструктура | `paths`, `observability`, `resources`, `ui` | уровень 0; `ui\messages_ru.py` — ничего |
| 2. Словарь запуска | `run` (новый: `ExitCode`, `RunMode`, `RunPart`, `RunRequest`) | 0–1 |
| 3. Хранилища и доступ | `secretsafe`, `config`, `google` | 0–2 |
| 4. Шов | `slots` (`slot.py`, `texts.py`, `preview.py`) | 0–1 |
| 5. Пакет | `packages` | 0–4 |
| 6A. Контур A | `texts` → `sheets`, `sources` → `llm` → `intake` (новый) | 0–5 и контур A по стрелкам; `publish` — этап 4 |
| 6B. Контур B (этап 5) | `platforms`, `form`, `records`, `pipeline`, `output` | 0–5; контур A — никогда |
| 7. Верх | `setup`, `main`, `tools` | всё |

Правила: контуры A и B друг друга не импортируют (§4); `app\slots` не знает ни таблицы, ни yt-dlp, ни нейросети;
импорт под `TYPE_CHECKING` считается импортом. Карту держит `app\tests\test_architecture.py` (задача R2.1): разбор
импортов ast по всем уровням вложенности; текущие нарушения — явный список долгов, который задачи R сокращают до нуля
(исчезнувший долг, оставшийся в списке, — тоже падение, список не может устареть). После R8.2 карта переносится в
CLAUDE.md §5/§11.

### 5.2 Нарушения сейчас

- ✔ **Оркестратор контура A в пакете шва.** `app\slots\intake.py` импортирует `sheets.client`, `google.auth`,
  `sources.video`, `packages.package`, `config.loader`, `secretsafe.vault`, `setup.run_mode`; при этом
  `packages\package.py` импортирует `slots.slot` — пакеты `slots` и `packages` образуют кольцо. → `app\intake\`
  (`PlanIntake`, `IntakeResult`, `SlotBuilder`, `SlotGroup`, `SlotBuild`).
- ✔ **Шов зависит от контура A.** `app\slots\slot.py::StreamSlot.previews: tuple[Preview, ...]` — тип из
  `app\sources\preview.py` (модуль тянет `requests`, Pillow, `RetryPolicy`); `StreamSlot.of` и `SlotKey.of` принимают
  `SourceVideo`; `app\slots\texts.py::SlotTexts.from_sources` знает `SourceVideo`. Режиму Б (слоты из ZIP) пришлось бы
  импортировать `app\sources`. → значение `Preview` переезжает в `app\slots\preview.py` (загрузчик остаётся в
  `sources`), `StreamSlot.of(key, texts, previews, sources)`.
- ✔ **Коды выхода в пакете настройщика.** `app\setup\run_mode.py::ExitCode` импортируют `app\slots\intake.py` и
  `main`; §16 планировал перенести его в `app\pipeline\runner.py` — тогда контур A импортировал бы контур B. Код выхода
  решается в трёх местах (`IntakeResult.exit_code`, ветки `main`, `ExitCode.combined`), §10 требует одного.
  → `app\run\exit.py::ExitCode` (вес — свойство члена); `IntakeResult` отдаёт факт `IntakeOutcome`, в код его переводит
  уровень запуска. `RunMode`, `RunPart` — тоже в `app\run\`.
- **Детектор языка текста в пакете источников.** `app\sources\language.py::TextLanguageDetector` нужен merge
  (`quality.py`, `service_lines.py`, `check.py`, `attempt.py`), и merge ради него зависит от `app\sources`. →
  `app\texts\language_detector.py`.
- **Внутри merge порядок перевёрнут** ✔: `MergeRules` (правила всего запуска) лежит в модуле одной попытки
  `attempt.py`, санация импортирует его оттуда; `job.py` импортирует `run.py`, `run.py` — `job.py` (кольцо под
  `TYPE_CHECKING`); `description.py` импортирует `quality.py` при выполнении, `quality.py` — `description.py` под
  `TYPE_CHECKING`.

### 5.3 Выбор текстов слота — место для merge

Сейчас ✔ `app\slots\builder.py::SlotGroup.slot()` умеет строить слот только с текстами источников
(`SlotGroup.texts = SlotTexts.from_sources(...).for_youtube(...)`), а `SlotBuild.of` зовёт `group.slot()`: подать тексты
`MergeJob` в сборку некуда, `MergeJob` трижды сам зовёт `SlotTexts.from_sources`. Задача R4.1 делает место:
Protocol `SlotTextsSource.texts_for(group)` с реализациями «тексты источников» и «merge» — 3.15 подключает merge одной
строкой, а `--no-llm` — выбором реализации.

---

## 6. Области: модель сейчас → цель

### 6.1 Запуск, пути, логи, пробники

Сейчас: `app\main.py` — 18 свободных функций; состояние запуска кочует тройкой `(request, paths, readiness)` через шесть
функций; правило «не готово ничего → окно или отказ; готова основа → прогон» лежит в `main`, а не у готовности.
Флаги argparse — литералы, четыре взаимоисключающих bool плюс `RunMode.of` только ради перевода в enum.
`app\paths.py::build_paths` — функция на 32 строки с 22 именами файлов строками по месту; имя файла лога строит
`logging_setup.py:53`. Логи — изменяемый модульный список и пять функций вокруг него. Последовательность «пути → папки →
логи → try/finally закрыть» повторена в четырёх точках входа. Три пробника повторяют `main`, `_say`, `_refuse`,
свои `ProbeExit` (те же 0/1/2) и два разных пути чтения сейфа.

Цель:
- `app\main.py` — объект `Launch(request, paths, console)`: `run` (замок, логи, шапка, перехват), `prepare` (готовность,
  фильтр секретов, перенос ссылки), `service`, `mode`, `setup`; решение шага — `ModeReadiness.next_step` и
  `ModeReadiness.exit_code`; снаружи — одна `run_cli(argv)`.
- `app\run\request.py` — `CliFlag` (флаг и справка из `messages_ru`), `RunRequest.from_argv`; режимы —
  `store_const` в одно поле.
- `app\paths.py::LivecraftPaths(root)` — `locate()`, `ensure_dirs()`, `run_log_file(stamp)`, `code_root()`; имена
  файлов и папок — константы и `DataDir(Enum)`.
- `app\observability\logging_setup.py::RunLog` — `open(paths, debug)`, `protect(vault)`, `close()`, контекстный менеджер.
- `app\ui\console.py::Console` — `say`, `say_lines`, `say_error`, `title`; им пользуются `Launch` и пробники.
- `app\tools\probe.py` — `ProbeLauncher`, `ProbeConsole` (`refuse`, `open_readiness`, `announce_login`); пробники держат
  только свои отчёты; `SourceProbe` работает через `SourceCatalog`.

### 6.2 Конфиг и сейф

Сейчас ✔: `app\config\loader.py` — 876 строк. Правила канала (ник, название, почта, коды языков) — свободные функции с
русскими текстами (`handle_problem`, `account_name_problem`, `_is_google_account`, `_is_language_code`), у
`ChannelConfig` нет `problem`, как у `FormSettings` и `LivecraftSettings`. Всю проверку типов делает процедурный
`_ConfigParser` (24 метода): каждый принимает `mapping, key, prefix`; путь `channels[i].поле` собирается строкой, а вкладка
каналов разбирает его обратно (`channels_panel.py::_field_problem`). Два файла конфигов объектами не существуют — 11
свободных функций, путь передаётся каждой; какой файл сломан, `Readiness` узнаёт сравнением путей. Имя каждого поля JSON
записано строкой в 5–7 местах (кортежи ключей, `to_data`, разбор, `SettingsDraft.to_data`, `settings_tab.FIELD_KEYS` ✔,
словари подписей). Тарифы OpenAI (`ReasoningEffort`, `ServiceTier`) лежат в общем модуле конфига.
Сейф устроен объектно, но правила «своё поверх поставки» и «только поля с происхождением X» живут в `VaultLoad` и
`VaultStore`, а не в `Vault`; `VaultSource` повторяет `VaultOrigin`; три одинаковых разбора base64.

Цель:
- `app\config\json_node.py` — `KeyPath` (части пути, `text`, `field`, `index`), `JsonNode` (типовые читатели, `choice`,
  `items`, `raise_problem`), `JsonObject` (повторы ключей). `_ConfigParser` уходит: каждый объект строит себя сам
  (`from_node`) в пару к `to_data`.
- `app\config\channel.py` — `ChannelHandle` (`key`, `problem`), `ChannelConfig.problem`, `ConfiguredChannels`
  (`problem` — повтор ника, `served_languages`, `by_handle`).
- `app\config\settings.py` — `LlmSettings`, `FormSettings` (`language_codes`, `with_url`), `LivecraftSettings`.
  Ключи — `SettingKey` / `ChannelKey` (значение — путь JSON); кортежи ключей и `to_data` выводятся из полей.
- `app\config\files.py` — `SettingsFile`, `ChannelsFile` (`load`, `parse`, `render`, `save`, `install_shipped`),
  `ConfigFileKind`, `ConfigRead[T]` (значение или ошибка вместо пар полей). Поставочный шаблон — ресурс.
  `loader.py` — фасад реэкспорта (§11).
- `app\secretsafe` — `Vault.overlaid_by`, `only(origin)`, `entry`, `missing_of`; один `VaultOrigin`; `SecretField` с
  `FieldSpec`; `Base64Field`; `VaultFile.new`.

### 6.3 Готовность к запуску

Сейчас: `Readiness._gaps` — switch по `RunPart`; строка о настройках входит в три части, и в режиме «объявления» одна
причина печатается двумя строками (долг §16); правило «пакету нужна ссылка формы» живёт в `Readiness._form_gaps` и
`SlotPackage`, текстов о ней три. Три одинаковых try/except в `check` и три пары полей «значение / ошибка»;
`PartReadiness` держит состояние двумя флагами. `main` сам знает, как логировать каждую ошибку конфига.
Цель: `RunPart.needs` → `Need` (SHEETS_VAULT, OPENAI_VAULT, SETTINGS, FORM, CHANNELS, CLIENT_SECRET); `Readiness.gap(need)`
— единственное место текста, каждая нужда называется один раз; `PartState` (READY / BLOCKED / NOT_BUILT);
`Readiness.log(logger)`, `Readiness.window_line`.

### 6.4 Контур A: таблица, источники, слоты, пакет

Сейчас:
- Допущенный и отсеянный ряд — один `PlanRow` с `Optional` `start` / `link`, годный и негодный источник — один
  `SourceVideo` с `Optional` `metadata` / `language`; ниже по цепочке защиты `or ""` и `ValueError` над гарантированными
  значениями ✔ (11 проверок `metadata is not None`).
- `SourceCatalog` держит три параллельных кеша и три одинаковых метода «кеш → вычислить → положить»; `SourceVideo.of`
  расплющивает итоги получения и теряет подробность.
- Итоги стадий собраны не у владельцев: подсчёт «ряды, допущено, отсеяно по причинам» написан трижды
  (`intake.py::RowTally`, `plan.py::SheetPlan._summary`, пробник); `IntakeResult` решает за чужие объекты, форматирует
  их строки и создаёт `SourceTally` / `RowTally` заново 6 раз ✔.
- `StreamSlot` расплющивает `SlotTexts` и заново считает символы и байты; правило пустого названия — побайтно дважды;
  `sorted(videos, key=row_number)` — трижды, хотя порядок держит `SlotGroup`.
- Причины хранятся готовым русским текстом там, где он не показывается (`SOURCE_NO_TITLE` используется как «не None»).

Цель:
- `app\sheets\rows.py` — `AdmittedRow(row, start, video: YouTubeVideoId)`, `SkippedRow(row, reason, start, duplicate_of)`,
  `PlannedRows` (`admitted`, `skipped`, `counts`, `log_line`, `console_line`); `HeaderAliases` из ресурса.
- `app\sources` — `SourceFacts(fetch, language, preview; refusal, is_ready, log_line)` с одним кешем;
  `PreparedSources` (видео, счётчики, `has_errors`, `console_line`); `SourceVideo.title`, `description`,
  `metadata_url` — единственная проверка метаданных.
- `app\core\counts.py::Counts` — упорядоченные счётчики с `log_text` и `human_text`.
- `app\slots` — `StreamSlot(… texts: SlotTexts …)`: `title`, `description` — свойства; причины — перечисления.
- `app\intake` — `IntakeResult` хранит объекты стадий и только опрашивает их; `SheetsReadReason.is_configuration`.
- `app\packages` — `PackagePeriod` вместо двух свойств-клонов; запись через `AtomicFile`.

### 6.5 Merge и разъём нейросети

Сейчас:
- ✔ `app\llm\merges\description.py::MergedDescription` — 24 члена и пять несвязанных забот (эхо тезиса, призыв в
  начале, омоглифы, оркестровка нормализации качества, ссылки и эмодзи); файл 595 строк.
- ✔ Правила лежат в трёх вложенных «мешках» `MergeRules → MergeCheckRules → QualityRules` (цепочки
  `rules.check.quality.cta`), параметр `detector` протащен через четыре уровня ради одного листа.
- Коды отказа записаны строками в 4–5 местах (`reject.py::RECOVERABLE_REJECT_CODES`, `MergeRejectCode`, `CODE_STAGES`,
  `retry.py::RetrySignal`, `SIGNAL_ORDER`, `_REJECT_SIGNALS`); `MergeSkipReason` повторяет `MergeStopReason`; схема ответа
  `attempt.py::MERGE_RESPONSE_SCHEMA` повторяет ключи и предел длины `answer.py`; формула минимума пунктов — дважды;
  пороги донора лежат то в `rules.py`, то по месту.
- Две оценки ссылки (`OfficialLinkCandidate.score`, `AuthoritativeCandidate.score`), две сортировки и два отсева по ключу.
- `MergeOutcome` копирует поля `SlotKey` и пересчитывает то, что знает `AttemptHistory`; `MergeAttempt` получает три поля
  одного `MergeRun` по отдельности; `MergeAttemptResult` держит «ровно одно из трёх» только в докстроке.
- Разъём: `LlmRequestError` — 6 параметров → 6 приватных полей → 9 свойств-прокладок, разбор параметра `temperature`
  ответа OpenAI лежит в общем объекте (против решения 22); 6 полей токенов объявлены дважды и копируются по одному;
  кольцо `openai` ↔ `openai_response`; `ModelChoice._chosen` вызывается 5 раз с одной парой моделей.
- Кортежи-состояния: `without_non_structural_emoji`, `HookParagraph.split_*`, `DescriptionLayout._split_tail` (три
  списка), `_recover`, `FormattingRecovery._formatted`, `json_text.parse_json_tolerant`.

Цель (поведение и строки лога донора — побайтно):
- порядок модулей снизу вверх: `rules.py` (все пороги) → `merge_rules.py::MergeRules` (плоский: `lexicons`, `texts`,
  `headings`, `gate`) и `MergeLexicons` (загружаются один раз) → промт / проверка / санация → `attempt.py` → `outcome.py` →
  `run.py` → `job.py`; импортов под `TYPE_CHECKING` внутри пакета нет;
- `MergeRejectCode` с одной таблицей признаков `RejectTraits(stage, is_description_validation, is_recoverable)`;
  `RetrySignal` — по `MergeRejectCode`; `MergeAnswer.SCHEMA`; `MergeContract.min_bullets(n)`;
- `MergedDescription` (повторы, строки, пересказ, пункты) + `HookEcho`, `DescriptionOpening`, `EmojiUsage`,
  `script_mix.py` (`ScriptMixProbe`, `HomoglyphMap` из ресурса, `HomoglyphRepair`), `QualityNormalization` в
  `quality.py`; кортежи — значениями (`EmojiCleanup`, `HookSplit`, `TailSplit`, `BodyRecovery`, `FormattedDraft`);
- `LinkCandidate.score` одной формулой и `RankedLinks` для обоих отборов; `SourceDescriptionLines` — один обход описаний;
- `PublicationBody`, `GateVerdict`, `MergePublication(title, description, body, verdict, layout)`; `TailCollector`
  вместо двух накопителей; правила «строка — призыв» и «хвост-призыв» — у `CtaLexicon`, `TailReader` уходит;
- `MergeOutcome(group, texts, history, skipped, recoveries, publish_blocked)`; `MergeRun.request(prompt_text, label)`;
  `MergeAttempt(prompt, label, sources, run)`; `MergeAttemptResult.outcome: AcceptedMerge | RejectedMerge | LlmFailure`;
- `LlmFailure` + `LlmRequestError(failure)`; `TokenCounts`; `LlmResponse(text, structured, model)`; `ModelPair`;
  `openai_request.py`; один цикл flex; `ResponseSchema`; `ParsedJson`.

### 6.6 Тексты и санация

Сверх раздела 4.2–4.3: `app\texts\tail.py::TailReader` держит одно поле `cta`, нужное 2 методам из 5, правило «строка —
призыв» живёт вне `CtaLexicon`; `EmbeddedTail.of` (32 строки) и `TailScan` копят и переливают одни и те же 6 полей;
`official_links.py::official_link_urls` пишет в лог (не чистая функция); `safe_trim_right` — 57 строк, четыре почти
одинаковых блока, причины — строки, доли 0.6 / 0.5 — числа по месту. Цель: `TrimReason`, `TrimBoundary`, цикл по
границам (форма свободной функции остаётся — §0 называет её примером); `TailCollector`; правило ссылок блока — внутри
`OfficialLinksBlocks`.

### 6.7 Настройщик

Сейчас ✔: логика выбора языка канала (сужение списка, Esc, язык не из формы, пополнение каталога) — в
`app\setup\tabs\channels_tab.py::ChannelsTab.type_language`, `restore_language`, `refresh_form_languages` и соседях;
проверить её можно только в окне Tk. `KeysTab` сам открывает `VaultStore`, ловит `VaultFormatError` и держит
`panel=None`. Вкладка каналов сама читает `livecraft.json` через `load_settings`. Какое поле черновика настроек — путь JSON,
перечень, флажок или широкое поле, знает вид (`settings_tab.py::FIELD_KEYS`, `_choices`, `WIDE_FIELDS`). У трёх панелей
три разных API загрузки и записи и три одинаковых класса правки (`ChannelsPanelEdit`, `SettingsPanelEdit`,
`KeysPanelEdit`). Каркас вкладки, строка формы, тема и константы Tk повторены в каждой вкладке. Язык канала ходит по
кругу «кортеж → текст "uk, ru" → разбор → кортеж». Правило «несохранённое» у трёх вкладок разное: окно каналов и ключей
закроется без вопроса при набранном, но не принятом значении.

Цель: модели без Tk — Protocol `SetupPanel` (`title`, `notices`, `is_dirty`, `save() -> PanelEdit`), `PanelEdit[P]`
(`panel`, `problem_line`, `failure`), `KeysPanel.from_paths` (всегда панель, `load_problem`), `LanguagePicker` и
`LanguageDirectory` (pycountry один раз), `DraftField` (`key_path`, `kind`, `choices`, `width`), `ChannelDraft.languages:
tuple[str, ...]`. Вид — `TabShell`, `FormGrid`, `DraftVariables`, `SetupTheme`, `TkEvent`, `SetupWindow.open(paths)`.
Вкладки импортируют только панели, поля, `messages_ru` и тему. Одно правило «несохранённое» для всех вкладок.

### 6.8 Тесты

Сейчас ✔: общий слой — только `conftest.py`; всё остальное каждый файл объявляет заново. Модули тестов merge служат
библиотекой фикстур друг для друга (цепочка `run → job → attempt → check → source`, 7 файлов). Фабрика источника
объявлена 14 раз; перехват лога — около 20 раз с именами логгеров строками; подделки портов (`_FakeFetcher`, `_Response`,
`_Reader`, случайность) продублированы; сейф собирается по месту в 10 файлах; зона Киева — в 8. Семь тестов читают
исходники программы, каждый своим обходом; проверки слоёв нет. `test_llm_merges_check.py::normalized_check` повторяет
шаг `MergeAttempt._checked` вместо вызова программы. Три механизма сверки ресурсов с донором и дословные копии ресурсов
в тестах.

Цель: пакет `app\tests\fixtures\` (`source.py::SourceFactory`, `log.py::LogCapture`, `fake.py`, `llm.py`, `vault.py`,
`merge.py`, `sheet.py`, `slot.py`, `setup.py::SetupWindowDriver`, `scan.py::AppSource`) — единственное место, где тесты
знают форму объектов программы; `test_architecture.py`; единый манифест хешей ресурсов донора в
`app\tests\data\donor\`. Правила: тест-модули не импортируют друг друга; нет `dataclasses.replace` объектов программы
вне фабрик; нет строк `"livecraft.x"`; нет подмен приватных имён и глобальных `os` / `shutil`. Точные строки лога
merge и санации — контракт совпадения с донором (решение 23): рефакторинг формы обязан сохранить их побайтно.

---

## 7. Правила донора, которые выглядят странно — не трогаем

Поведение merge и санации переносится как есть (решение 23). Отмечено, чтобы не принять за дефект:
- `publish_cta_gate_dropped` пишется дважды; `drop_cta` ничего не удаляет, только пишет строку.
- Три правила «ссылка YouTube»: хост из списка, «обрамление + хост», подстрока `"youtu"` (`layout.py::YOUTUBE_MARK`).
- Обрамление ссылки снимается двумя наборами знаков (`sanitize_url` — без фигурных скобок).
- `_core_language_mismatch` считает `unknown` несовпадением, `ServiceLanguage.is_wrong` — нет.
- Второй отказ `CTA_AS_FIRST_PARAGRAPH` в `check.py:346-348` при текущем лексиконе недостижим.
- Три разных поиска имён собственных (`contract.capitalized_runs`, `NAMED_ENTITY_PATTERN`, `PROPER_NAME_PATTERN`) —
  держать рядом, чтобы различия были видны.
- `sheet_text.py::HEADER_JUNK_PATTERN` выбрасывает украинские «і ї є ґ» из шапки таблицы; украинских названий колонок
  сейчас нет — не мешает.
- Повтор `slot_id` в пакете и повтор ссылки в слоте на боевом пути недостижимы (повтор снят `SheetPlan.plan_rows`) —
  рубежи донора, остаются явными инвариантами.

---

## 8. План этапа R

**Правила каждой задачи R** (добавляются в промт сверх обычного шаблона):
- поведение не меняется, кроме явно названного в задаче; строки лога донора — побайтно;
- задача, которая касается `app\llm\merges\` или `app\texts\`, прогоняет сверку с донором на тех же входах (после R2.3 —
  одной командой из репозитория) и доказывает 0 расхождений;
- в изменённых файлах снимаются `str(x or "")` над значениями типа `str` и пересылки с одним вызывающим;
- список долгов `test_architecture.py` сокращается на то, что задача закрыла;
- отчёт называет, какие показатели раздела 2 изменились.

Вид изменений — по §12: исправления → переименования → структурные рефакторинги. Каждая строка ниже — одна задача,
один проход Codex.

### Волна 1 — исправления

| Задача | Что | Находки | Объём |
|---|---|---|---|
| **R1.1** | Дефекты поведения | D1–D7 | M |
| **R1.2** | Мёртвый код | 4.9 | M |

### Волна 2 — страховочная сетка (только тесты и инструмент разработки)

| Задача | Что | Объём |
|---|---|---|
| **R2.1** | `test_architecture.py`: карта слоёв 5.1 с явным списком долгов; туда же — семь разрозненных проверок исходников; счётчики дублей шаблонов и имён логгеров со списками долгов | M |
| **R2.2** | Пакет `app\tests\fixtures\` (6.8); тест-модули не импортируют друг друга; `normalized_check` — через метод программы | L |
| **R2.3** | Сверки с донором 3.11–3.14 из `%TEMP%` — в репозиторий: `app\tools\donor_compare\` (в поставку не идёт, как пробники), одна команда, контроль чувствительности; сейчас доказательство совпадения живёт во временной папке и может пропасть при чистке | M |

### Волна 3 — общие объекты

| Задача | Что | Раздел | Объём |
|---|---|---|---|
| **R3.1** | `LogArea`, словарь значений лога; все 35 объявлений логгеров, `_flag`, `YES`/`NO`, «пусто», разделители лога | 4.1 | M |
| **R3.2** | Текстовые примитивы: `paragraphs.py`, `hashtags.py`, `alphabet.py`, `similarity.py`, `BulletLine`, заголовок «🌐 …:», конец предложения; тройная обёртка префикса | 4.2, 4.8 | L |
| **R3.3** | Ссылки: `WebLink`, `SourceLink`, `LinkedText`, `YouTubeVideoId`; `slot_id` — в `SlotKey` | 4.3 | L |
| **R3.4** | `RetryLoop`, `AttemptFailure`, `RETRYABLE_HTTP_STATUSES` — таблица, превью, OpenAI | 4.4 | M |
| **R3.5** | Контракт ошибок `ExplainedError`; общие константы (кодировка, имя программы, разделители для человека, `NONE_TEXT`, единицы времени), `AtomicFile`, `TextResource.body` | 4.5, 4.7 | M |
| **R3.6** | Данные и лексиконы — в ресурсы, объекты лексиконов, `ServiceHints` (один раз за запуск), `PhraseLexicon`, поставочный шаблон `livecraft.json` | 4.6 | M |

### Волна 4 — слои и запуск

| Задача | Что | Раздел | Объём |
|---|---|---|---|
| **R4.1** | Шов и слои: `app\run\` (`ExitCode`, `RunMode`, `RunPart`), `app\slots` — только шов (`Preview` — значение), `app\intake\` (intake и сборка слотов), `SlotTextsSource`; `TextLanguageDetector` → `app\texts` | 5.2, 5.3 | L |
| **R4.2** | Запуск объектами: `Launch`, `RunRequest`/`CliFlag`, `LivecraftPaths.locate`, `RunLog`, `Console`, общий каркас пробников | 6.1 | L |

### Волна 5 — контур A, конфиг, готовность, сейф

| Задача | Что | Раздел | Объём |
|---|---|---|---|
| **R5.1** | Допуск типом и итоги у владельцев: `AdmittedRow`/`SkippedRow`/`PlannedRows`, `HeaderAliases`, `SourceFacts`/`PreparedSources`, свойства `SourceVideo`, `Counts`, `IntakeResult` опрашивает стадии, `StreamSlot.texts`, `PackagePeriod` | 6.4 | L |
| **R5.2** | Конфиг: `KeyPath`/`JsonNode` вместо `_ConfigParser`, `from_node`, `SettingKey`/`ChannelKey`, `ChannelHandle`, `ConfiguredChannels`, разрезка `loader.py` с фасадом | 6.2 | L |
| **R5.3** | Файлы конфигов и готовность: `SettingsFile`/`ChannelsFile`/`ConfigRead`, `Need`/`PartState`, каждая нужда — одна строка (долг §16 о форме), `Readiness.log` | 6.2, 6.3 | M |
| **R5.4** | Сейф: `Vault.overlaid_by`/`only`/`entry`/`missing_of`, один `VaultOrigin`, `FieldSpec`, `Base64Field`, `VaultFile.new` | 6.2 | S |

### Волна 6 — merge и нейросеть (каждая задача — со сверкой с донором)

| Задача | Что | Объём |
|---|---|---|
| **R6.1** | Порядок модулей и правила: `merge_rules.py`, `MergeLexicons`, `outcome.py`, все пороги в `rules.py`, коды отказа одной таблицей, `MergeAnswer.SCHEMA`, `min_bullets`, `MergeSkipReason`/`MergeStopReason` | L |
| **R6.2** | Описание по заботам: `MergedDescription` + `HookEcho`, `DescriptionOpening`, `EmojiUsage`, `script_mix.py`, `QualityNormalization`; кортежи — значениями | L |
| **R6.3** | Ссылки и санация: `LinkCandidate`/`RankedLinks`, `SourceDescriptionLines`, `PublicationBody`/`GateVerdict`, `TailCollector`, правила призыва у `CtaLexicon` | L |
| **R6.4** | Разъём и попытка: `LlmFailure`, `TokenCounts`, `LlmResponse` без мёртвых полей, `ModelPair`, `openai_request.py`, цикл flex, `ResponseSchema`, `MergeRun.request`, `MergeAttempt(run)`, `MergeAttemptResult.outcome`, `MergeOutcome` поверх `AttemptHistory`, `ParsedJson` | L |

### Волна 7 — настройщик (не блокирует 3.14b и 3.15)

| Задача | Что | Объём |
|---|---|---|
| **R7.1** | Модели: `SetupPanel`, `PanelEdit`, `KeysPanel.from_paths`, `LanguagePicker`/`LanguageDirectory`, `DraftField`, `ChannelDraft.languages` — кортеж, `FormSettings.language_codes`; тесты языка без Tk; `SetupWindowDriver` для тестов окна | L |
| **R7.2** | Вид: `TabShell`, `FormGrid`, `DraftVariables`, `SetupTheme`, `TkEvent`, `SetupWindow.open`; одно правило «несохранённое» для всех вкладок | M |

### Волна 8 — завершение

| Задача | Что | Объём |
|---|---|---|
| **R8.1** | Строка лога объектом `LogEvent` во всех модулях | L |
| **R8.2** | Итоговая зачистка: остатки `str(x or "")`, методы длиннее 30 строк, пересчёт показателей раздела 2; список долгов `test_architecture.py` пуст; карта слоёв и новые пакеты — в CLAUDE.md §5/§11 | M |

**Зависимости.** R1 → R2 → R3.1 (логи нужны всем) → остальное R3 → R4.1 → R4.2, R5 → R6. R3.2 и R3.3 — до R6.
R5.2 — до R5.3 и R7. Волна 7 идёт в любой момент после R5.3. После R6.4 — задачи 3.14b и 3.15 (3.15 подключает merge
через `SlotTextsSource` из R4.1).

**Итого:** 25 задач. Боевых прогонов на этапе R не нужно: поведение держат тесты и сверки с донором. Контрольный прогон
режима А без нейросети (`--no-llm` появится в 3.15; до него — обычный запуск на боевой таблице) — после R5.1, чтобы
увидеть, что пакет и консоль не изменились.

---

## 9. Что решает Артур

Ничего из этого плана не касается списка решений Артура (контракты §0/§4/§6/§7/§14, зависимости, живые каналы, релиз).
Заметные решения Коворка, принятые в плане:
- карта слоёв 5.1 и новые пакеты `app\run\`, `app\intake\`, `app\tests\fixtures\`, перенос значения `Preview` в
  `app\slots\` — это приведение кода к §4 и §10; §5 правится по итогам (R8.2);
- контракт ошибок — Protocol, а не базовый класс (§0);
- мёртвый код донора (строка `merge_bullet_count_mismatch`, профиль `expanded`) удаляется: у донора он тоже не
  срабатывает — поведение не меняется;
- поведение меняется только в дефектах D1–D7 и в правиле «несохранённое» настройщика (R7.2).
