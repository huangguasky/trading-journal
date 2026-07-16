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
    assert symbol.provider_code == "0700.HK"


def test_normalize_hk_equivalent_formats():
    expected = ("hk", "HK1810", "1810.HK")
    for value in ("HK1810", "hk01810", "1810.HK", "01810.hk"):
        symbol = normalize_symbol(value)
        assert (symbol.market, symbol.display, symbol.provider_code) == expected

    expected_short = ("hk", "HK0700", "0700.HK")
    for value in ("HK700", "hk00700", "700.HK", "00700.hk"):
        symbol = normalize_symbol(value)
        assert (symbol.market, symbol.display, symbol.provider_code) == expected_short


def test_normalize_bare_hk_code():
    symbol = normalize_symbol("1810")
    assert (symbol.market, symbol.display, symbol.provider_code) == ("hk", "HK1810", "1810.HK")


def test_normalize_us():
    symbol = normalize_symbol("aapl")
    assert symbol.market == "us"
    assert symbol.display == "AAPL"
