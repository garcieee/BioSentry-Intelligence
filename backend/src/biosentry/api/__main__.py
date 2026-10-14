"""Run the API in this process: `python -m biosentry.api [--host H] [--port P]`.

Settings are validated here, in the parent, before anything is bound: a configuration the app
refuses (more than one worker while state lives in process memory, a cache TTL above the
staleness ceiling) exits non-zero with its message.

Started as `uvicorn --workers N biosentry.api.main:app` instead, every worker refuses at import
and none ever serves, but uvicorn's supervisor respawns refusing workers in a loop and never
exits. This launcher is the way to fail fast; it always serves from a single process.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace

import uvicorn

from biosentry.core.config import ConfigError, Settings

from .app import create_app


def main(argv: Sequence[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
    try:
        # The environment is read here; the launcher's own flags are applied on top, and the
        # combination is validated again (Settings refuses unsafe combinations on creation).
        base = Settings.from_env(argv=())
        settings = replace(base, workers=max(base.workers, args.workers))
    except ConfigError as exc:
        sys.stderr.write(f"biosentry: {exc}\n")
        return 2
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
