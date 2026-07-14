from __future__ import annotations

import argparse

from engine.app import build_market_pipeline, build_stock_pipeline
from engine.config import get_settings
from engine.storage.db import Database


def main() -> None:
    """Parse CLI options and run the requested stock, watchlist, or market analysis."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock")
    parser.add_argument("--watchlist", nargs="*")
    parser.add_argument("--market", choices=["cn", "hk", "us"])
    args = parser.parse_args()
    settings = get_settings()
    db = Database(settings.db_path)
    if args.stock:
        print(build_stock_pipeline().analyze(args.stock)["markdown"])
    if args.watchlist:
        print(build_stock_pipeline().analyze_watchlist(args.watchlist))
    if args.market:
        print(build_market_pipeline().analyze(args.market)["markdown"])


if __name__ == "__main__":
    main()
