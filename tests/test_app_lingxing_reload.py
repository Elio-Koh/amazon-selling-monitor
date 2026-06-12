import importlib
import sys
import types


class FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.secrets = {}

    def set_page_config(self, **kwargs):
        return None

    def cache_data(self, **kwargs):
        def decorator(func):
            func.clear = lambda: None
            return func

        return decorator

    def __getattr__(self, name):
        def noop(*args, **kwargs):
            return None

        return noop


class OldLingxingClient:
    def __init__(self, server_url, asin):
        self.server_url = server_url
        self.asin = asin


class NewLingxingClient:
    def __init__(self, server_url, asin, transport="auto"):
        self.server_url = server_url
        self.asin = asin
        self.transport = transport


def import_app_with_fake_streamlit(monkeypatch):
    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def test_create_lingxing_client_reloads_when_transport_keyword_hits_stale_class(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    stale_module = types.SimpleNamespace(LingxingClient=OldLingxingClient)
    reloaded_module = types.SimpleNamespace(LingxingClient=NewLingxingClient)
    reload_calls = []

    monkeypatch.setattr(app, "lingxing_client", stale_module)

    def fake_reload(module):
        reload_calls.append(module)
        return reloaded_module

    monkeypatch.setattr(app.importlib, "reload", fake_reload)

    client = app.create_lingxing_client(
        server_url="http://example.test/lingxing_config_B0GXYYZPBW/",
        asin="B0GXYYZPBW",
        transport="streamable_http",
    )

    assert reload_calls == [stale_module]
    assert isinstance(client, NewLingxingClient)
    assert client.transport == "streamable_http"
