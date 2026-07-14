from engine.data.market_data import Bar
from .chips import chip_indicators
from .levels import levels_indicators
from .momentum import momentum_indicators
from .patterns import pattern_indicators
from .trend import trend_indicators
from .volume import volume_indicators


def compute_indicators(bars: list[Bar]) -> dict:
    """Compute and group all supported technical indicators for price bars."""
    if len(bars) < 30:
        raise ValueError("at least 30 bars are required")
    return {
        "trend": trend_indicators(bars),
        "momentum": momentum_indicators(bars),
        "volume": volume_indicators(bars),
        "levels": levels_indicators(bars),
        "chips": chip_indicators(bars),
        "patterns": pattern_indicators(bars),
    }
