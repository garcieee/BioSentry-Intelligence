"""`python -m biosentry.api` refuses an unsafe configuration before it binds anything (CP7).

The launcher is the way to fail fast: started as `uvicorn --workers N`, every worker refuses
at import but uvicorn's supervisor respawns them forever. Here the parent exits non-zero with
the reason, before a socket is opened.
"""

import os
import subprocess
import sys

import pytest

from biosentry.api.__main__ import banner, is_loopback, plan
from biosentry.core.config import ConfigError

_DECLARATIONS = ("WEB_CONCURRENCY", "UVICORN_WORKERS", "BIOSENTRY_WORKERS")
ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - the address these tests exist to refuse
_SETTINGS = ("BIOSENTRY_CACHE", "BIOSENTRY_CACHE_TTL_S")


def launch(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in (*_DECLARATIONS, *_SETTINGS)}
    clean.update(env or {})
    return subprocess.run(  # noqa: S603 - our own interpreter and module, fixed arguments
        [sys.executable, "-m", "biosentry.api", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=clean,
        check=False,
    )


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--workers", "2"], {}),
        ([], {"WEB_CONCURRENCY": "3"}),
        ([], {"UVICORN_WORKERS": "2", "BIOSENTRY_CACHE": "none"}),
        (["--workers", "4"], {"BIOSENTRY_CACHE": "none"}),
        ([], {"BIOSENTRY_WORKERS": "2"}),
    ],
    ids=["flag", "WEB_CONCURRENCY", "UVICORN_WORKERS+no cache", "flag+no cache", "declared"],
)
def test_more_than_one_worker_exits_non_zero_with_the_reason_and_binds_nothing(
    args: list[str], env: dict[str, str]
) -> None:
    result = launch(*args, env=env)
    assert result.returncode == 2
    assert "refusing to start" in result.stderr
    assert "single worker" in result.stderr
    assert "Uvicorn running" not in result.stderr  # the server never started
    assert result.stdout == ""


def test_a_cache_ttl_above_the_staleness_ceiling_exits_non_zero() -> None:
    result = launch(env={"BIOSENTRY_CACHE_TTL_S": "600"})
    assert result.returncode == 2
    assert "staleness" in result.stderr


def test_an_unparseable_worker_count_is_refused_not_read_as_one() -> None:
    result = launch(env={"WEB_CONCURRENCY": "several"})
    assert result.returncode == 2
    assert "WEB_CONCURRENCY" in result.stderr


# --- identity is a stub: loopback unless told otherwise, and loud about it -------------------


@pytest.fixture
def no_declarations(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*_DECLARATIONS, *_SETTINGS):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2"])
def test_loopback_addresses_are_loopback(host: str) -> None:
    assert is_loopback(host)


@pytest.mark.parametrize(
    "host", [ALL_INTERFACES, "::", "192.168.1.20", "10.0.0.5", "example.org", ""]
)
def test_everything_else_is_not(host: str) -> None:
    assert not is_loopback(host)


def test_the_default_is_loopback_one_worker_and_the_api_port(no_declarations: None) -> None:
    launch = plan([])
    assert (launch.host, launch.port, launch.settings.workers) == ("127.0.0.1", 8000, 1)
    assert launch.allow_remote is False


def test_a_remote_bind_is_refused_unless_it_is_asked_for_by_name(no_declarations: None) -> None:
    with pytest.raises(ConfigError) as refused:
        plan(["--host", ALL_INTERFACES])
    assert "stub" in str(refused.value)
    assert "--allow-remote" in str(refused.value)
    assert plan(["--host", ALL_INTERFACES, "--allow-remote"]).host == ALL_INTERFACES


def test_the_banner_says_the_identity_is_a_stub_every_time(no_declarations: None) -> None:
    text = banner(plan(["--port", "9100"]))
    assert "http://127.0.0.1:9100" in text
    assert "IDENTITY IS A STUB" in text
    assert "EXPOSED" not in text
    exposed = banner(plan(["--host", ALL_INTERFACES, "--allow-remote"]))
    assert "IDENTITY IS A STUB" in exposed
    assert "EXPOSED" in exposed


def test_the_launcher_process_refuses_a_remote_bind_before_serving() -> None:
    result = launch("--host", ALL_INTERFACES)
    assert result.returncode == 2
    assert f"refusing to bind {ALL_INTERFACES}" in result.stderr
    assert "Uvicorn running" not in result.stderr
