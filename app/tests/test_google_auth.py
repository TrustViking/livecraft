from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from google_auth_oauthlib.flow import WSGITimeoutError

from app.google import auth as auth_module
from app.google.auth import (
    ACCESS_TYPE,
    LOGIN_TIMEOUT_MINUTES,
    LOGIN_TIMEOUT_SEC,
    DOCUMENTS_SCOPE,
    DRIVE_SCOPE,
    PROMPT,
    SPREADSHEETS_SCOPE,
    YOUTUBE_SCOPE,
    AuthError,
    AuthErrorReason,
    GoogleLogin,
)
from app.observability.log_event import LogArea
from app.paths import DataDir, FileName, LivecraftPaths, write_text_atomically
from app.tests.fixtures.logs import LogCapture
from app.tools.code_standard.source import SourceKey, SourceTree
from app.ui import messages_ru as msg

TOKEN_JSON: str = json.dumps({"token": "x", "refresh_token": "y"})
LOGIN_HINT: str = "owner@gmail.com"
OPERATOR_SCOPES: tuple[str, ...] = (SPREADSHEETS_SCOPE, DOCUMENTS_SCOPE, DRIVE_SCOPE)
READONLY_SCOPE: str = "https://www.googleapis.com/auth/spreadsheets.readonly"


class _FakeCredentials:
    """Учётные данные: права токена (`scopes`) и права, выданные при входе (`granted_scopes`; None — Google не
    назвал их, как разрешает RFC 6749)."""

    def __init__(
        self,
        *,
        valid: bool = True,
        refresh_token: str | None = "y",
        scopes: tuple[str, ...] = OPERATOR_SCOPES,
        granted_scopes: list[str] | None = None,
    ) -> None:
        self.valid: bool = valid
        self.refresh_token: str | None = refresh_token
        self.scopes: tuple[str, ...] = scopes
        self.granted_scopes: list[str] | None = granted_scopes
        self.refreshed: bool = False

    def to_json(self) -> str:
        return TOKEN_JSON

    def refresh(self, request: Any) -> None:
        self.refreshed = True
        self.valid = True


class _FakeFlow:
    """Подмена InstalledAppFlow: запоминает, с какими параметрами открывали браузер."""

    last_kwargs: dict[str, Any] = {}
    error: Exception | None = None
    granted: list[str] | None = None

    @classmethod
    def from_client_secrets_file(cls, path: str, scopes: list[str]) -> _FakeFlow:
        cls.last_kwargs = {"path": path, "scopes": scopes}
        return cls()

    def run_local_server(self, **kwargs: Any) -> _FakeCredentials:
        _FakeFlow.last_kwargs.update(kwargs)
        if _FakeFlow.error is not None:
            raise _FakeFlow.error
        return _FakeCredentials(granted_scopes=_FakeFlow.granted)


@pytest.fixture
def flow(monkeypatch: pytest.MonkeyPatch) -> type[_FakeFlow]:
    _FakeFlow.last_kwargs = {}
    _FakeFlow.error = None
    _FakeFlow.granted = None
    monkeypatch.setattr(auth_module, "InstalledAppFlow", _FakeFlow)
    return _FakeFlow


@pytest.fixture
def operator(livecraft_paths: LivecraftPaths) -> GoogleLogin:
    livecraft_paths.file(FileName.CLIENT_SECRET).write_text("{}", encoding="utf-8")
    return GoogleLogin.operator(livecraft_paths)


@pytest.fixture
def channel_login(operator: GoogleLogin, livecraft_paths: LivecraftPaths) -> GoogleLogin:
    """Вход владельца канала: сам нового токена не пишет — его пишет площадка после подтверждения канала."""
    return GoogleLogin.owner(livecraft_paths, "@Kanal.X", LOGIN_HINT)


def _token_reads(monkeypatch: pytest.MonkeyPatch, credentials: Any) -> list[str]:
    """Подменить чтение токена: отдаёт `credentials`, запоминает файл каждого чтения. Права токена — его собственные:
    нужные входу права при чтении не подставляются."""
    files_read: list[str] = []

    def _read(cls: Any, path: str) -> Any:
        files_read.append(Path(path).name)
        return credentials

    monkeypatch.setattr(auth_module.Credentials, "from_authorized_user_file", classmethod(_read))
    return files_read


def _real_token(login: GoogleLogin, scopes: list[str]) -> str:
    """Файл действующего токена в том виде, в каком его пишет google-auth, с этими правами; вернуть текст файла.
    Срок — в будущем: к Google за обновлением тест не ходит."""
    text: str = json.dumps(
        {
            "token": "old", "refresh_token": "r", "client_id": "c", "client_secret": "s", "scopes": scopes,
            "expiry": "2999-01-01T00:00:00Z",
        }
    )
    login.token_file.write_text(text, encoding="utf-8")
    return text


# --- личность оператора


def test_operator_has_the_table_documents_and_drive_with_its_own_token(livecraft_paths: LivecraftPaths) -> None:
    """§9, §14 решение 27: оператор пишет ссылки в таблицу и кладёт превью и документы в папку Диска."""
    login: GoogleLogin = GoogleLogin.operator(livecraft_paths)
    assert login.scopes == OPERATOR_SCOPES
    assert SPREADSHEETS_SCOPE == "https://www.googleapis.com/auth/spreadsheets"
    assert DOCUMENTS_SCOPE == "https://www.googleapis.com/auth/documents"
    assert DRIVE_SCOPE == "https://www.googleapis.com/auth/drive"
    assert login.token_file == livecraft_paths.file(FileName.SHEETS_TOKEN)
    assert login.token_file.name == "sheets.token.json"
    assert login.client_secret_file == livecraft_paths.file(FileName.CLIENT_SECRET)
    assert login.login_hint is None
    assert login.saves_new_login is True


def test_youtube_scope_is_the_channel_one() -> None:
    assert YOUTUBE_SCOPE == "https://www.googleapis.com/auth/youtube"


def test_owner_has_only_youtube_with_a_token_per_channel(livecraft_paths: LivecraftPaths) -> None:
    """§9: владелец канала — только youtube, токен secrets\\<ник>.token.json, подсказка — почта аккаунта канала."""
    login: GoogleLogin = GoogleLogin.owner(livecraft_paths, "@Kanal.X", LOGIN_HINT)
    assert login.scopes == (YOUTUBE_SCOPE,)
    assert login.token_file == livecraft_paths.dir(DataDir.SECRETS) / "@Kanal.X.token.json"
    assert login.client_secret_file == livecraft_paths.file(FileName.CLIENT_SECRET)
    assert login.login_hint == LOGIN_HINT
    assert login.saves_new_login is False


def test_new_operator_login_is_saved_at_once(operator: GoogleLogin, flow: type[_FakeFlow]) -> None:
    operator.credentials()
    assert flow.last_kwargs["scopes"] == list(OPERATOR_SCOPES)
    assert "login_hint" not in flow.last_kwargs          # у оператора подсказки аккаунта нет
    assert operator.token_file.read_text(encoding="utf-8") == TOKEN_JSON


def test_login_that_does_not_save_leaves_no_token(channel_login: GoogleLogin, flow: type[_FakeFlow]) -> None:
    channel_login.credentials()
    assert flow.last_kwargs["login_hint"] == LOGIN_HINT
    assert flow.last_kwargs["scopes"] == [YOUTUBE_SCOPE]
    assert not channel_login.token_file.exists()         # запишет вызывающий после подтверждения канала


# --- токен


def test_missing_client_secret_is_reported(livecraft_paths: LivecraftPaths, flow: type[_FakeFlow]) -> None:
    with pytest.raises(AuthError) as raised:
        GoogleLogin.operator(livecraft_paths).credentials()
    assert raised.value.reason is AuthErrorReason.CLIENT_SECRET_MISSING
    assert raised.value.detail == "client_secret.json"
    assert str(livecraft_paths.dir(DataDir.SECRETS)) not in str(raised.value)
    assert flow.last_kwargs == {}


def test_valid_token_is_reused_without_browser(
    operator: GoogleLogin, flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator.token_file.write_text(TOKEN_JSON, encoding="utf-8")
    files_read: list[str] = _token_reads(monkeypatch, _FakeCredentials())
    logins: list[bool] = []
    operator.credentials(on_login=lambda: logins.append(True))
    assert flow.last_kwargs == {}
    assert logins == []
    assert files_read == ["sheets.token.json"]


def test_a_token_with_more_rights_than_needed_is_reused(
    operator: GoogleLogin, flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator.token_file.write_text(TOKEN_JSON, encoding="utf-8")
    token: _FakeCredentials = _FakeCredentials(scopes=(*OPERATOR_SCOPES, YOUTUBE_SCOPE))
    _token_reads(monkeypatch, token)
    assert operator.credentials() is token
    assert flow.last_kwargs == {}


def test_a_token_of_the_old_version_leads_to_the_browser_and_is_replaced_after_login(
    operator: GoogleLogin, flow: type[_FakeFlow]
) -> None:
    """Токен прежней версии (только чтение таблиц) — как нет токена: вход в браузере; файл заменяет только вход."""
    _real_token(operator, [READONLY_SCOPE])
    logins: list[bool] = []
    with LogCapture.on(LogArea.AUTH) as capture:
        operator.credentials(on_login=lambda: logins.append(True))
    assert logins == [True]
    assert flow.last_kwargs["scopes"] == list(OPERATOR_SCOPES)
    assert operator.token_file.read_text(encoding="utf-8") == TOKEN_JSON
    assert any(line.startswith("token_scopes_short file=sheets.token.json") for line in capture.messages())


def test_a_token_without_the_drive_is_not_used_when_login_is_not_allowed(
    operator: GoogleLogin, flow: type[_FakeFlow]
) -> None:
    before: str = _real_token(operator, [SPREADSHEETS_SCOPE, DOCUMENTS_SCOPE])
    with pytest.raises(AuthError) as raised:
        operator.credentials(allow_login=False)
    assert raised.value.reason is AuthErrorReason.LOGIN_REQUIRED
    assert flow.last_kwargs == {}
    assert operator.token_file.read_text(encoding="utf-8") == before       # прежний файл не тронут


def test_a_token_with_all_rights_is_read_from_the_file(operator: GoogleLogin, flow: type[_FakeFlow]) -> None:
    _real_token(operator, list(OPERATOR_SCOPES))
    credentials: Any = operator.credentials(allow_login=False)
    assert tuple(credentials.scopes) == OPERATOR_SCOPES


def test_expired_token_is_refreshed_and_written(
    operator: GoogleLogin, flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator.token_file.write_text("stale", encoding="utf-8")
    stale: _FakeCredentials = _FakeCredentials(valid=False)
    _token_reads(monkeypatch, stale)
    assert operator.credentials() is stale
    assert stale.refreshed is True
    assert flow.last_kwargs == {}
    assert operator.token_file.read_text(encoding="utf-8") == TOKEN_JSON


def test_expired_token_without_refresh_token_goes_to_browser(
    operator: GoogleLogin, flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator.token_file.write_text("stale", encoding="utf-8")
    _token_reads(monkeypatch, _FakeCredentials(valid=False, refresh_token=None))
    operator.credentials()
    assert flow.last_kwargs["port"] == 0


def test_revoked_token_falls_back_to_browser(
    operator: GoogleLogin, flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator.token_file.write_text("revoked", encoding="utf-8")
    revoked: _FakeCredentials = _FakeCredentials(valid=False)

    def _raise(request: Any) -> None:
        raise auth_module.RefreshError("invalid_grant")

    revoked.refresh = _raise  # type: ignore[method-assign]
    _token_reads(monkeypatch, revoked)
    logins: list[dict[str, Any]] = []
    operator.credentials(on_login=lambda: logins.append(dict(flow.last_kwargs)))
    assert logins == [{}]                                 # on_login — ровно перед браузером
    assert flow.last_kwargs["port"] == 0
    assert operator.token_file.read_text(encoding="utf-8") == TOKEN_JSON


def test_transport_failure_on_refresh_is_refresh_failed(
    operator: GoogleLogin, flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator.token_file.write_text("stale", encoding="utf-8")
    stale: _FakeCredentials = _FakeCredentials(valid=False)

    def _raise(request: Any) -> None:
        raise auth_module.TransportError("no network")

    stale.refresh = _raise  # type: ignore[method-assign]
    _token_reads(monkeypatch, stale)
    with pytest.raises(AuthError) as raised:
        operator.credentials()
    assert raised.value.reason is AuthErrorReason.REFRESH_FAILED
    assert flow.last_kwargs == {}
    assert operator.token_file.read_text(encoding="utf-8") == "stale"


def test_unreadable_token_is_reported_without_the_full_path(
    operator: GoogleLogin, flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator.token_file.write_text("{broken", encoding="utf-8")

    def _raise(cls: Any, path: str) -> None:
        raise OSError(13, "Permission denied", path)

    monkeypatch.setattr(auth_module.Credentials, "from_authorized_user_file", classmethod(_raise))
    with pytest.raises(AuthError) as raised:
        operator.credentials()
    assert raised.value.reason is AuthErrorReason.TOKEN_UNREADABLE
    assert "sheets.token.json" in raised.value.detail and "sheets.token.json" in raised.value.log_line
    for text in (str(raised.value), raised.value.detail, raised.value.log_line):
        assert str(operator.token_file.parent) not in text


def test_login_not_allowed_does_not_open_the_browser(operator: GoogleLogin, flow: type[_FakeFlow]) -> None:
    logins: list[bool] = []
    with pytest.raises(AuthError) as raised:
        operator.credentials(allow_login=False, on_login=lambda: logins.append(True))
    assert raised.value.reason is AuthErrorReason.LOGIN_REQUIRED
    assert flow.last_kwargs == {} and logins == []
    assert not operator.token_file.exists()


def test_force_reauth_opens_the_browser_without_reading_the_token(
    operator: GoogleLogin, flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator.token_file.write_text("old token", encoding="utf-8")
    monkeypatch.setattr(
        auth_module.Credentials,
        "from_authorized_user_file",
        classmethod(lambda cls, path: pytest.fail("токен не должен читаться при force_reauth")),
    )
    operator.credentials(force_reauth=True)
    assert flow.last_kwargs["port"] == 0


# --- браузер


def test_browser_runs_on_free_port_with_limited_wait_and_russian_texts(
    operator: GoogleLogin, flow: type[_FakeFlow]
) -> None:
    operator.credentials()
    assert flow.last_kwargs["port"] == 0
    assert flow.last_kwargs["access_type"] == ACCESS_TYPE == "offline"
    assert flow.last_kwargs["prompt"] == PROMPT == "select_account consent"
    assert flow.last_kwargs["timeout_seconds"] == LOGIN_TIMEOUT_SEC == 600
    assert flow.last_kwargs["authorization_prompt_message"] == msg.AUTH_OPEN_LINK
    assert flow.last_kwargs["success_message"] == msg.AUTH_BROWSER_DONE
    assert "{url}" in msg.AUTH_OPEN_LINK
    assert "планер" not in msg.AUTH_BROWSER_DONE.lower()


def test_browser_timeout_is_login_timeout(operator: GoogleLogin, flow: type[_FakeFlow]) -> None:
    """WSGITimeoutError наследует AttributeError: без отдельной ветки это было бы падение запуска."""
    flow.error = WSGITimeoutError("Timed out waiting for response from authorization server")
    with pytest.raises(AuthError) as raised:
        operator.credentials()
    assert raised.value.reason is AuthErrorReason.LOGIN_TIMEOUT
    assert not operator.token_file.exists()
    assert str(LOGIN_TIMEOUT_MINUTES) in raised.value.human


def test_browser_failure_is_flow_failed_without_the_full_path(
    operator: GoogleLogin, flow: type[_FakeFlow]
) -> None:
    flow.error = OSError(2, "No such file or directory", str(operator.client_secret_file))
    with pytest.raises(AuthError) as raised:
        operator.credentials()
    assert raised.value.reason is AuthErrorReason.FLOW_FAILED
    assert "client_secret.json" in raised.value.log_line
    for text in (str(raised.value), raised.value.log_line):
        assert str(operator.client_secret_file.parent) not in text


def test_a_login_without_all_permissions_is_refused_and_not_saved(
    operator: GoogleLogin, flow: type[_FakeFlow]
) -> None:
    """В окне входа сняли доступ к Диску: вход не принят, токен не записан, человеку — что отметить."""
    flow.granted = [SPREADSHEETS_SCOPE, DOCUMENTS_SCOPE]
    with pytest.raises(AuthError) as raised:
        operator.credentials()
    assert raised.value.reason is AuthErrorReason.SCOPES_NOT_GRANTED
    assert str(raised.value) == msg.AUTH_REASON_TEXT["scopes_not_granted"]
    assert DRIVE_SCOPE in raised.value.detail and SPREADSHEETS_SCOPE not in raised.value.detail
    assert not operator.token_file.exists()


def test_the_oauthlib_scope_warning_is_the_same_refusal(operator: GoogleLogin, flow: type[_FakeFlow]) -> None:
    """oauthlib встречает снятое разрешение предупреждением о смене прав с выданными правами."""
    warning: Warning = Warning("Scope has changed")
    warning.new_scope = [SPREADSHEETS_SCOPE]  # type: ignore[attr-defined]
    flow.error = warning
    with pytest.raises(AuthError) as raised:
        operator.credentials()
    assert raised.value.reason is AuthErrorReason.SCOPES_NOT_GRANTED
    assert DOCUMENTS_SCOPE in raised.value.detail and DRIVE_SCOPE in raised.value.detail
    assert not operator.token_file.exists()


def test_a_login_with_all_permissions_granted_is_saved(operator: GoogleLogin, flow: type[_FakeFlow]) -> None:
    flow.granted = [DRIVE_SCOPE, SPREADSHEETS_SCOPE, DOCUMENTS_SCOPE, "openid"]
    operator.credentials()
    assert operator.token_file.read_text(encoding="utf-8") == TOKEN_JSON


# --- запись и удаление токена


def test_save_writes_and_drop_removes_the_token(operator: GoogleLogin) -> None:
    operator.save(_FakeCredentials())  # type: ignore[arg-type]
    assert operator.token_file.read_text(encoding="utf-8") == TOKEN_JSON
    operator.drop()
    operator.drop()                                       # файла уже нет — не ошибка
    assert not operator.token_file.exists()


def test_save_goes_through_the_atomic_write(operator: GoogleLogin, monkeypatch: pytest.MonkeyPatch) -> None:
    """Токен пишется временным файлом и os.replace: оборванная запись не оставит испорченный токен."""
    calls: list[tuple[Path, str]] = []

    def _recording_write(path: Path, text: str, encoding: str) -> None:
        calls.append((path, encoding))
        write_text_atomically(path, text, encoding)

    monkeypatch.setattr(auth_module, "write_text_atomically", _recording_write)
    operator.save(_FakeCredentials())  # type: ignore[arg-type]
    assert calls == [(operator.token_file, "utf-8")]
    assert operator.token_file.read_bytes() == TOKEN_JSON.encode("utf-8")
    leftovers: list[Path] = [
        path for path in operator.token_file.parent.iterdir()
        if path.name.startswith(operator.token_file.name) and path != operator.token_file
    ]
    assert leftovers == []                                  # временный файл записи не остался рядом


def test_a_save_that_cannot_write_is_token_unwritable(livecraft_paths: LivecraftPaths, operator: GoogleLogin) -> None:
    """На месте папки токена лежит файл: mkdir падает — причина «не удаётся записать», а не «не читается»."""
    blocker: Path = livecraft_paths.root / "blocker"
    blocker.write_text("", encoding="utf-8")
    login: GoogleLogin = GoogleLogin(
        client_secret_file=operator.client_secret_file,
        token_file=blocker / "sheets.token.json",
        scopes=operator.scopes,
        login_hint=None,
        saves_new_login=True,
    )
    with pytest.raises(AuthError) as raised:
        login.save(_FakeCredentials())  # type: ignore[arg-type]
    assert raised.value.reason is AuthErrorReason.TOKEN_UNWRITABLE
    assert str(livecraft_paths.root) not in str(raised.value)


def test_a_drop_that_cannot_remove_is_token_unwritable(operator: GoogleLogin) -> None:
    """На месте файла токена папка: удалить её как файл нельзя — причина «не удаётся удалить»."""
    operator.token_file.mkdir(parents=True)
    with pytest.raises(AuthError) as raised:
        operator.drop()
    assert raised.value.reason is AuthErrorReason.TOKEN_UNWRITABLE
    assert operator.token_file.is_dir()


def test_every_reason_has_a_russian_text() -> None:
    for reason in AuthErrorReason:
        assert reason.human
    assert set(msg.AUTH_REASON_TEXT) == {reason.value for reason in AuthErrorReason}
    assert AuthError(AuthErrorReason.LOGIN_REQUIRED).human == AuthErrorReason.LOGIN_REQUIRED.human


def test_the_auth_error_follows_the_error_contract() -> None:
    """Человеку — русская причина; имя файла и подробность — только в строку лога (§11)."""
    error: AuthError = AuthError(AuthErrorReason.CLIENT_SECRET_MISSING, "client_secret.json")
    assert str(error) == error.human == AuthErrorReason.CLIENT_SECRET_MISSING.human
    assert error.log_line == "auth_failed reason=client_secret_missing detail=client_secret.json"
    assert AuthError(AuthErrorReason.LOGIN_REQUIRED).log_line == "auth_failed reason=login_required detail=-"


def test_scopes_live_only_in_the_auth_module(repo_root: Path) -> None:
    """§9: скоупы задаются в app\\google\\auth.py и больше нигде (тесты не в счёт)."""
    places: list[str] = [
        module.key.text for module in SourceTree.from_root(repo_root).production if "googleapis.com/auth" in module.text
    ]
    assert places == [SourceKey.of("app/google/auth.py").text]
