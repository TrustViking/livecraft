"""Части запуска — линии работы, их опоры, нужды и этапы; вид запуска (CLAUDE.md §10, §14 решения 17, 18, 37, 48, 50,
51).

Что делает запуск, решают переключатели линий работы (раздел `lines` livecraft.json), а не ключ режима: работа
одна (`RunMode.RUN`), служебные запуски — настройщик (--setup), проверка каналов (--check), вход (--auth), сверка
(--status): частей работы у них нет. Линия — член `RunPart`; порядок членов — порядок работы, порядок «Главной» окна
для людей — `LINE_ORDER`, этап «Главной» — `stage` (`LineStage`). Часть знает себя: своё имя для людей, что ей
нужно (`needs`) и на какую линию она опирается при каждом входе (`requires_from`): линия без работающей опоры не
работает. Вход — таблица плана или пакеты: чтение
пакетов (`PACKAGES_IN`) — не линия, оно идёт само, когда таблица плана выключена. От таблицы пакет и эфиры идут только с
нейросетью (решение 50: тексты «по номерам» — только для людей); от пакетов вывод и эфиры своей опоры не требуют (решение
51). Какие линии работают, решает `LinePlan` (app\\run\\line_plan.py); удовлетворена ли нужда и что сделать, если нет, —
`Readiness.gap` (app\\setup\\readiness.py): там прочитанные сейф и конфиги. Служебным запускам по каналам нужны каналы,
настройки и client_secret.json (`RunMode.service_needs`).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.run.flag import CliFlag
from app.ui.messages import msg


class Need(str, Enum):
    """Что нужно части запуска, чтобы работать. Значение — английский идентификатор для лога."""

    SHEETS_VAULT = "sheets_vault"        # id таблицы плана в сейфе (лист и колонки — по шапке, §14 решение 26)
    OPENAI_VAULT = "openai_vault"        # ключ OpenAI в сейфе
    SETTINGS = "settings"                # livecraft.json прочитан
    FORM = "form"                        # ссылка на форму ключей задана
    CHANNELS = "channels"                # channels.json прочитан
    CLIENT_SECRET = "client_secret"      # client_secret.json рядом с программой (§9)
    TELEGRAM = "telegram"                # токен бота в сейфе и чат, куда уходят объявления (§14 решение 19)
    DRIVE_FOLDER = "drive_folder"        # папка материалов на Google Диске задана (§14 решение 27)


class RunPart(str, Enum):
    """Часть работы одного запуска в порядке работы: сначала вход (таблица плана или чтение пакетов — основа запуска),
    затем вывод и эфиры. Значение — английский идентификатор для лога и имя поля линии в разделе `lines`
    livecraft.json."""

    PLAN = "plan"                          # таблица плана: чтение, источники, язык видео в таблицу, слоты
    PACKAGES_IN = "packages_in"            # чтение пакетов из папки пакетов — таблица плана выключена (вход «Пакеты»)
    LOCAL_PREVIEWS = "local_previews"      # копии превью в папке превью
    DRIVE_PREVIEWS = "drive_previews"      # копии превью на Google Диске и ссылки на них в таблице плана
    MERGE = "merge"                        # одно название и одно описание на слот нейросетью
    PACKAGE = "package"                    # пакет plan_*.bcast в папке пакетов
    DOC = "doc"                            # документ объявлений в Google Docs на каждую дату
    DOC_COPY = "doc_copy"                  # копия документа объявлений .docx в папке копий
    ANNOUNCE = "announce"                  # объявления в Telegram: по датам слотов, затем пакет документом
    BROADCAST = "broadcast"                # эфиры на YouTube
    KEYS = "keys"                          # ключи эфиров в форму

    @property
    def human_label(self) -> str:
        return msg.RUN_PART_LABELS[self.value]

    @property
    def needs(self) -> tuple[Need, ...]:
        """Что нужно части — в том порядке, в каком об этом говорить человеку."""
        return PART_NEEDS[self]

    @property
    def stage(self) -> LineStage:
        """Этап работы, под которым линия стоит на «Главной» (§14 решение 48)."""
        return PART_STAGES[self]

    def requires_from(self, source: RunPart) -> RunPart | None:
        """Линия, на которую опирается часть при входе `source` (таблица плана или чтение пакетов); своя опора не
        нужна — None."""
        return INPUT_REQUIRES[source].get(self)


class LineStage(str, Enum):
    """Этап работы (§14 решение 48): «Главная» делит линии чертами с подписями этапов. Значение — английский
    идентификатор и ключ подписи этапа (`human_label`)."""

    INPUT = "input"                  # откуда эфиры: таблица плана или пакеты — одно из двух
    PROCESSING = "processing"        # нейросеть
    OUTPUT = "output"                # превью, документ и копия, пакет, Telegram
    BROADCASTS = "broadcasts"        # эфиры YouTube и ключи в форму

    @property
    def human_label(self) -> str:
        return msg.SETUP_LINE_STAGES[self.value]

    @property
    def parts(self) -> tuple[RunPart, ...]:
        """Линии этапа в порядке «Главной»."""
        return tuple(part for part in LINE_ORDER if part.stage is self)


# Что нужно каждой части (§7.5, §9): таблице — сейф таблицы, настройки и вход в Google; превью в папке — настройки
# (шаблон папки); превью на Диске — ещё и папка материалов; нейросети — ключ OpenAI; пакету — настройки и форма;
# документу объявлений — папка материалов, форма (её ссылка — в шапке), настройки и вход в Google; копии документа —
# настройки; объявлениям в Telegram — бот и чат, форма (объявление ведёт стримеров к форме ключей: без её ссылки оно
# бесполезно) и настройки; эфирам — каналы, настройки и client_secret.json (вход в каналы YouTube — тем же
# OAuth-клиентом, §9); ключам в форму — форма и настройки; чтению пакетов — настройки (пояс программы).
PART_NEEDS: Final[dict[RunPart, tuple[Need, ...]]] = {
    RunPart.PLAN: (Need.SHEETS_VAULT, Need.SETTINGS, Need.CLIENT_SECRET),
    RunPart.LOCAL_PREVIEWS: (Need.SETTINGS,),
    RunPart.DRIVE_PREVIEWS: (Need.DRIVE_FOLDER, Need.SHEETS_VAULT, Need.SETTINGS, Need.CLIENT_SECRET),
    RunPart.MERGE: (Need.OPENAI_VAULT,),
    RunPart.PACKAGE: (Need.SETTINGS, Need.FORM),
    RunPart.DOC: (Need.DRIVE_FOLDER, Need.FORM, Need.SETTINGS, Need.CLIENT_SECRET),
    RunPart.DOC_COPY: (Need.SETTINGS,),
    RunPart.ANNOUNCE: (Need.TELEGRAM, Need.FORM, Need.SETTINGS),
    RunPart.PACKAGES_IN: (Need.SETTINGS,),
    RunPart.BROADCAST: (Need.CHANNELS, Need.SETTINGS, Need.CLIENT_SECRET),
    RunPart.KEYS: (Need.FORM, Need.SETTINGS),
}
# Опоры линий при входе «Таблица» (§14 решения 37, 50): нейросеть, оба превью, документ и Telegram работают со слотами
# таблицы; пакет и эфиры — только с текстами нейросети (тексты «по номерам» на YouTube и в пакет не идут); копия
# документа — с документом; ключи в форму — с эфирами.
TABLE_REQUIRES: Final[dict[RunPart, RunPart]] = {
    RunPart.MERGE: RunPart.PLAN,
    RunPart.LOCAL_PREVIEWS: RunPart.PLAN,
    RunPart.DRIVE_PREVIEWS: RunPart.PLAN,
    RunPart.DOC: RunPart.PLAN,
    RunPart.ANNOUNCE: RunPart.PLAN,
    RunPart.PACKAGE: RunPart.MERGE,
    RunPart.BROADCAST: RunPart.MERGE,
    RunPart.DOC_COPY: RunPart.DOC,
    RunPart.KEYS: RunPart.BROADCAST,
}
# Опоры при входе «Пакеты» (§14 решение 51): нейросети нужна таблица; превью, документ, Telegram, пакет и эфиры
# работают от слотов пакетов; копия документа — с документом; ключи в форму — с эфирами.
PACKAGES_REQUIRES: Final[dict[RunPart, RunPart]] = {
    RunPart.MERGE: RunPart.PLAN,
    RunPart.DOC_COPY: RunPart.DOC,
    RunPart.KEYS: RunPart.BROADCAST,
}
INPUT_REQUIRES: Final[dict[RunPart, dict[RunPart, RunPart]]] = {
    RunPart.PLAN: TABLE_REQUIRES,
    RunPart.PACKAGES_IN: PACKAGES_REQUIRES,
}
# Нужды, которые при входе «Пакеты» удовлетворены сами: форма ключей — у каждого пакета своя (решение 51), таблицы нет —
# ссылки на превью в неё не пишутся.
PACKAGES_MET_NEEDS: Final[frozenset[Need]] = frozenset({Need.FORM, Need.SHEETS_VAULT})
# Линии работы в порядке «Главной» окна — для людей; чтение пакетов не линия.
LINE_ORDER: Final[tuple[RunPart, ...]] = (
    RunPart.PLAN,
    RunPart.MERGE,
    RunPart.LOCAL_PREVIEWS,
    RunPart.DRIVE_PREVIEWS,
    RunPart.DOC,
    RunPart.DOC_COPY,
    RunPart.PACKAGE,
    RunPart.ANNOUNCE,
    RunPart.BROADCAST,
    RunPart.KEYS,
)
# Этап каждой части (§14 решение 48): вход — таблица плана или чтение пакетов; обработка — нейросеть; вывод — превью,
# документ и копия, пакет и Telegram; эфиры — эфиры YouTube и ключи в форму.
PART_STAGES: Final[dict[RunPart, LineStage]] = {
    RunPart.PLAN: LineStage.INPUT,
    RunPart.PACKAGES_IN: LineStage.INPUT,
    RunPart.MERGE: LineStage.PROCESSING,
    RunPart.LOCAL_PREVIEWS: LineStage.OUTPUT,
    RunPart.DRIVE_PREVIEWS: LineStage.OUTPUT,
    RunPart.DOC: LineStage.OUTPUT,
    RunPart.DOC_COPY: LineStage.OUTPUT,
    RunPart.PACKAGE: LineStage.OUTPUT,
    RunPart.ANNOUNCE: LineStage.OUTPUT,
    RunPart.BROADCAST: LineStage.BROADCASTS,
    RunPart.KEYS: LineStage.BROADCASTS,
}
# Служебные запуски по каналам (--check, --auth, --status): каналы, настройки и вход в YouTube тем же OAuth-клиентом.
CHANNEL_SERVICE_NEEDS: Final[tuple[Need, ...]] = (Need.CHANNELS, Need.SETTINGS, Need.CLIENT_SECRET)


class RunMode(str, Enum):
    """Что запросила командная строка. Значение — английский идентификатор для лога."""

    RUN = "run"                      # работа по включённым линиям; ключа нет
    SETUP = "setup"                  # окно настройщика
    CHECK = "check"                  # проверка каналов
    AUTH = "auth"                    # вход в канал заново
    STATUS = "status"                # сверка эфиров без таблицы и нейросети

    @property
    def is_service(self) -> bool:
        """Служебный запуск, а не работа по линиям: частей работы у него нет."""
        return self is not RunMode.RUN

    @property
    def flag(self) -> CliFlag | None:
        """Ключ командной строки служебного запуска; у работы по линиям ключа нет."""
        return MODE_FLAGS.get(self)

    @property
    def service_needs(self) -> tuple[Need, ...]:
        """Что нужно служебному запуску по каналам; окну настройщика не нужно ничего, работе — её части."""
        return CHANNEL_SERVICE_NEEDS if self.is_service and self is not RunMode.SETUP else ()


MODE_FLAGS: Final[dict[RunMode, CliFlag]] = {
    RunMode.SETUP: CliFlag.SETUP,
    RunMode.CHECK: CliFlag.CHECK,
    RunMode.AUTH: CliFlag.AUTH,
    RunMode.STATUS: CliFlag.STATUS,
}


class ModeStep(str, Enum):
    """Что делает запуск по готовности линий. Значение — идентификатор для лога."""

    OPEN_SETUP = "open_setup"        # не работает ни одна линия или не готова основа: строки, окно настройщика, код 2
    RUN_PLAN = "run_plan"            # таблица готова: сводка, строки нужд, прогон контура A
    RUN_PACKAGES = "run_packages"    # режим Б, чтение пакетов готово: сводка, строки нужд, полка пакетов и эфиры


class PartState(str, Enum):
    """Состояние работающей части. Значение — идентификатор для лога."""

    READY = "ready"              # всё нужное есть
    BLOCKED = "blocked"          # чего-то не хватает


@dataclass(frozen=True)
class NeedGap:
    """Нужда, которой не хватает, и строки для человека без значений (§7.4): `text` — что задать и где (консоль и лог),
    `what` — что задать, без вкладки (окно: рядом кнопка «Перейти»); None — у строки вкладки нет, окну — `text`."""

    need: Need
    text: str
    what: str | None = None

    @property
    def window_text(self) -> str:
        """Строка окна: что задать; вкладку называет кнопка «Перейти» рядом."""
        return self.text if self.what is None else self.what


@dataclass(frozen=True)
class PartReadiness:
    """Готовность одной работающей части: чего ей не хватает (`unmet`) и что из этого следует (`state`)."""

    part: RunPart
    unmet: tuple[NeedGap, ...]

    @property
    def state(self) -> PartState:
        return PartState.BLOCKED if self.unmet else PartState.READY

    def lacks(self, text: str) -> bool:
        """Не готова ли часть из-за нужды с этим текстом: две нужды с одним текстом — одна беда (сломанный сейф
        не даёт ни таблицы, ни ключа OpenAI)."""
        return self.state is PartState.BLOCKED and any(gap.text == text for gap in self.unmet)
