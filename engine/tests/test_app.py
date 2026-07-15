from engine.app import Handler


def test_http_handler_exposes_json_transport_methods():
    """Keep health and API responses callable after adding module-level helpers."""
    assert callable(getattr(Handler, "read_json", None))
    assert callable(getattr(Handler, "send_json", None))
