from __future__ import annotations

import io
import unicodedata
from pathlib import Path

import pytest

from app.config.channel import ChannelConfig, ConfiguredChannels
from app.config.files import ChannelsFile
from app.google.auth import AuthError, AuthErrorReason
from app.paths import FileName, LivecraftPaths
from app.platforms.channel import (
    LOGIN_MAX_ATTEMPTS,
    Channel,
    ChannelBindingError,
    ChannelCheck,
    ChannelRefusal,
    ChannelStatus,
    CheckVerdict,
    LoginNeed,
)
from app.platforms.channel_console import ChannelConsole
from app.platforms.channel_info import ChannelInfo
from app.platforms.error import PlatformCode, PlatformError
from app.platforms.passport import ChannelPassport, ChannelVerification, PassportEntry
from app.platforms.channel_book import ChannelBook
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.platform import (
    FAKE_TOKEN_TEXT,
    FakePlatform,
    channel_info,
    channel_of,
    channel_sync,
    token_path,
    two_channels,
    written_channels,
    written_token,
)
from app.ui import messages_ru as msg

CYRILLIC_ENCODED: str = "@%D0%9A%D0%B0%D0%BD%D0%B0%D0%BB%D0%A2%D0%B5%D1%81%D1%82"
UA: ChannelConfig = channel_of()
WRONG: ChannelInfo = channel_info(UA, youtube_channel_id="UCother", title="Lisa Thomson", handle_raw="@lisathomson-v3l")
TIMEOUT: AuthError = AuthError(AuthErrorReason.LOGIN_TIMEOUT, "no answer in 600 s")


def book_of(platform: FakePlatform, paths: LivecraftPaths, record: ConsoleRecord | None = None) -> ChannelBook:
    console: ChannelConsole | None = None if record is None else ChannelConsole(record.console)
    return ChannelBook(platform, channel_sync(platform, paths), console)


def passport_entry(channel: ChannelConfig, channel_id: str) -> PassportEntry:
    info: ChannelInfo = channel_info(channel, youtube_channel_id=channel_id)
    return ChannelPassport(Path("passport.json")).record_verified(
        ChannelVerification(channel, channel, info, "t.json", "01-09-2026 10:00")
    )


def console_lines(channel: ChannelConfig, info: ChannelInfo, will_retry: bool) -> str:
    template: str = msg.AUTH_WRONG_CHANNEL_RETRY if will_retry else msg.AUTH_WRONG_CHANNEL_GIVE_UP
    return template.format(
        account_name=channel.account_name, handle=channel.handle, youtube_title=info.title, youtube_handle=info.handle_text
    )


# --- правило проверки: ник → id по паспорту → название


@pytest.mark.parametrize(
    ("changes", "entry_id", "verdict", "refusal"),
    [
        ({}, None, CheckVerdict.CONFIRMED, None),
        ({}, "UCfakeyt_ua", CheckVerdict.CONFIRMED, None),
        ({"title": "Новое"}, None, CheckVerdict.ALIGN, None),
        ({"handle_raw": None}, None, CheckVerdict.REFUSED, ChannelRefusal.HANDLE_MISSING),
        ({"handle_raw": "@other"}, None, CheckVerdict.REFUSED, ChannelRefusal.HANDLE_MISMATCH),
        ({"handle_raw": "@other"}, "UCfakeyt_ua", CheckVerdict.ALIGN, None),
        ({}, "UCother", CheckVerdict.REFUSED, ChannelRefusal.ID_MISMATCH),
    ],
    ids=["same", "same_in_passport", "title", "no_handle", "other_handle", "handle_by_id", "other_id"],
)
def test_check_rule(
    changes: dict[str, object], entry_id: str | None, verdict: CheckVerdict, refusal: ChannelRefusal | None
) -> None:
    channel: Channel = Channel(
        config=UA, token_file=Path("t.json"), passport_entry=passport_entry(UA, entry_id) if entry_id else None
    )
    assert channel.check(channel_info(UA, **changes)) == ChannelCheck(verdict, refusal)


@pytest.mark.parametrize(
    ("handle", "handle_raw"),
    [("@Kanal_Test25", "@kanal_test25"), ("@КаналТест", CYRILLIC_ENCODED), ("@Kanal.X", " Kanal.X ")],
    ids=["lower_case", "percent_encoded", "without_at_and_spaces"],
)
def test_handle_from_youtube_is_compared_by_key(handle: str, handle_raw: str) -> None:
    config: ChannelConfig = channel_of(handle, "Канал")
    channel: Channel = Channel(config=config, token_file=Path("t.json"))
    assert channel.check(channel_info(config, handle_raw=handle_raw)).verdict is CheckVerdict.CONFIRMED


def test_title_is_compared_in_nfc_without_edge_spaces() -> None:
    name: str = unicodedata.normalize("NFC", "Канал Лейла")
    config: ChannelConfig = channel_of("@kanal_leyla", name)
    channel: Channel = Channel(config=config, token_file=Path("t.json"))
    decomposed: str = unicodedata.normalize("NFD", name)
    assert channel.check(channel_info(config, title=f"  {decomposed} ")).verdict is CheckVerdict.CONFIRMED


def test_refusal_speaks_to_the_owner_and_keeps_the_code() -> None:
    channel: Channel = Channel(config=UA, token_file=Path("t.json"))
    error: ChannelBindingError = channel.refusal(WRONG, ChannelRefusal.HANDLE_MISMATCH)
    assert error.code == "channelHandleMismatch"
    assert str(error) == error.human == msg.AUTH_CHANNEL_HANDLE_MISMATCH.format(
        account_name="yt_ua", handle="@yt_ua", youtube_title="Lisa Thomson", youtube_handle="@lisathomson-v3l",
        youtube_channel_id="UCother",
    )
    assert "Lisa" not in error.message and "@lisathomson-v3l" in error.message


def test_channel_not_ready_names_the_login_it_needs() -> None:
    error: PlatformError | None = Channel(config=UA, token_file=Path("t.json")).access_error()
    assert error is not None and error.code == PlatformCode.LOGIN_REQUIRED.value
    assert str(error) == msg.YOUTUBE_REASON_TEXT["loginRequired"]


# --- статусы после проверки без браузера


def test_statuses_after_check_without_login(livecraft_paths: LivecraftPaths) -> None:
    ua, ru = two_channels()
    en: ChannelConfig = channel_of("@yt_en", "yt_en", "en")
    channels: ConfiguredChannels = written_channels(livecraft_paths, ua, ru, en)
    written_token(livecraft_paths, ua.handle)
    written_token(livecraft_paths, en.handle)
    platform: FakePlatform = FakePlatform()
    platform.fail_describe["yt_en"] = PlatformError("backendError", "503")
    book: ChannelBook = book_of(platform, livecraft_paths)
    assert book.check_without_login(channels) == channels
    found: dict[str, ChannelStatus] = {channel.key: book.channel(channel).status for channel in channels.channels}
    assert found == {"yt_ua": ChannelStatus.READY, "yt_ru": ChannelStatus.NEEDS_LOGIN, "yt_en": ChannelStatus.FAILED}
    assert book.channel(ua).info == FakePlatform.default_channel_info(ua)
    assert platform.logins == []


class AskedAtLine(io.StringIO):
    """stdout консоли, который к каждой строке помнит, сколько раз площадку уже спросили о канале."""

    def __init__(self, platform: FakePlatform) -> None:
        super().__init__()
        self.platform: FakePlatform = platform
        self.asked: list[int] = []

    def write(self, text: str) -> int:
        if text != "\n":
            self.asked.append(len(self.platform.describe_calls))
        return super().write(text)


def test_the_check_says_a_line_before_it_asks_youtube(livecraft_paths: LivecraftPaths) -> None:
    """Сверка каналов идёт по сети (рабочий прогон 01-10-2026: 59 с тишины на повторах): перед ней — строка, и перед
    вопросом YouTube о каждом канале с файлом входа — строка этого канала; канал без файла входа YouTube не спрашивают,
    и строки у него нет."""
    ua, ru = two_channels()
    channels: ConfiguredChannels = written_channels(livecraft_paths, ua, ru)
    written_token(livecraft_paths, ua.handle)
    record: ConsoleRecord = ConsoleRecord()
    book_of(FakePlatform(), livecraft_paths, record).check_without_login(channels)
    assert record.lines == [
        msg.PROGRESS_CHANNELS_CHECK.format(count=2),
        msg.PROGRESS_CHANNEL_CHECK_STARTED.format(account_name=ua.account_name, handle=ua.handle),
    ]
    assert record.lines == [
        "Проверка каналов YouTube по сохранённым входам: 2.",
        "Канал «yt_ua» @yt_ua: проверка по сохранённому входу.",
    ]


def test_each_channel_line_comes_before_youtube_is_asked_about_it(livecraft_paths: LivecraftPaths) -> None:
    ua, ru = two_channels()
    channels: ConfiguredChannels = written_channels(livecraft_paths, ua, ru)
    written_token(livecraft_paths, ua.handle)
    written_token(livecraft_paths, ru.handle)
    platform: FakePlatform = FakePlatform()
    stdout: AskedAtLine = AskedAtLine(platform)
    book_of(platform, livecraft_paths, ConsoleRecord(out=stdout)).check_without_login(channels)
    assert ConsoleRecord(out=stdout).lines[1:] == [
        msg.PROGRESS_CHANNEL_CHECK_STARTED.format(account_name=channel.account_name, handle=channel.handle)
        for channel in (ua, ru)
    ]
    assert stdout.asked == [0, 0, 1] and platform.describe_calls == [ua.key, ru.key]


def test_foreign_token_is_dropped_and_the_channel_logs_in_again(livecraft_paths: LivecraftPaths) -> None:
    """Живой прогон planers 17-09-2026: токен «Українка Я» вёл на «Lisa Thomson» — файл удаляется, вход заново."""
    channels: ConfiguredChannels = written_channels(livecraft_paths, UA)
    token: Path = written_token(livecraft_paths, UA.handle)
    platform: FakePlatform = FakePlatform()
    platform.channel_info["yt_ua"] = WRONG
    book: ChannelBook = book_of(platform, livecraft_paths)
    book.check_without_login(channels)
    assert not token.exists()
    assert book.channel(UA).status is ChannelStatus.NEEDS_LOGIN
    assert book.sync.take_warnings() == [
        msg.WARNING_TOKEN_REJECTED.format(
            account_name="yt_ua", handle="@yt_ua", youtube_title="Lisa Thomson",
            youtube_handle="@lisathomson-v3l", youtube_channel_id="UCother",
        )
    ]
    platform.login_answers["yt_ua"] = [FakePlatform.default_channel_info(UA)]
    book.log_in_needed(channels.channels)
    assert book.channel(UA).status is ChannelStatus.READY
    assert token.read_text(encoding="utf-8") == FAKE_TOKEN_TEXT


# --- вход


def test_wrong_channel_then_right_channel_is_ready(livecraft_paths: LivecraftPaths) -> None:
    written_channels(livecraft_paths, UA)
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua"}
    platform.login_answers["yt_ua"] = [WRONG, FakePlatform.default_channel_info(UA)]
    record: ConsoleRecord = ConsoleRecord()
    channel: Channel = book_of(platform, livecraft_paths, record).log_in(UA)
    assert channel.status is ChannelStatus.READY and channel.login_attempts == 2
    reason: str = msg.AUTH_LOGIN_NEEDS["no_token"]
    starting: str = msg.AUTH_STARTING.format(account_name="yt_ua", handle="@yt_ua", reason=reason)
    assert [line for line in record.lines if line == starting] == [starting, starting]
    assert console_lines(UA, WRONG, will_retry=True) in record.lines
    assert record.lines[-1].startswith(msg.AUTH_OK.split("—", 1)[0].format(account_name="yt_ua", handle="@yt_ua"))
    assert token_path(livecraft_paths, UA.handle).read_text(encoding="utf-8") == FAKE_TOKEN_TEXT
    found: PassportEntry | None = ChannelPassport.load(livecraft_paths.file(FileName.PASSPORT)).find_by_key("yt_ua")
    assert found is not None and found.youtube_channel_id == "UCfakeyt_ua"
    assert platform.kept_logins == ["yt_ua"]


def test_two_wrong_channels_are_refused_without_token(livecraft_paths: LivecraftPaths) -> None:
    written_channels(livecraft_paths, UA)
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua"}
    platform.login_answers["yt_ua"] = [WRONG] * LOGIN_MAX_ATTEMPTS
    record: ConsoleRecord = ConsoleRecord()
    book: ChannelBook = book_of(platform, livecraft_paths, record)
    channel: Channel = book.log_in(UA)
    assert channel.status is ChannelStatus.REFUSED and channel.login_attempts == LOGIN_MAX_ATTEMPTS
    assert record.lines[-1] == console_lines(UA, WRONG, will_retry=False)
    assert not token_path(livecraft_paths, UA.handle).exists() and platform.kept_logins == []
    assert not livecraft_paths.file(FileName.PASSPORT).exists()
    assert isinstance(channel.error, ChannelBindingError)
    assert channel.error.code == ChannelRefusal.HANDLE_MISMATCH.value
    assert str(channel.error) == msg.AUTH_CHANNEL_HANDLE_MISMATCH.format(
        account_name="yt_ua", handle="@yt_ua", youtube_title="Lisa Thomson", youtube_handle="@lisathomson-v3l",
        youtube_channel_id="UCother",
    )
    assert msg.AUTH_NEXT_RUN_HINT in str(channel.error)
    book.log_in(UA)                                        # статус не NEEDS_LOGIN: третьего входа нет
    assert platform.logins == ["yt_ua"] * LOGIN_MAX_ATTEMPTS


def test_login_failure_is_failed(livecraft_paths: LivecraftPaths) -> None:
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua"}
    closed: AuthError = AuthError(AuthErrorReason.FLOW_FAILED, "closed")
    failure: PlatformError = PlatformError.of_login(closed, PlatformCode.AUTH_FAILED)
    platform.fail_login["yt_ua"] = failure
    record: ConsoleRecord = ConsoleRecord()
    channel: Channel = book_of(platform, livecraft_paths, record).log_in(UA)
    assert channel.status is ChannelStatus.FAILED and channel.login_attempts == 1
    assert channel.error is failure
    assert record.lines[-2:] == [
        msg.AUTH_FAILED.format(account_name="yt_ua", handle="@yt_ua", reason=msg.AUTH_REASON_TEXT["flow_failed"]),
        msg.AUTH_SCOPE_HINT,
    ]
    assert not token_path(livecraft_paths, UA.handle).exists()


def test_login_timeout_is_failed_without_second_attempt(livecraft_paths: LivecraftPaths) -> None:
    """Вход не завершён за LOGIN_TIMEOUT_SEC: FAILED с текстом причины, второго входа нет, другой канал входит."""
    ua, other = two_channels()
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {ua.key, other.key}
    platform.fail_login[ua.key] = PlatformError.of_login(TIMEOUT, PlatformCode.AUTH_FAILED)
    record: ConsoleRecord = ConsoleRecord()
    book: ChannelBook = book_of(platform, livecraft_paths, record)
    book.log_in_needed((ua, other))
    channel: Channel = book.channel(ua)
    assert channel.status is ChannelStatus.FAILED and channel.login_attempts == 1
    expected: str = AuthErrorReason.LOGIN_TIMEOUT.human
    assert channel.error is not None and str(channel.error) == expected and "10 минут" in expected
    assert platform.logins.count(ua.key) == 1
    failed: str = msg.AUTH_FAILED.format(account_name="yt_ua", handle="@yt_ua", reason=expected)
    assert failed in record.lines and msg.AUTH_SCOPE_HINT not in record.lines   # экрана согласия могло и не быть
    assert book.channel(other).status is ChannelStatus.READY
    assert not token_path(livecraft_paths, ua.handle).exists()           # следующий запуск снова предложит вход


def test_login_with_other_title_aligns_the_channel_in_the_same_run(livecraft_paths: LivecraftPaths) -> None:
    """§14 решение 25: ник совпал, название на YouTube новое — токен записан, channels.json выровнен, и объект
    канала несёт новое название уже в этом запуске."""
    written_channels(livecraft_paths, UA)
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua"}
    platform.channel_info["yt_ua"] = channel_info(UA, title="Новое название")
    book: ChannelBook = book_of(platform, livecraft_paths)
    channel: Channel = book.log_in(UA)
    assert channel.status is ChannelStatus.READY and channel.config.account_name == "Новое название"
    assert [item.account_name for item in ChannelsFile.of(livecraft_paths).load().channels] == ["Новое название"]
    assert token_path(livecraft_paths, UA.handle).exists()
    [warning] = book.sync.take_warnings()
    assert warning == msg.WARNING_CHANNEL_ALIGNED.format(
        youtube_channel_id="UCfakeyt_ua", title_before="yt_ua", handle_before="@yt_ua",
        title_after="Новое название", handle_after="@yt_ua",
    )


def test_login_with_other_handle_confirmed_by_passport_is_found_by_both_handles(livecraft_paths: LivecraftPaths) -> None:
    """Ник сменился на YouTube, паспорт подтверждает id: токен под новым ником, книга находит канал по обоим."""
    written_channels(livecraft_paths, UA)
    passport: ChannelPassport = ChannelPassport(livecraft_paths.file(FileName.PASSPORT))
    passport.record_verified(
        ChannelVerification(UA, UA, FakePlatform.default_channel_info(UA), "@yt_ua.token.json", "01-09-2026 10:00")
    )
    assert passport.save() is None
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua"}
    platform.channel_info["yt_ua"] = channel_info(UA, handle_raw="@yt_ua_new")
    book: ChannelBook = book_of(platform, livecraft_paths)
    channel: Channel = book.log_in(UA)
    assert channel.status is ChannelStatus.READY and channel.config.handle == "@yt_ua_new"
    assert channel.token_file == token_path(livecraft_paths, "@yt_ua_new") and channel.token_file.exists()
    assert not token_path(livecraft_paths, UA.handle).exists()
    assert book.channel(UA) is channel and book.channel(channel.config) is channel


def test_token_that_did_not_save_is_a_warning_and_the_channel_works(livecraft_paths: LivecraftPaths) -> None:
    written_channels(livecraft_paths, UA)
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua"}
    unwritable: AuthError = AuthError(AuthErrorReason.TOKEN_UNWRITABLE, "@yt_ua.token.json")
    platform.fail_keep["yt_ua"] = PlatformError.of_login(unwritable, PlatformCode.AUTH_FAILED)
    book: ChannelBook = book_of(platform, livecraft_paths)
    assert book.log_in(UA).status is ChannelStatus.READY
    assert not token_path(livecraft_paths, UA.handle).exists()
    assert book.sync.take_warnings() == [
        msg.WARNING_TOKEN_SAVE_FAILED.format(
            account_name="yt_ua", handle="@yt_ua", error=msg.AUTH_REASON_TEXT["token_unwritable"]
        )
    ]


def test_forced_login_keeps_old_token_until_confirmed(livecraft_paths: LivecraftPaths) -> None:
    token: Path = written_token(livecraft_paths, UA.handle, "old")
    platform: FakePlatform = FakePlatform()
    platform.login_answers["yt_ua"] = [channel_info(UA, handle_raw="@other")] * LOGIN_MAX_ATTEMPTS
    assert book_of(platform, livecraft_paths).log_in(UA, force=True).status is ChannelStatus.REFUSED
    assert token.read_text(encoding="utf-8") == "old"
    platform.login_answers["yt_ua"] = [FakePlatform.default_channel_info(UA)]
    assert book_of(platform, livecraft_paths).log_in(UA, force=True).status is ChannelStatus.READY
    assert token.read_text(encoding="utf-8") == FAKE_TOKEN_TEXT


def test_forced_login_says_why_before_the_browser(livecraft_paths: LivecraftPaths) -> None:
    """--auth: причина входа — FORCED, строка перед браузером называет её словами."""
    written_token(livecraft_paths, UA.handle, "old")
    platform: FakePlatform = FakePlatform()
    platform.login_answers["yt_ua"] = [FakePlatform.default_channel_info(UA)]
    record: ConsoleRecord = ConsoleRecord()
    channel: Channel = book_of(platform, livecraft_paths, record).log_in(UA, force=True)
    assert channel.login_need is LoginNeed.FORCED
    forced: str = msg.AUTH_STARTING.format(account_name="yt_ua", handle="@yt_ua", reason=msg.AUTH_LOGIN_NEEDS["forced"])
    assert record.lines[0] == forced


def test_every_login_need_has_words() -> None:
    assert [need.human for need in LoginNeed] == [
        "токена канала ещё нет — первый вход",
        "Google больше не принимает токен канала",
        "прежний токен вёл на другой канал и удалён",
        "вход заново по --auth",
    ]


def test_login_phase_logs_in_each_listed_channel_once(livecraft_paths: LivecraftPaths) -> None:
    """Фаза входов: только каналы из списка (с эфирами) и только NEEDS_LOGIN; повтор в списке — один вход."""
    ua, ru = two_channels()
    channels: ConfiguredChannels = written_channels(livecraft_paths, ua, ru)
    platform: FakePlatform = FakePlatform()
    platform.tokens_missing = {"yt_ua", "yt_ru"}
    book: ChannelBook = book_of(platform, livecraft_paths)
    book.check_without_login(channels)
    book.log_in_needed((ua, ua))
    assert platform.logins == ["yt_ua"]
    assert book.channel(ru).status is ChannelStatus.NEEDS_LOGIN
