from io import BytesIO

from engine.app import Handler


def test_http_handler_exposes_json_transport_methods():
    """Keep health and API responses callable after adding module-level helpers."""
    assert callable(getattr(Handler, "read_json", None))
    assert callable(getattr(Handler, "send_json", None))


def test_health_exposes_engine_version_to_cross_origin_desktop_client():
    """Release webviews must be able to read the engine compatibility header."""
    class ResponseRecorder:
        def __init__(self):
            self.headers = {}
            self.wfile = BytesIO()

        def send_response(self, status):
            self.status = status

        def send_header(self, name, value):
            self.headers[name] = value

        def end_headers(self):
            return None

    response = ResponseRecorder()
    Handler.send_json(response, {"ok": True})
    assert response.headers["X-Trading-Journal-Engine"] == "4"
    assert response.headers["Access-Control-Expose-Headers"] == "X-Trading-Journal-Engine"
    assert response.headers["Access-Control-Allow-Private-Network"] == "true"
