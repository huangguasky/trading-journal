from engine.data.market_data import MarketData


class USStockProvider(MarketData):
    """MarketData specialization reserved for United States providers."""
    market = "us"
