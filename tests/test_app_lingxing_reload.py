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

    def fetch_dashboard(self, start_date=None, end_date=None, **kwargs):
        return {
            "date_window": {"start_date": start_date, "end_date": end_date},
            "kwargs": kwargs,
        }


class StaleFetchLingxingClient(NewLingxingClient):
    def fetch_dashboard(self):
        return {"stale": True}


class OldMetrics(types.SimpleNamespace):
    def build_dashboard_summary(self, **kwargs):
        if "window_days" in kwargs:
            raise TypeError("build_dashboard_summary() got an unexpected keyword argument 'window_days'")
        return {"old": True}


class NewMetrics(types.SimpleNamespace):
    def build_dashboard_summary(self, **kwargs):
        return {"window_days": kwargs["window_days"]}


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


def test_fetch_dashboard_reloads_when_start_date_keyword_hits_stale_method(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    stale_module = types.SimpleNamespace(LingxingClient=StaleFetchLingxingClient)
    reloaded_module = types.SimpleNamespace(LingxingClient=NewLingxingClient)
    reload_calls = []

    monkeypatch.setattr(app, "lingxing_client", stale_module)

    def fake_reload(module):
        reload_calls.append(module)
        return reloaded_module

    monkeypatch.setattr(app.importlib, "reload", fake_reload)

    payload = app.fetch_dashboard_with_reload(
        server_url="http://example.test/lingxing_config_B0GXYYZPBW/",
        asin="B0GXYYZPBW",
        transport="streamable_http",
        start_date="2026-06-11",
        end_date="2026-06-11",
        sp_campaign_ids=("230170919088708",),
        known_non_sp_campaign_ids=(),
    )

    assert reload_calls == [stale_module]
    assert payload["date_window"] == {"start_date": "2026-06-11", "end_date": "2026-06-11"}
    assert payload["kwargs"]["sp_campaign_ids"] == ("230170919088708",)


def test_build_dashboard_summary_reloads_when_window_days_keyword_hits_stale_function(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    stale_metrics = OldMetrics()
    fresh_metrics = NewMetrics()
    reload_calls = []

    monkeypatch.setattr(app, "metrics", stale_metrics)

    def fake_reload(module):
        reload_calls.append(module)
        return fresh_metrics

    monkeypatch.setattr(app.importlib, "reload", fake_reload)

    summary = app.build_summary_with_reload(
        total_sales=100,
        total_orders=2,
        total_units=2,
        ad_summary={"sp": {}, "all_ads": {}, "by_product": {}},
        targets={
            "sp_target_acos": 0.5,
            "sp_daily_budget_current": 300,
            "sp_orders_daily_min": 1,
            "sp_orders_daily_max": 2,
        },
        window_days=7,
    )

    assert reload_calls == [stale_metrics]
    assert summary == {"window_days": 7}


def test_date_inputs_for_yesterday_show_resolved_window(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    calls = []

    class Columns(list):
        pass

    class FakeColumn:
        def __init__(self, index):
            self.index = index

        def selectbox(self, label, options, index=0):
            calls.append(("selectbox", label, options, index))
            return "Yesterday"

        def date_input(self, label, value, disabled=False):
            calls.append(("date_input", label, value.isoformat(), disabled))
            return value

        def button(self, label, use_container_width=False):
            calls.append(("button", label, use_container_width))
            return False

    monkeypatch.setattr(app.st, "columns", lambda spec: Columns([FakeColumn(0), FakeColumn(1), FakeColumn(2), FakeColumn(3)]))
    monkeypatch.setattr(app, "today_for_timezone", lambda timezone_name="Asia/Shanghai": __import__("datetime").date(2026, 6, 12))
    monkeypatch.setattr(app.st, "title", lambda *args, **kwargs: None)
    monkeypatch.setattr(app.st, "caption", lambda *args, **kwargs: None)

    window = app.render_header({"asin": "B0GXYYZPBW", "marketplace": "US"})

    assert window.start_date == "2026-06-11"
    assert ("date_input", "Start Date", "2026-06-11", False) in calls
    assert ("date_input", "End Date", "2026-06-11", False) in calls


def test_date_inputs_allow_manual_override_of_preset(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    from datetime import date

    class Columns(list):
        pass

    class FakeColumn:
        def selectbox(self, label, options, index=0):
            return "Last 7 Days"

        def date_input(self, label, value, disabled=False):
            if label == "Start Date":
                return date(2026, 6, 1)
            return date(2026, 6, 3)

        def button(self, label, use_container_width=False):
            return False

    monkeypatch.setattr(app.st, "columns", lambda spec: Columns([FakeColumn(), FakeColumn(), FakeColumn(), FakeColumn()]))
    monkeypatch.setattr(app, "today_for_timezone", lambda timezone_name="Asia/Shanghai": date(2026, 6, 12))
    monkeypatch.setattr(app.st, "title", lambda *args, **kwargs: None)
    monkeypatch.setattr(app.st, "caption", lambda *args, **kwargs: None)

    window = app.render_header({"asin": "B0GXYYZPBW", "marketplace": "US"})

    assert window.preset == "Custom"
    assert window.label == "Jun 1 - Jun 3"
    assert window.start_date == "2026-06-01"
    assert window.end_date == "2026-06-03"


def test_enrich_public_context_without_token_preserves_configured_keywords(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    data = {
        "asin": "B0GXYYZPBW",
        "context": {"listing": {"title": "Sample milk frother"}},
        "source_status": {"warnings": []},
    }

    enriched = app.enrich_public_context(
        data,
        {
            "asin": "B0GXYYZPBW",
            "marketplace": "US",
            "core_keywords": ["milk frother", "coffee frother"],
        },
    )

    assert enriched["context"]["public_context_status"]["status"] == "missing_token"
    assert enriched["context"]["core_keywords"][0]["keyword"] == "milk frother"
    assert enriched["context"]["core_keywords"][0]["rank_status"] == "not_checked"
    assert "PANGOLINFO_API_TOKEN" in enriched["source_status"]["warnings"][0]


def test_offer_value_formatting_uses_yes_no_and_none(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)

    assert app.offer_value(True) == "Yes"
    assert app.offer_value(False) == "No"
    assert app.offer_value(None) == "None"
    assert app.offer_value("") == "None"
