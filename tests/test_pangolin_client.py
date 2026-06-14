import pytest

from src.pangolin_client import PangolinClient, PangolinError


def test_pangolin_client_wraps_timeout_errors(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", raise_timeout)
    client = PangolinClient(api_token="token-123", timeout=0.01)

    with pytest.raises(PangolinError) as exc:
        client.keyword_search(keyword="milk frother", site="amz_us", zipcode="10041")

    assert "timeout" in str(exc.value).lower()
