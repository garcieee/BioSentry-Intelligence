"""Write the synthetic dataset: python -m biosentry.sim --out data/synthetic/synthetic.json"""

import argparse
from pathlib import Path

from .assemble import DEFAULT_SEED, build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the synthetic ward (I6: synthetic only)."
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(args.seed).dumps(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
