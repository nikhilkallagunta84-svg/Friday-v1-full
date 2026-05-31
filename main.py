from __future__ import annotations

import argparse

from friday.config import FridayConfig
from friday.server import run_server
from friday.self_test import run_self_test


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FRIDAY local assistant")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--silent-tts", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = FridayConfig.load(host=args.host, port=args.port, silent_tts=args.silent_tts)
    if args.self_test:
        return run_self_test(config)
    run_server(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
