"""Run the API in this process: `python -m biosentry.api [--host H] [--port P]`.

Settings are validated here, in the parent, before anything is bound: a configuration the app
refuses (more than one worker while state lives in process memory, a cache TTL above the
staleness ceiling, a non-loopback address) exits non-zero with its message.

Started as `uvicorn --workers N biosentry.api.main:app` instead, every worker refuses at import
and none ever serves, but uvicorn's supervisor respawns refusing workers in a loop and never
exits. This launcher is the way to fail fast; it always serves from a single process.

Identity is a stub (the bearer token IS the clinician id), so the launcher binds loopback
unless told otherwise and says so, loudly, every time it starts.
"""

import argparse
import ipaddress
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace

import uvicorn

from biosentry.core.config import ConfigError, Settings

from .app import create_app


@dataclass(frozen=True, slots=True)
class Launch:
    settings: Settings
    host: str
    port: int
    log_level: str
    allow_remote: bool


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a name other than localhost: not provably loopback


def plan(argv: Sequence[str] | None = None) -> Launch:
    """Parse and validate. Raises `ConfigError` for anything the process must refuse."""
    parser = argparse.ArgumentParser(prog="python -m biosentry.api", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: loopback)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--log-level", default="info", choices=["debug", "info", "warning", "error", "critical"]
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="refused above 1 while repositories, audit log or cache live in process memory",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="bind a non-loopback address although identity is a stub (synthetic data only)",
    )
    args = parser.parse_args(argv)
    # The environment is read here; the launcher's own flags are applied on top, and the
    # combination is validated again (Settings refuses unsafe combinations on creation).
    base = Settings.from_env(argv=())
    settings = replace(base, workers=max(base.workers, args.workers))
    if not is_loopback(args.host) and not args.allow_remote:
        raise ConfigError(
            f"refusing to bind {args.host}: identity is a stub (the bearer token is the "
            "clinician id), so anything that can reach the port can act as any clinician. "
            "Bind loopback (the default), or pass --allow-remote on a network where that is "
            "acceptable and the data is synthetic."
        )
    return Launch(settings, args.host, args.port, args.log_level, args.allow_remote)


def banner(launch: Launch) -> str:
    where = f"http://{launch.host}:{launch.port}"
    lines = [
        f"BioSentry API on {where}",
        "  IDENTITY IS A STUB: the bearer token IS the clinician id. Anyone who can reach this",
        "  port can act as any clinician. Synthetic data only; real authentication replaces",
        "  this before any non-synthetic use.",
    ]
    if not is_loopback(launch.host):
        lines.append(f"  EXPOSED: bound to {launch.host} (--allow-remote), not loopback.")
    lines.append("  State lives in this process's memory and resets on restart.")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    try:
        launch = plan(argv)
    except ConfigError as exc:
        sys.stderr.write(f"biosentry: {exc}\n")
        return 2
    sys.stderr.write(banner(launch))
    uvicorn.run(
        create_app(launch.settings),
        host=launch.host,
        port=launch.port,
        log_level=launch.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
