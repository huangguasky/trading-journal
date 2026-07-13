from engine.data.market_data import MarketData


class AShareProvider(MarketData):
    """MarketData specialization reserved for mainland China providers."""
    market = "cn"
