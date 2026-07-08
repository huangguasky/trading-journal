from __future__ import annotations

import argparse

from engine.analysis.market_pipeline import MarketPipeline
from engine.analysis.stock_pipeline import StockPipeline
from engine.config import get_settings
from engine.storage.db import Database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock")
    parser.add_argument("--watchlist", nargs="*")
    parser.add_argument("--market", choices=["cn", "hk", "us"])
    args = parser.parse_args()
    settings = get_settings()
    db = Database(settings.db_path)
    if args.stock:
        print(StockPipeline(db).analyze(args.stock)["markdown"])
    if args.watchlist:
        print(StockPipeline(db).analyze_watchlist(args.watchlist))
    if args.market:
        print(MarketPipeline(db).analyze(args.market)["markdown"])


if __name__ == "__main__":
    main()

