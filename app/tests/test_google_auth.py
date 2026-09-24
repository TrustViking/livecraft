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
    PROMPT,
    SHEETS_SCOPE,
    YOUTUBE_SCOPE,
    AuthError,
    AuthErrorReason,
    GoogleLogin,
)
from app.paths import LivecraftPaths
from app.ui import messages_ru as msg

TOKEN_JSON: str = json.dumps({"token": "x", "refresh_token": "y"})
LOGIN_HINT: str = "owner@gmail.com"


class _FakeCredentials:
    def __init__(self, *, valid: bool = True, refresh_token: str | None = "y") -> None:
        self.valid: bool = valid
        self.refresh_token: str | None = refresh_token
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

    @classmethod
    def from_client_secrets_file(cls, path: str, scopes: list[str]) -> _FakeFlow:
        cls.last_kwargs = {"path": path, "scopes": scopes}
        return cls()

    def run_local_server(self, **kwargs: Any) -> _FakeCredentials:
        _FakeFlow.last_kwargs.update(kwargs)
        if _FakeFlow.error is not None:
            raise _FakeFlow.error
        return _FakeCredentials()


@pytest.fixture
def flow(monkeypatch: pytest.MonkeyPatch) -> type[_FakeFlow]:
    _FakeFlow.last_kwargs = {}
    _FakeFlow.error = None
    monkeypatch.setattr(auth_module, "InstalledAppFlow", _FakeFlow)
    return _FakeFlow


@pytest.fixture
def operator(livecraft_paths: LivecraftPaths) -> GoogleLogin:
    livecraft_paths.client_secret_file.write_text("{}", encoding="utf-8")
    return GoogleLogin.operator(livecraft_paths)


@pytest.fixture
def channel_login(operator: GoogleLogin, livecraft_paths: LivecraftPaths) -> GoogleLogin:
    """Вход, который сам нового токена не пишет (так будет у канала на этапе 4)."""
    return GoogleLogin(
        client_secret_file=operator.client_secret_file,
        token_file=livecraft_paths.secrets_dir / "@Osvald.X.token.json",
        scopes=(YOUTUBE_SCOPE,),
        login_hint=LOGIN_HINT,
        saves_new_login=False,
    )


def _token_reads(monkeypatch: pytest.MonkeyPatch, credentials: Any) -> list[list[str]]:
    """Подменить чтение токена: отдаёт `credentials`, запоминает скоупы каждого чтения."""
    scopes_seen: list[list[str]] = []

    def _read(cls: Any, path: str, scopes: list[str]) -> Any:
        scopes_seen.append(scopes)
        return credentials

    monkeypatch.setattr(auth_module.Credentials, "from_authorized_user_file", classmethod(_read))
    return scopes_seen


# --- личность оператора


def test_operator_reads_sheets_only_with_its_own_token(livecraft_paths: LivecraftPaths) -> None:
    login: GoogleLogin = GoogleLogin.operator(livecraft_paths)
    assert login.scopes == (SHEETS_SCOPE,)
    assert SHEETS_SCOPE == "https://www.googleapis.com/auth/spreadsheets.readonly"
    assert login.token_file == livecraft_paths.sheets_token_file
    assert login.token_file.name == "sheets.token.json"
    assert login.client_secret_file == livecraft_paths.client_secret_file
    assert login.login_hint is None
    assert login.saves_new_login is True


def test_youtube_scope_is_the_channel_one() -> None:
    assert YOUTUBE_SCOPE == "https://www.googleapis.com/auth/youtube"


def test_new_operator_login_is_saved_at_once(operator: GoogleLogin, flow: type[_FakeFlow]) -> None:
    operator.credentials()
    assert flow.last_kwargs["scopes"] == [SHEETS_SCOPE]
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
    assert str(livecraft_paths.secrets_dir) not in str(raised.value)
    assert flow.last_kwargs == {}


def test_valid_token_is_reused_without_browser(
    operator: GoogleLogin, flow: type[_FakeFlow], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator.token_file.write_text(TOKEN_JSON, encoding="utf-8")
    scopes_seen: list[list[str]] = _token_reads(monkeypatch, _FakeCredentials())
    logins: list[bool] = []
    operator.credentials(on_login=lambda: logins.append(True))
    assert flow.last_kwargs == {}
    assert logins == []
    assert scopes_seen == [[SHEETS_SCOPE]]


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

    def _raise(cls: Any, path: str, scopes: list[str]) -> None:
        raise OSError(13, "Permission denied", path)

    monkeypatch.setattr(auth_module.Credentials, "from_authorized_user_file", classmethod(_raise))
    with pytest.raises(AuthError) as raised:
        operator.credentials()
    assert raised.value.reason is AuthErrorReason.TOKEN_UNREADABLE
    assert "sheets.token.json" in str(raised.value)
    assert str(operator.token_file.parent) not in str(raised.value)
    assert str(operator.token_file.parent) not in raised.value.detail


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
        classmethod(lambda cls, path, scopes: pytest.fail("токен не должен читаться при force_reauth")),
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
    assert "client_secret.json" in str(raised.value)
    assert str(operator.client_secret_file.parent) not in str(raised.value)


# --- запись и удаление токена


def test_save_writes_and_drop_removes_the_token(operator: GoogleLogin) -> None:
    operator.save(_FakeCredentials())  # type: ignore[arg-type]
    assert operator.token_file.read_text(encoding="utf-8") == TOKEN_JSON
    operator.drop()
    operator.drop()                                       # файла уже нет — не ошибка
    assert not operator.token_file.exists()


def test_every_reason_has_a_russian_text() -> None:
    for reason in AuthErrorReason:
        assert reason.human
    assert set(msg.AUTH_REASON_TEXT) == {reason.value for reason in AuthErrorReason}
    assert AuthError(AuthErrorReason.LOGIN_REQUIRED).human == AuthErrorReason.LOGIN_REQUIRED.human


def test_scopes_live_only_in_the_auth_module(repo_root: Path) -> None:
    """§9: скоупы задаются в app\\google\\auth.py и больше нигде (тесты не в счёт)."""
    places: list[str] = [
        str(path.relative_to(repo_root))
        for path in (repo_root / "app").rglob("*.py")
        if "tests" not in path.parts and "googleapis.com/auth" in path.read_text(encoding="utf-8")
    ]
    assert places == [str(Path("app") / "google" / "auth.py")]
