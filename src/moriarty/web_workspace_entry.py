from __future__ import annotations

import argparse

from moriarty.webapp import serve_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moriarty-local web-workspace",
        description="Start the local Gökbörü Intelligence workspace.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir")
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    serve_workspace(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir,
        open_browser=not args.no_browser,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
