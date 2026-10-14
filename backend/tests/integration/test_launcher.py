"""`python -m biosentry.api` refuses an unsafe configuration before it binds anything (CP7).

The launcher is the way to fail fast: started as `uvicorn --workers N`, every worker refuses
at import but uvicorn's supervisor respawns them forever. Here the parent exits non-zero with
the reason, before a socket is opened.
"""

import os
import subprocess
import sys

import pytest

_DECLARATIONS = ("WEB_CONCURRENCY", "UVICORN_WORKERS", "BIOSENTRY_WORKERS")
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
