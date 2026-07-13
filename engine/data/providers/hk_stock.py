from engine.data.market_data import MarketData


class HKStockProvider(MarketData):
    """MarketData specialization reserved for Hong Kong providers."""
    market = "hk"
