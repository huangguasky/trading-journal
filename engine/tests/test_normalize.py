from engine.data.normalize import normalize_symbol


def test_normalize_cn():
    symbol = normalize_symbol("600519")
    assert symbol.market == "cn"
    assert symbol.display == "SH600519"
    assert symbol.provider_code == "600519.SS"


def test_normalize_hk():
    symbol = normalize_symbol("hk700")
    assert symbol.market == "hk"
    assert symbol.display == "HK0700"


def test_normalize_us():
    symbol = normalize_symbol("aapl")
    assert symbol.market == "us"
    assert symbol.display == "AAPL"

