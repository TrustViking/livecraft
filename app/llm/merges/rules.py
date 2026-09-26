"""Пороги merge: одно место для всех чисел, по которым разбирается, проверяется и нормализуется ответ модели.

Пороги — стартовые данные (CLAUDE.md §14 решение 23): меняются только задачей продукта по итогам боевого прогона.
Нормализация качества, проверка покрытия, контракт промта и разбор ответа берут числа отсюда, чтобы правила,
которые должны сходиться, не разошлись.
"""
from __future__ import annotations

from typing import Final

# Перегруженный пункт: длиннее 500 знаков — всегда; длиннее 280 знаков — если в нём не меньше трёх имён собственных.
BULLET_OVERLOAD_CHAR_LIMIT: Final[int] = 280
BULLET_OVERLOAD_NAME_LIMIT: Final[int] = 3
BULLET_ABSOLUTE_MAX_CHAR_LIMIT: Final[int] = 500

# Компактный контракт (один-два источника): пунктов от 4 до 7.
COMPACT_BULLET_MIN: Final[int] = 4
COMPACT_BULLET_MAX: Final[int] = 7
COMPACT_MAX_SOURCES: Final[int] = 2

# Акцентных маркеров (📌, 🎤, …) в списке не больше трёх; лишние становятся нейтральными 🔹.
ACCENT_MARKER_CAP: Final[int] = 3

# Контракт промта: расширенный — от трёх источников, пунктов 4-6 при трёх, 5-7 при четырёх-пяти, 6-9 при шести
# и больше; тело — не больше 7 абзацев. «Одно событие» — от двух источников, когда не меньше пяти имён встречаются
# хотя бы в двух источниках; тело — не больше 5 абзацев. Компактный — не больше 4.
EXPANDED_MIN_SOURCES: Final[int] = 3
EXPANDED_BULLET_RANGES: Final[tuple[tuple[int, int, int], ...]] = ((3, 4, 6), (5, 5, 7))   # (до стольких источников, min, max)
EXPANDED_BULLET_RANGE_LARGE: Final[tuple[int, int]] = (6, 9)
EXPANDED_MAX_BODY_PARAGRAPHS: Final[int] = 7
NARRATIVE_MIN_SOURCES: Final[int] = 2
NARRATIVE_MIN_SHARED_ENTITIES: Final[int] = 5
NARRATIVE_SHARED_IN_SOURCES: Final[int] = 2
NARRATIVE_MAX_BODY_PARAGRAPHS: Final[int] = 5
COMPACT_MAX_BODY_PARAGRAPHS: Final[int] = 4
# Имя события для сравнения источников — цепочка не меньше чем из двух слов с заглавной буквы.
EVENT_NAME_MIN_WORDS: Final[int] = 2

# Строка-якорь спикеров: от четырёх источников, не больше восьми имён, самые длинные первыми.
SPEAKER_ANCHOR_MIN_SOURCES: Final[int] = 4
SPEAKER_NAMES_MAX: Final[int] = 8

# Официальные ссылки источников: оценка ссылки — https +20, контекст «official», «сайт» и т. п. в строке +20,
# частота домена по 5 за ссылку (не больше 20), query −5, короткая ссылка — до +15 (минус 1 за каждые 15 знаков);
# после повтора по ключу остаются не больше трёх лучших.
OFFICIAL_LINK_HTTPS_SCORE: Final[int] = 20
OFFICIAL_LINK_CONTEXT_SCORE: Final[int] = 20
OFFICIAL_LINK_DOMAIN_SCORE_STEP: Final[int] = 5
OFFICIAL_LINK_DOMAIN_SCORE_CAP: Final[int] = 20
OFFICIAL_LINK_QUERY_PENALTY: Final[int] = 5
OFFICIAL_LINK_LENGTH_SCORE: Final[int] = 15
OFFICIAL_LINK_LENGTH_STEP: Final[int] = 15
OFFICIAL_LINKS_KEPT_MAX: Final[int] = 3

# Ответ модели: название от 1 до 99 знаков; тело описания — от двух абзацев до предела контракта. При пределе тела
# от семи абзацев ответ ровно на один абзац длиннее отвергается до восстановления: слияние исказило бы структуру.
TITLE_MIN_CHARS: Final[int] = 1
TITLE_MAX_CHARS: Final[int] = 99
MIN_BODY_PARAGRAPHS: Final[int] = 2
SINGLE_STEP_OVERFLOW_MIN_LIMIT: Final[int] = 7
# Восстановление числа абзацев тела: один абзац делится, только если в нём не меньше четырёх фраз (левая часть —
# не меньше двух); лишние абзацы сливаются, только если их не больше чем на четыре сверх предела.
SPLIT_MIN_SENTENCES: Final[int] = 4
SPLIT_MIN_LEFT_SENTENCES: Final[int] = 2
COLLAPSE_MAX_EXCESS: Final[int] = 4

# Проверка покрытия. Соседние строки — повтор: обе не короче 60 знаков и общее начало больше 65 % короткой;
# или в обеих не меньше 8 смысловых слов и доля общих (Жаккар) не меньше 0,75.
ADJACENT_LINE_MIN_CHARS: Final[int] = 60
ADJACENT_LINE_PREFIX_RATIO: Final[float] = 0.65
ADJACENT_LINE_MIN_TOKENS: Final[int] = 8
ADJACENT_LINE_JACCARD: Final[float] = 0.75
# Два любых абзаца — повтор: оба не короче 80 знаков и общее начало больше 70 % короткого.
PARAGRAPH_PREFIX_MIN_CHARS: Final[int] = 80
PARAGRAPH_PREFIX_RATIO: Final[float] = 0.7
# Эхо тезиса: оба текста не короче 40 знаков; общее начало больше половины; последняя фраза тезиса (не короче
# 30 знаков) и первая строка тела совпадают по смысловым словам не меньше чем на 55 %; весь тезис и первая строка
# тела — не меньше чем на 60 %.
ECHO_MIN_CHARS: Final[int] = 40
ECHO_PREFIX_RATIO: Final[float] = 0.50
ECHO_SENTENCE_MIN_CHARS: Final[int] = 30
ECHO_SENTENCE_JACCARD: Final[float] = 0.55
ECHO_JACCARD: Final[float] = 0.60
# Пункт, сросшийся с тезисом в одной строке: конец фразы не ближе 40 знаков от начала строки.
FUSED_BULLET_MIN_POSITION: Final[int] = 40
# Выгрузка по источникам: строк «Source 1:», «Video 2)» — хотя бы две.
SOURCE_LINE_MIN_HITS: Final[int] = 2
# Призыв в начале: окно — первые три непустые строки первых двух абзацев.
OPENING_PARAGRAPHS: Final[int] = 2
OPENING_LINES: Final[int] = 3
# Пунктов при двух и больше источниках — не меньше max(источников + 1, 5).
MIN_BULLETS_FLOOR: Final[int] = 5
MIN_BULLETS_EXTRA_OVER_SOURCES: Final[int] = 1
MIN_BULLETS_MIN_SOURCES: Final[int] = 2
# Эмодзи вне маркеров пунктов — не больше десяти.
EMOJI_MAX: Final[int] = 10
# Перегруженных пунктов не меньше двух при списке от четырёх пунктов — отказ.
OVERLOADED_BULLETS_REJECT: Final[int] = 2
OVERLOADED_BULLETS_MIN_LIST: Final[int] = 4
# Тезис есть: первый абзац не короче 60 знаков и в нём «!», «?» или «:». Список есть: от трёх пунктов.
HOOK_MIN_CHARS: Final[int] = 60
HOOK_MARKS: Final[tuple[str, ...]] = ("!", "?", ":")
AGENDA_MIN_BULLETS: Final[int] = 3
# Восстановление форматирования — от трёх источников.
FORMATTING_RECOVERY_MIN_SOURCES: Final[int] = 3

# Служебная строка — не длиннее 140 знаков; абзац короче 12 знаков язык не получает.
SERVICE_LINE_MAX_CHARS: Final[int] = 140
SERVICE_PARAGRAPH_MIN_CHARS: Final[int] = 12
# Смесь алфавитов: не больше пяти подозрительных слов на описание. В английском тексте подозрительно слово хотя бы
# с двумя кириллическими буквами; в тексте кириллицей — латинское слово в нижнем регистре не короче четырёх
# латинских букв, если это не аббревиатура, не слово с заглавной буквы и не допустимое слово.
SCRIPT_MIX_MAX_SUSPECTS: Final[int] = 5
EN_MIN_CYRILLIC_CHARS: Final[int] = 2
CYRILLIC_TEXT_MIN_LATIN_CHARS: Final[int] = 4

# Попыток merge на слот: две; три — если хоть одна отвергнутая попытка отказана по повторяемой причине.
PRIMARY_ATTEMPTS: Final[int] = 2
PRIMARY_ATTEMPTS_EXTENDED: Final[int] = 3
# Merge делается, только когда непустых описаний у источников слота не меньше двух.
MIN_DESCRIBED_SOURCES: Final[int] = 2
# Предел абзацев тела при выравнивании принятого описания слота из нескольких источников.
POST_ENFORCEMENT_MAX_BODY_PARAGRAPHS: Final[int] = 4
# Версия контракта стиля в строке лога `merge_style_coverage`.
STYLE_CONTRACT_VERSION: Final[str] = "v4_merge_quality_hardening"

# Рекомендуемые материалы: не больше двух видео. У слота из двух источников и меньше видео проходит порог, если хоть
# одно слово его контекста совпало со словами ответа; у слота побольше — если оно встретилось в двух источниках или
# совпали два слова.
RECOMMENDED_MAX: Final[int] = 2
RECOMMENDED_FEW_SOURCES: Final[int] = 2
RECOMMENDED_FEW_MIN_OVERLAP: Final[int] = 1
RECOMMENDED_REPEATED_HITS: Final[int] = 2
RECOMMENDED_MIN_OVERLAP: Final[int] = 2
