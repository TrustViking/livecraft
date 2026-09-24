"""Все тексты для оператора: консоль, отчёт, файл ключей, настройщик (CLAUDE.md §11).

В коде — только эти константы; английских текстов для человека в коде нет.
Здесь пока только то, что нужно скелету: строки командной строки, шапка запуска,
обрыв и падение, требование настройки. Остальное добавляют свои этапы (§13).
"""
from __future__ import annotations

from typing import Final

# --- командная строка (CLAUDE.md §10)
CLI_DESCRIPTION: Final[str] = (
    "Livecraft: план стримов из Google Sheets → эфиры на YouTube → ключи потоков стримеру."
)
HELP_SETUP: Final[str] = "открыть настройщик: ключи и ссылки, каналы YouTube, настройки запуска"
HELP_DRY_RUN: Final[str] = (
    "прочитать таблицу, собрать слоты и сверить их с YouTube; ничего не создавать, "
    "в форму не отправлять, keys.txt не менять"
)
HELP_NO_LLM: Final[str] = "не звать LLM: взять название и описание источника как есть"
HELP_EXPORT_SLOTS: Final[str] = "выгрузить слоты запуска JSON-ом в указанный файл (отладка)"
HELP_CHECK: Final[str] = "проверить каждый канал: вход, ник и название, языки, число запланированных эфиров"
HELP_AUTH: Final[str] = (
    "заново авторизовать канал (ник handle из channels.json, например @MyChannel) или all — все каналы"
)
HELP_STATUS: Final[str] = "сверка эфиров livecraft, keys.txt и отчёт — без таблицы и без LLM"
HELP_DEBUG: Final[str] = "подробный лог в терминал"
HELP_VERSION: Final[str] = "показать номер версии и выйти"
VERSION_TEXT: Final[str] = "Livecraft {version}"
# Подписи значений в справке argparse: их видит человек, поэтому они здесь, а не в main.py (§11).
CLI_METAVAR_PATH: Final[str] = "ПУТЬ"
CLI_METAVAR_HANDLE: Final[str] = "НИК"

# --- шапка запуска: первая строка любого запуска, время — то же, что в отчёте этого запуска
CONSOLE_TITLE: Final[str] = "Livecraft {version} — {generated_at}"

# --- настройка программы (CLAUDE.md §8): без сейфа и конфига обычный запуск не начинается
# Что именно не так, перечислено строками выше (сейф и конфиги называют свои причины сами) — здесь только что делать.
SETUP_REQUIRED: Final[str] = "Запустите livecraft.bat --setup и заполните настройки."

# --- готовность к запуску (app\setup\readiness.py): сводка без значений — только откуда что взялось (§7.4)
READINESS_SUMMARY_TITLE: Final[str] = "Настройки livecraft:"
READINESS_FIELD_LINE: Final[str] = "  {label}: {origin}"
READINESS_FIELD_ABSENT: Final[str] = "нет"
READINESS_CHANNELS_LINE: Final[str] = "  каналов: {count}, языки стримов: {languages}"
READINESS_CHANNELS_ABSENT: Final[str] = "  каналы: не прочитаны"
# Личный сейф есть, но не читается: молчаливый откат на поставку недопустим (§16) — иначе получатель
# незаметно работает на ключе OpenAI и таблице того, кто передал ему программу.
VAULT_LOCAL_UNREADABLE: Final[str] = (
    "ВНИМАНИЕ: ваши собственные ключи и ссылки не прочитаны — программа работает на значениях, пришедших "
    "вместе с ней (ключ OpenAI, таблица плана, форма ключей). Так бывает после переноса программы на другой "
    "компьютер или смены пользователя Windows. Введите свои значения заново: livecraft.bat --setup."
)
VAULT_FILE_BROKEN: Final[str] = (
    "Ключи и ссылки не читаются: {error}. Если это vault.local.dat — введите свои значения заново через "
    "livecraft.bat --setup; если vault.dat — переустановите программу."
)

# --- конфиги (CLAUDE.md §5): два JSON, все поля обязательные, умолчаний и копирования примеров нет
CONFIG_ERROR: Final[str] = "Ошибка в конфиге {path}: {key} — {problem}"
CONFIG_ROOT_KEY: Final[str] = "(корень файла)"
CONFIG_CHANNELS_HINT: Final[str] = "Создайте файл {path} с таким содержимым и впишите свои значения:"
# Что вписать в каждое поле: печатается между CONFIG_CHANNELS_HINT и шаблоном.
# {languages} — CONFIG_LANGUAGES_RULE, {privacy} и {platform} — допустимые значения из config\loader.py.
CONFIG_CHANNELS_FIELDS: Final[tuple[str, ...]] = (
    "  account_name — название канала как на YouTube: оно уходит в форму как «Название канала»;",
    "  handle — ник канала на YouTube, начинается с @ (Студия -> аватар вверху справа); "
    "ник и название программа потом выравнивает сама;",
    "  google_account — почта аккаунта Google, в котором этот канал;",
    "  languages — языки стримов этого канала: {languages};",
    "  privacy — видимость эфиров: {privacy};",
    "  platform — {platform}.",
)
CONFIG_LANGUAGES_RULE: Final[str] = 'непустой список кодов строчными буквами без повторов, например ["uk"] или ["uk", "ru"]'
CONFIG_SETTINGS_HINT: Final[str] = "Восстановите файл {path} с таким содержимым и впишите свои значения:"
# Точные шаблоны файлов для консоли: печатаются, когда файла или поля нет. В код как умолчания не идут.
# Шаблон настроек совпадает с поставочным secrets\livecraft.json — это проверяет тест.
CONFIG_CHANNELS_TEMPLATE: Final[str] = """{
  "channels": [
    {"platform": "youtube", "account_name": "Название канала на YouTube", "handle": "@ник_канала", "google_account": "you@gmail.com",
     "languages": ["ru"], "privacy": "unlisted"}
  ]
}"""
CONFIG_SETTINGS_TEMPLATE: Final[str] = """{
  "min_lead_minutes": 60,
  "keep_days": 30,
  "auto_start": true,
  "set_thumbnail": true,
  "category_id": "22",
  "youtube_pause_seconds": 0.5,
  "image_dir_template": "{date}/{language}",
  "timezone": "Europe/Kyiv",
  "llm": {
    "model": "gpt-5.6-sol",
    "fallback_model": "gpt-5.4",
    "reasoning_effort": "medium",
    "service_tier": "flex",
    "timeout_sec": 900,
    "max_output_tokens": 8000
  },
  "form": {
    "fields": {
      "language": "Язык стрима ( Language of stream)",
      "account_name": "Название канала ( Channel name)",
      "date": "Время стрима ( Stream time )",
      "platform": "Платформа (Platform)",
      "stream_key": "You Tube Stream Key",
      "stream_url": "Stream-URL (YT)",
      "time": null,
      "broadcast_url": null,
      "slot_id": null
    },
    "values": {
      "language": {
        "uk": "Украинский ( Ukranian)",
        "ru": "Русский ( Russian)",
        "en": "Английский ( English)",
        "hu": "Венгерский (Hungarian, Magyar)"
      },
      "platform": {
        "youtube": "You Tube",
        "facebook": "Facebook",
        "rumble": "Rumble"
      }
    },
    "date_format": "%d.%m.%Y"
  }
}"""
CONFIG_PROBLEM_FILE_MISSING: Final[str] = "файла нет"
CONFIG_PROBLEM_JSON: Final[str] = "файл не читается как JSON: {error}"
CONFIG_PROBLEM_NOT_MAPPING: Final[str] = "нужен объект JSON в фигурных скобках"
CONFIG_PROBLEM_MISSING_KEY: Final[str] = "обязательное поле отсутствует"
CONFIG_PROBLEM_UNKNOWN_KEY: Final[str] = "неизвестное поле"
CONFIG_PROBLEM_DUPLICATE_KEY: Final[str] = "поле указано дважды"
CONFIG_PROBLEM_NON_EMPTY_STRING: Final[str] = "нужна непустая строка в кавычках"
CONFIG_PROBLEM_TEXT_OR_NULL: Final[str] = "нужно название вопроса формы в кавычках или null, если такого вопроса в форме нет"
CONFIG_PROBLEM_TEXT_MAPPING: Final[str] = (
    'нужен непустой объект «код — текст варианта», например {"uk": "Украинский ( Ukranian)"}'
)
CONFIG_PROBLEM_INT_MIN: Final[str] = "нужно целое число не меньше {minimum}"
CONFIG_PROBLEM_NUMBER_MIN: Final[str] = "нужно число не меньше {minimum:g}, можно дробное, например 0.5"
CONFIG_PROBLEM_NUMBER_FINITE: Final[str] = "нужно обычное число: NaN и бесконечность не годятся"
CONFIG_PROBLEM_BOOL: Final[str] = "нужно true или false"
CONFIG_PROBLEM_CHOICE: Final[str] = "допустимо: {allowed}"
CONFIG_PROBLEM_FORM_PLATFORM: Final[str] = "среди вариантов площадки обязан быть «{platform}»"
CONFIG_PROBLEM_FORM_DATE_FORMAT: Final[str] = "в формате даты обязательны {required}; нет {absent}"
CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS: Final[str] = (
    "в шаблоне папки превью обязательны {{date}} и {{language}}; нет: {absent}"
)
CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE: Final[str] = (
    "шаблон папки превью должен быть относительным, например {date}/{language}: корень задаёт сама программа"
)
CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT: Final[str] = (
    "в шаблоне папки превью есть подстановка, которой программа не знает; допустимы только {date} и {language}"
)
CONFIG_PROBLEM_TIMEZONE_UNKNOWN: Final[str] = (
    "часовой пояс не распознан: нужно имя зоны из базы IANA с учётом регистра, например Europe/Kyiv"
)
CONFIG_PROBLEM_CHANNELS_EMPTY: Final[str] = "нужен непустой список каналов"
CONFIG_PROBLEM_ACCOUNT_NAME_TOO_LONG: Final[str] = (
    "название канала длиннее {maximum} символов (сейчас {length}): на YouTube таких названий нет"
)
CONFIG_PROBLEM_ACCOUNT_NAME_CONTROL: Final[str] = "в названии канала есть управляющий символ (перевод строки, табуляция)"
CONFIG_PROBLEM_ACCOUNT_NAME_SPACE_EDGE: Final[str] = (
    "название канала начинается или заканчивается пробелом: «{value}»; на YouTube таких названий нет — уберите пробел"
)
CONFIG_PROBLEM_HANDLE_PREFIX: Final[str] = "ник «{value}» должен начинаться с {prefix}, как на YouTube"
CONFIG_PROBLEM_HANDLE_LENGTH: Final[str] = (
    "в нике «{value}» после @ нужно от {minimum} до {maximum} символов (сейчас {length})"
)
CONFIG_PROBLEM_HANDLE_CHAR: Final[str] = (
    "в нике «{value}» недопустимый символ {char}: пробелы, управляющие символы и < > : \" / \\ | ? * в нике не бывают"
)
CONFIG_PROBLEM_HANDLE_DUPLICATE: Final[str] = (
    "ник «{value}» уже есть у другого канала («{other}»); большие и маленькие буквы в нике не различаются"
)
CONFIG_PROBLEM_GOOGLE_ACCOUNT: Final[str] = (
    "«{value}» не похоже на почту аккаунта Google: нужен вид имя@домен, ровно один @ и без пробелов"
)
CONFIG_PROBLEM_PLATFORM_UNKNOWN: Final[str] = "неизвестная площадка «{value}»; допустимо: {allowed}"
CONFIG_PROBLEM_LANGUAGES: Final[str] = "нужен " + CONFIG_LANGUAGES_RULE
CONFIG_PROBLEM_LANGUAGE_DUPLICATE: Final[str] = "язык «{value}» указан дважды"

# --- один экземпляр на машину (CLAUDE.md §6, инвариант 12): замок занят — работать нельзя
LOCK_REJECTED: Final[str] = (
    "Livecraft уже работает на этой машине: процесс {pid}, запущен {started_at}. "
    "Дождитесь окончания первого запуска или закройте его окно."
)
LOCK_REJECTED_UNKNOWN_OWNER: Final[str] = (
    "Livecraft уже работает на этой машине, но какой именно процесс держит запуск — определить не удалось. "
    "Закройте открытые окна Livecraft и запустите заново."
)

# --- сейф (CLAUDE.md §7): названия полей и маска, которую человек видит вместо значения.
# Само значение не показывается нигде, кроме поля настройщика, куда его ввёл сам пользователь (§8.2).
VAULT_FIELD_OPENAI_API_KEY: Final[str] = "ключ OpenAI"
VAULT_FIELD_SHEETS_ID: Final[str] = "Google таблица контент-плана"
# Пример в названии — не поставочный диапазон: название стоит в масках и сводках, и настоящий диапазон
# в нём подсказал бы структуру таблицы, ради сокрытия которой диапазон и лежит в сейфе (§7.5).
VAULT_FIELD_SHEETS_RANGE: Final[str] = "колонки Google таблицы (например, B:H)"
VAULT_FIELD_KEY_FORM_URL: Final[str] = "Google форма для ключей стрима (эфира)"
# Маска по отпечатку: название поля и четыре знака sha256 — различить два значения можно, восстановить нет.
VAULT_MASK_FINGERPRINT: Final[str] = "{label} (…{fingerprint})"
# Происхождение поля: пришло со сборкой или его вписал сам пользователь (§7.3).
VAULT_ORIGIN_SUPPLIED: Final[str] = "поставка"
VAULT_ORIGIN_OWN: Final[str] = "своё"
# Сейф заполнен не до конца — запускаться не с чем; перечень недостающих полей строит сам сейф.
# Что делать, говорит SETUP_REQUIRED, который main печатает следом, — здесь только чего не хватает.
VAULT_NOT_READY: Final[str] = "Не хватает ключей и ссылок: {fields}."

# --- настройщик, вкладка «Ключи и ссылки» (CLAUDE.md §8.2, п.1): что не так с введённым значением.
# Само введённое значение в строки не подставляется: это секрет, и он не должен попасть ни в один вывод (§7.4).
SETUP_INPUT_EMPTY: Final[str] = "пусто: чтобы убрать своё значение, нажмите «Сбросить к поставке»"
SETUP_INPUT_OPENAI_API_KEY: Final[str] = (
    "ключ OpenAI начинается с sk-, пишется без пробелов и переводов строк и длиной не меньше {minimum} символов"
)
SETUP_INPUT_SHEETS_ID: Final[str] = (
    "нужна ссылка на Google-таблицу вида https://docs.google.com/spreadsheets/d/<id>/edit или сам id: "
    "латинские буквы, цифры, - и _, не меньше {minimum} символов"
)
SETUP_INPUT_SHEETS_RANGE: Final[str] = (
    "нужен диапазон вида B:H, B1:H200, План!B:H или 'План стримов'!B2:H: "
    "колонки — от 1 до 3 латинских букв, номер строки — по желанию"
)
SETUP_INPUT_KEY_FORM_URL: Final[str] = (
    "нужна ссылка на Google-форму: https://docs.google.com/forms/… или https://forms.gle/…, без пробелов"
)
# Тексты для человека без знания устройства программы: ни где лежат файлы, ни как шифруется (смотр окна 23-09-2026).
SETUP_INPUT_OWN_UNAVAILABLE: Final[str] = (
    "на этом компьютере свои значения сохранить нельзя: программа работает на значениях, пришедших вместе с ней"
)
# Оговорка §7.2 и §14 решения 6: вкладка показывает её всегда, без неё защита выглядела бы защитой от всех.
# «Не от специалиста» — обязательно; где лежит ключ и как шифруется — не говорим.
SETUP_KEYS_NOTICE_PROTECTION: Final[str] = (
    "Значения, пришедшие вместе с программой, защищены от копирования и визуального отображения, но не от "
    "специалиста. Свои значения, введённые здесь, действуют только на этом компьютере под вашей учётной записью "
    "Windows. Свои значения и их сброс касаются только этого компьютера."
)
SETUP_KEYS_NOTICE_NO_OWN: Final[str] = (
    "На этом компьютере свои значения сохранить нельзя: программа работает на значениях, пришедших вместе с ней."
)
SETUP_KEYS_NOTICE_LOCAL_UNREADABLE: Final[str] = (
    "Ваши прежние значения не прочитались — так бывает после переноса программы на другой компьютер или смены "
    "пользователя Windows. Первое сохранение заменит их тем, что вы введёте сейчас."
)

# --- настройщик, вкладка «Каналы YouTube» (CLAUDE.md §8.2, п.2). {key} и {problem} — из ConfigError загрузчика.
SETUP_CHANNELS_NOTICE_FILE_MISSING: Final[str] = (
    "Файла secrets\\channels.json ещё нет: добавьте хотя бы один канал и сохраните."
)
SETUP_CHANNELS_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\channels.json не прочитался: {key} — {problem}. Сохранение заменит его списком этой вкладки, "
    "а прежний файл останется в secrets\\channels.previous.json."
)

# --- настройщик, вкладка «Настройки запуска» (CLAUDE.md §8.2, п.3). {key} и {problem} — из ConfigError загрузчика.
SETUP_SETTINGS_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\livecraft.json не прочитался: {key} — {problem}. Вкладка открыта на поставочных значениях "
    "программы; файл будет записан только по кнопке «Сохранить»."
)

# --- окно настройщика (CLAUDE.md §8, app\setup\app.py и app\setup\tabs\): подписи, кнопки, диалоги.
# Значения сейфа сюда не подставляются никогда: окно показывает только маски из модели вкладки (§7.4).
SETUP_WINDOW_TITLE: Final[str] = "Livecraft {version} — настройка"
SETUP_WINDOW_FAILED: Final[str] = (
    "Окно настройщика не открылось ({error}). Нужен рабочий стол Windows и Python с компонентом tcl/tk."
)
SETUP_TAB_KEYS: Final[str] = "Ключи и ссылки"
SETUP_TAB_CHANNELS: Final[str] = "Каналы YouTube"
SETUP_TAB_SETTINGS: Final[str] = "Настройки запуска"
SETUP_READY: Final[str] = "Готово к запуску."
SETUP_BUTTON_SAVE: Final[str] = "Сохранить"
SETUP_PROBLEM_LINE: Final[str] = "{label}: {text}"
SETUP_SAVE_FAILED_TITLE: Final[str] = "Не сохранено"
SETUP_CLOSE_DIRTY_TITLE: Final[str] = "Несохранённые изменения"
SETUP_CLOSE_DIRTY_TEXT: Final[str] = "Есть несохранённые изменения. Закрыть без сохранения?"
# Вкладка «Ключи и ссылки»: заголовки колонок, кнопки строки, отказы записи — без значения и без пути к сейфу.
SETUP_KEYS_HEADER_FIELD: Final[str] = "Поле"
SETUP_KEYS_HEADER_ORIGIN: Final[str] = "Откуда"
SETUP_KEYS_HEADER_VALUE: Final[str] = "Значение"
SETUP_KEYS_HEADER_INPUT: Final[str] = "Своё значение"
SETUP_KEYS_BUTTON_ACCEPT: Final[str] = "Сохранить значение"
# Сброс своего значения называется по итогу (KeyRow.reset_label): под своим есть значение программы — оно
# вернётся; нет — поле останется пустым.
SETUP_KEYS_BUTTON_RESET_TO_SUPPLIED: Final[str] = "Вернуть значение программы"
SETUP_KEYS_BUTTON_DELETE_OWN: Final[str] = "Удалить своё значение"
# «Показать своё» (§14 решение 11): только значение, которое пользователь ввёл сам, только на экран.
SETUP_KEYS_BUTTON_REVEAL: Final[str] = "показать"
SETUP_KEYS_BUTTON_HIDE: Final[str] = "скрыть"
SETUP_KEYS_SAVE_FAILED_OS: Final[str] = (
    "Не удалось записать файл ваших значений. Проверьте, не занят ли он другой программой "
    "(антивирус, синхронизация), и нажмите «Сохранить» ещё раз."
)
# Вкладка «Каналы YouTube»: подписи по ключам SettingProblem (имя поля строки канала) и по полям ChannelDraft.
SETUP_CHANNEL_FIELD_LABELS: Final[dict[str, str]] = {
    "account_name": "название канала",
    "handle": "ник",
    "google_account": "аккаунт Google",
    "languages": "языки",
    "privacy": "видимость",
    "platform": "площадка",
    "channels": "список каналов",
}
SETUP_CHANNELS_BUTTON_ADD: Final[str] = "Добавить"
SETUP_CHANNELS_BUTTON_UPDATE: Final[str] = "Изменить выбранный"
SETUP_CHANNELS_BUTTON_REMOVE: Final[str] = "Удалить выбранный"
SETUP_CHANNELS_NOTHING_SELECTED: Final[str] = "Сначала выберите канал в таблице."
SETUP_CHANNELS_SAVE_FAILED: Final[str] = "Не удалось записать secrets\\channels.json: {error}"
# Вкладка «Настройки запуска»: подписи по ключам SettingProblem (путь поля в livecraft.json).
SETUP_SETTINGS_FIELD_LABELS: Final[dict[str, str]] = {
    "min_lead_minutes": "минимальный запас до старта эфира (минут)",
    "keep_days": "хранить старые файлы программы (дней)",
    "auto_start": "эфир стартует сам, когда пошёл видеопоток",
    "set_thumbnail": "ставить эфиру обложку",
    "category_id": "категория видео на YouTube",
    "youtube_pause_seconds": "пауза между обращениями к YouTube (секунд)",
    "image_dir_template": "папка для обложек",
    "timezone": "часовой пояс",
    "llm.model": "модель OpenAI",
    "llm.fallback_model": "запасная модель OpenAI",
    "llm.reasoning_effort": "глубина рассуждений модели",
    "llm.service_tier": "тариф OpenAI",
    "llm.timeout_sec": "сколько ждать ответа модели (секунд)",
    "llm.max_output_tokens": "наибольшая длина ответа модели (токенов)",
}
# Серые подсказки справа от поля — по тем же ключам, что подписи; есть не у всех полей. Строки не проходят
# через .format: {date} и {language} здесь — буквальный текст шаблона папки.
SETUP_SETTINGS_FIELD_HINTS: Final[dict[str, str]] = {
    "category_id": (
        "номер категории YouTube: 22 — «Люди и блоги», 24 — «Развлечения», 25 — «Новости и политика», "
        "27 — «Образование»"
    ),
    "image_dir_template": (
        "где внутри папки image складывать обложки: {date} — дата эфира, {language} — язык. "
        "{date}/{language} даёт image\\23-09-2026\\uk"
    ),
    "youtube_pause_seconds": "сколько ждать между обращениями к YouTube; 0.5 — обычно достаточно",
    "llm.model": "модель OpenAI для текстов эфира, например gpt-5.6-sol",
    "llm.fallback_model": "если основная модель недоступна, например gpt-5.4",
    "llm.service_tier": "flex — дешевле и медленнее, default — обычный",
    "timezone": "Europe/Kyiv — киевское время",
}
SETUP_SETTINGS_SAVE_FAILED: Final[str] = "Не удалось записать secrets\\livecraft.json: {error}"

# --- план из таблицы (app\sheets\): причины отсева ряда и проблемы плана. Ключи словаря — значения
# RowSkipReason; заголовки шапки — текст оператора, значений ключей и ссылок настроек здесь нет (§7.4).
SHEET_ROW_SKIP_REASONS: Final[dict[str, str]] = {
    "empty_link": "нет ссылки на видео",
    "missing_date_time": "не заполнена дата или время",
    "bad_date_time": "дата или время не разобрались",
    "nonexistent_time": "такого времени нет: в эту ночь часы переводят вперёд на летнее время",
    "in_past": "время эфира уже прошло",
    "bad_link": "в ссылке не найдено видео YouTube",
    "duplicate": "повтор: та же ссылка на то же время уже есть в таблице выше",
}
SHEET_PLAN_EMPTY: Final[str] = "Таблица плана пуста: в выбранных колонках нет ни шапки, ни рядов."
SHEET_PLAN_HEADER_UNKNOWN: Final[str] = (
    "Шапка таблицы плана не распознана: нужны колонки ссылки, даты и времени (например, «Links», «Date», "
    "«Time» или «Ссылка», «Дата», «Время»). Найдены заголовки: {headers}."
)
SHEET_PLAN_HEADER_NONE: Final[str] = "нет ни одного"

# --- вход в Google (app\google\auth.py): строка в консоли — формат библиотеки, плейсхолдер {url};
# страница в браузере после входа. Ключи AUTH_REASON_TEXT — значения AuthErrorReason, {minutes} — время ожидания.
AUTH_OPEN_LINK: Final[str] = "Если браузер не открылся — откройте ссылку: {url}"
AUTH_BROWSER_DONE: Final[str] = "Вход выполнен. Вернитесь в окно Livecraft."
AUTH_REASON_TEXT: Final[dict[str, str]] = {
    "client_secret_missing": "нет файла client_secret.json рядом с программой",
    "token_unreadable": "файл входа в Google не читается; удалите его и войдите заново",
    "flow_failed": "браузер не вернул разрешение",
    "refresh_failed": "не удалось обновить вход (нет связи с Google)",
    "login_required": "нужен вход в Google: входа ещё не было или он отозван",
    "login_timeout": (
        "вход не завершён за {minutes} минут — браузер закрыт или аккаунт не выбран; "
        "при следующем запуске программа снова предложит вход"
    ),
}

# --- чтение таблицы плана (app\sheets\client.py): {label} — ярлык таблицы с отпечатком, не её адрес (§7.4).
# Ключи SHEETS_READ_REASON_TEXT — значения SheetsReadReason; {detail} — подробность без значений.
SHEETS_READ_FAILED: Final[str] = "Таблица плана {label} не прочиталась: {reason}."
SHEETS_READ_FAILED_STATUS: Final[str] = "Таблица плана {label} не прочиталась: {reason} (код ответа {status})."
SHEETS_READ_REASON_TEXT: Final[dict[str, str]] = {
    "not_configured": "не заполнено: {detail}; запустите livecraft.bat --setup",
    "auth": "не удалось войти в Google — {detail}",
    "no_access": "нет доступа — откройте таблицу аккаунту Google, под которым вошли",
    "not_found": "такой таблицы нет — проверьте ссылку на таблицу в настройках",
    "bad_range": "Google не принял колонки таблицы — проверьте их в настройках",
    "rejected": "Google отказал в чтении",
    "unavailable": "Google не ответил и после повторов — проверьте связь и запустите ещё раз",
}

# --- пробник чтения таблицы (app\tools\sheets_probe.py): только счётчики, ни адреса таблицы, ни ссылок рядов
SHEETS_PROBE_TITLE: Final[str] = "Проверка чтения таблицы плана"
SHEETS_PROBE_LOGIN: Final[str] = "Нужен вход в Google, чтобы читать таблицу плана, — сейчас откроется браузер."
SHEETS_PROBE_COLUMNS: Final[str] = "Колонки: ссылка — {link}, дата — {date}, время — {time}."
SHEETS_PROBE_COLUMN: Final[str] = "«{name}» ({number}-я в диапазоне)"
SHEETS_PROBE_ROWS: Final[str] = "Рядов прочитано: {rows}, допущено: {admitted}, отсеяно: {skipped}."
SHEETS_PROBE_SKIP_LINE: Final[str] = "  {reason}: {count}"
SHEETS_PROBE_RELOGIN_HELP: Final[str] = "войти в Google заново в браузере и выбрать другой аккаунт"
SHEETS_PROBE_RELOGIN_HINT: Final[str] = (
    "Вошли не тем аккаунтом? Запустите с --relogin и выберите аккаунт, у которого есть доступ к таблице."
)

# --- источники (app\sources\): данные видео через yt-dlp и обложка. Ключи словарей — значения
# SourceFailureReason и PreviewProblem; ссылки на видео YouTube — не секрет, их можно показывать.
SOURCE_FAILURE_REASONS: Final[dict[str, str]] = {
    "tool_missing": "нет программы yt-dlp.exe в папке tools — без неё данные видео не получить",
    "private": "видео приватное или требует входа: cookies не подошли или их нет",
    "unavailable": "видео недоступно: удалено или заблокировано",
    "timeout": "yt-dlp не ответил вовремя",
    "bad_output": "yt-dlp вернул ответ, который не разбирается",
    "no_title": "у видео нет названия",
    "failed": "yt-dlp не смог получить данные видео — подробности в логе",
    "no_language": "язык видео не определился ни по данным YouTube, ни по названию и описанию",
}
SOURCE_NO_TITLE: Final[str] = "У видео нет названия — без него эфиру нечего дать в название."
PREVIEW_PROBLEMS: Final[dict[str, str]] = {
    "no_url": "источник не дал адреса обложки",
    "not_found": "обложки по адресу нет",
    "rejected": "сервер обложек отказал в скачивании",
    "unavailable": "обложка не скачалась и после повторов",
    "not_image": "скачанный файл — не картинка",
    "too_large": "обложка больше 2 МБ и после сжатия",
}

# --- пробник источников (app\tools\source_probe.py): {…} — данные видео, их можно показывать
SOURCE_PROBE_TITLE: Final[str] = "Проверка источников через yt-dlp"
SOURCE_PROBE_USAGE: Final[str] = "Укажите одну или несколько ссылок: python -m app.tools.source_probe <ссылка> …"
SOURCE_PROBE_SOURCE: Final[str] = "Источник {link}"
SOURCE_PROBE_BAD_LINK: Final[str] = "  в ссылке не найдено видео YouTube: {raw}"
SOURCE_PROBE_ID: Final[str] = "  id: {value}"
SOURCE_PROBE_NAME: Final[str] = "  название: {value}"
SOURCE_PROBE_DURATION: Final[str] = "  длительность: {value}"
SOURCE_PROBE_LANGUAGE: Final[str] = "  язык видео: {video}; язык канала: {channel}"
SOURCE_PROBE_AUDIO: Final[str] = "  языки аудио: {value}"
SOURCE_PROBE_SUBTITLES: Final[str] = "  субтитры: {value}"
SOURCE_PROBE_AUTO_CAPTIONS: Final[str] = "  автосубтитры: {value}"
SOURCE_PROBE_SOURCE_LANGUAGE: Final[str] = "  язык источника: {code} ({source})"
SOURCE_PROBE_SOURCE_LANGUAGE_NONE: Final[str] = "  язык источника: не определился"
SOURCE_PROBE_MORE: Final[str] = "{shown} … и ещё {more}"
SOURCE_PROBE_NONE: Final[str] = "нет"
SOURCE_PROBE_PREVIEW_OK: Final[str] = "  обложка: {width}×{height}, {kilobytes} КБ — годится для YouTube"
SOURCE_PROBE_PREVIEW_BAD: Final[str] = "  обложка: не годится — {reason}"
SOURCE_PROBE_FAILED: Final[str] = "  отказ: {reason}"
SOURCE_PROBE_DETAIL: Final[str] = "  подробно: {detail}"
SOURCE_PROBE_SUMMARY: Final[str] = "Источников: {total}, получено: {ok}, отказов: {failed}."

# --- обрыв и падение запуска (app\main.py::run_cli)
RUN_INTERRUPTED: Final[str] = (
    "Запуск прерван. Что уже сделано на YouTube, найдёт и учтёт следующий запуск."
)
RUN_CRASHED: Final[str] = (
    "Livecraft аварийно остановился — подробности в логе {log}. "
    "Что уже сделано на YouTube, найдёт и учтёт следующий запуск; перешлите лог оператору."
)
