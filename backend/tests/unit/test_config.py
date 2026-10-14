"""Settings refuse a combination that cannot be run safely (CP7): the worker guard and the
staleness ceiling on the cache TTL. The process fails to start with a message naming the fix."""

import math

import pytest

from biosentry.core.config import (
    DEFAULT_CACHE_TTL_S,
    SHORTEST_STALENESS_S,
    ConfigError,
    Settings,
    declared_workers,
    in_process_state,
)

# --- how many workers a start-up declares -------------------------------------------------


@pytest.mark.parametrize(
    ("env", "argv", "expected"),
    [
        ({}, [], 1),
        ({"WEB_CONCURRENCY": "1"}, [], 1),
        ({"WEB_CONCURRENCY": "4"}, [], 4),
        ({"UVICORN_WORKERS": "3"}, [], 3),
        ({"BIOSENTRY_WORKERS": "2"}, [], 2),
        ({"WEB_CONCURRENCY": ""}, [], 1),
        ({}, ["uvicorn", "biosentry.api.main:app", "--workers", "5"], 5),
        ({}, ["uvicorn", "biosentry.api.main:app", "--workers=6"], 6),
        ({}, ["gunicorn", "-w", "2", "biosentry.api.main:app"], 2),
        ({}, ["gunicorn", "-w=3"], 3),
        ({"WEB_CONCURRENCY": "2"}, ["--workers", "7"], 7),  # the largest declaration wins
        ({}, ["--workers", "0"], 1),  # uvicorn treats 0 as one
        ({}, ["--port", "8000", "--log-level", "warning"], 1),
    ],
)
def test_the_most_declared_workers_wins(
    env: dict[str, str], argv: list[str], expected: int
) -> None:
    assert declared_workers(env, argv) == expected


@pytest.mark.parametrize(
    ("env", "argv"),
    [
        ({"WEB_CONCURRENCY": "many"}, []),
        ({"UVICORN_WORKERS": "2.5"}, []),
        ({"BIOSENTRY_WORKERS": "-1"}, []),
        ({}, ["--workers", "lots"]),
        ({}, ["--workers"]),
        ({}, ["-w", "-3"]),
    ],
)
def test_a_declaration_that_does_not_parse_is_an_error_never_one_worker(
    env: dict[str, str], argv: list[str]
) -> None:
    with pytest.raises(ConfigError):
        declared_workers(env, argv)


# --- the guard ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "argv"),
    [
        ({"WEB_CONCURRENCY": "2"}, []),
        ({"UVICORN_WORKERS": "3"}, []),
        ({"BIOSENTRY_WORKERS": "2"}, []),
        ({}, ["--workers", "4"]),
        ({}, ["-w", "2"]),
    ],
)
def test_more_than_one_worker_refuses_to_start_and_names_the_fix(
    env: dict[str, str], argv: list[str]
) -> None:
    with pytest.raises(ConfigError) as refused:
        Settings.from_env(env, argv)
    message = str(refused.value)
    assert "refusing to start" in message
    assert "single worker" in message
    assert "repositories" in message  # the whole app is in-process, not only the cache


def test_the_refusal_covers_the_whole_app_even_with_the_cache_off() -> None:
    with pytest.raises(ConfigError) as refused:
        Settings.from_env({"BIOSENTRY_CACHE": "none", "WEB_CONCURRENCY": "2"})
    message = str(refused.value)
    assert "repositories" in message
    assert "audit log" in message
    assert "snapshot cache" not in message


def test_the_message_names_every_part_that_is_in_process() -> None:
    with pytest.raises(ConfigError) as refused:
        Settings(workers=3)
    message = str(refused.value)
    assert "3 workers" in message
    assert "the repositories, the audit log and the snapshot cache" in message


@pytest.mark.parametrize("env", [{}, {"WEB_CONCURRENCY": "1"}, {"UVICORN_WORKERS": "1"}])
def test_a_single_worker_starts(env: dict[str, str]) -> None:
    assert Settings.from_env(env).workers == 1


def test_a_database_repository_lifts_the_guard_for_what_it_holds() -> None:
    assert in_process_state(cache="memory") == ("repositories", "audit log", "snapshot cache")
    assert in_process_state(cache="none") == ("repositories", "audit log")
    # A future non-memory repository: only the in-memory cache is still per-process.
    assert in_process_state(cache="memory", repository="postgres") == ("snapshot cache",)
    assert in_process_state(cache="none", repository="postgres") == ()


# --- the cache settings -------------------------------------------------------------------


def test_defaults_are_a_memory_cache_inside_the_staleness_ceiling() -> None:
    settings = Settings()
    assert (settings.cache, settings.cache_ttl_s) == ("memory", DEFAULT_CACHE_TTL_S)
    assert 0 < DEFAULT_CACHE_TTL_S <= SHORTEST_STALENESS_S


def test_the_ttl_may_equal_the_staleness_ceiling_and_not_exceed_it() -> None:
    assert Settings(cache_ttl_s=SHORTEST_STALENESS_S).cache_ttl_s == SHORTEST_STALENESS_S
    with pytest.raises(ConfigError, match="staleness"):
        Settings(cache_ttl_s=SHORTEST_STALENESS_S + 0.1)


@pytest.mark.parametrize("ttl", [0.0, -5.0, math.nan, math.inf])
def test_a_ttl_that_is_not_a_positive_finite_number_is_refused(ttl: float) -> None:
    with pytest.raises(ConfigError):
        Settings(cache_ttl_s=ttl)


def test_cache_settings_come_from_the_environment_and_are_validated() -> None:
    settings = Settings.from_env({"BIOSENTRY_CACHE": "none", "BIOSENTRY_CACHE_TTL_S": "15"})
    assert (settings.cache, settings.cache_ttl_s) == ("none", 15.0)
    for env in (
        {"BIOSENTRY_CACHE": "redis"},
        {"BIOSENTRY_CACHE_TTL_S": "soon"},
        {"BIOSENTRY_CACHE_TTL_S": "61"},
    ):
        with pytest.raises(ConfigError):
            Settings.from_env(env)
    with pytest.raises(ConfigError):
        Settings(cache="redis")  # type: ignore[arg-type]
