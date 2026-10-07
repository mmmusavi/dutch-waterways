import pytest

from dutch_waterways import fis


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    """Serves ``total`` features at most ``server_max`` per request."""

    def __init__(self, total, server_max):
        self.total, self.server_max = total, server_max
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, dict(params)))
        start = params["resultOffset"]
        n = min(params["resultRecordCount"], self.server_max, self.total - start)
        feats = [{"type": "Feature", "properties": {"objectid": i}} for i in range(start, start + n)]
        return FakeResponse(
            {"features": feats, "exceededTransferLimit": start + n < self.total}
        )


@pytest.mark.parametrize("total, server_max", [(0, 1000), (999, 1000), (1000, 1000), (2500, 1000), (2500, 700)])
def test_fetch_layer_pages_until_done(total, server_max):
    session = FakeSession(total, server_max)
    fc = fis.fetch_layer("sections", session=session)
    ids = [f["properties"]["objectid"] for f in fc["features"]]
    assert ids == list(range(total))
    assert all(url.endswith("/58/query") for url, _ in session.calls)


def test_fetch_layer_bbox_and_numeric_id():
    session = FakeSession(3, 1000)
    fis.fetch_layer(49, bbox=(4.9, 52.0, 5.6, 52.6), session=session)
    url, params = session.calls[0]
    assert url.endswith("/49/query")
    assert params["geometry"] == "4.9,52.0,5.6,52.6"
    assert params["inSR"] == 4326


def test_fetch_layer_raises_on_service_error():
    class ErrorSession:
        def get(self, url, params, timeout):
            return FakeResponse({"error": {"code": 400, "message": "Invalid query"}})

    with pytest.raises(RuntimeError, match="Invalid query"):
        fis.fetch_layer("sections", session=ErrorSession())
