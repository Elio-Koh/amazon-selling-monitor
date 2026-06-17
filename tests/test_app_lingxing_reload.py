import importlib
import importlib.util
import sys
import types


class FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.secrets = {}
        self.session_state = SessionState()

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


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


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


class StalePublicContext(types.SimpleNamespace):
    def build_public_context(self, **kwargs):
        if "leaf_category_label" in kwargs:
            raise TypeError("build_public_context() got an unexpected keyword argument 'leaf_category_label'")
        return {"public_context_status": {"status": "stale"}}


class FreshPublicContext(types.SimpleNamespace):
    def build_public_context(self, **kwargs):
        return {
            "public_context_status": {
                "status": "ok",
                "message": "Pangolin public context loaded.",
                "source": "pangolin",
                "freshness": "2026-06-14T00:01:00Z",
            },
            "rank": {"own_bsr_leaf_rank": 53},
        }


def import_app_with_fake_streamlit(monkeypatch):
    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())
    install_fake_cryptography_if_missing(monkeypatch)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def install_fake_cryptography_if_missing(monkeypatch):
    if importlib.util.find_spec("cryptography") is not None:
        return

    class FakeAESGCM:
        def __init__(self, key):
            self.key = key

        def encrypt(self, nonce, data, associated_data):
            return data

        def decrypt(self, nonce, data, associated_data):
            return data

    cryptography_module = types.ModuleType("cryptography")
    hazmat_module = types.ModuleType("cryptography.hazmat")
    primitives_module = types.ModuleType("cryptography.hazmat.primitives")
    ciphers_module = types.ModuleType("cryptography.hazmat.primitives.ciphers")
    aead_module = types.ModuleType("cryptography.hazmat.primitives.ciphers.aead")
    aead_module.AESGCM = FakeAESGCM

    monkeypatch.setitem(sys.modules, "cryptography", cryptography_module)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat", hazmat_module)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives", primitives_module)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers", ciphers_module)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", aead_module)


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
        server_url="http://example.test/lingxing_config_B0TEST0001/",
        asin="B0TEST0001",
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
        server_url="http://example.test/lingxing_config_B0TEST0001/",
        asin="B0TEST0001",
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


def test_build_public_context_reloads_when_leaf_keyword_hits_stale_function(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    stale_public_context = StalePublicContext()
    fresh_public_context = FreshPublicContext()
    reload_calls = []

    monkeypatch.setattr(app, "public_context", stale_public_context)

    def fake_reload(module):
        reload_calls.append(module)
        return fresh_public_context

    monkeypatch.setattr(app.importlib, "reload", fake_reload)

    result = app.build_public_context_with_reload(
        asin="B0TEST0001",
        marketplace="US",
        zipcode="10041",
        core_keywords=["milk frother"],
        pinned_competitor_asins=[],
        excluded_competitor_asins=[],
        leaf_category_label="Milk Frothers",
    )

    assert reload_calls == [stale_public_context]
    assert result["rank"]["own_bsr_leaf_rank"] == 53


def test_own_ranking_values_use_major_and_leaf_rows(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)

    values = app.own_ranking_values(
        {
            "own_bsr_major_rank": 8,
            "own_bsr_major_category": "Kitchen & Dining",
            "own_bsr_leaf_rank": 2,
            "own_bsr_leaf_category": "Milk Frothers",
            "own_bsr_leaf_source": "pangolin:amzBestSellers",
            "own_new_release_major_rank": 3,
            "own_new_release_major_category": "Kitchen & Dining",
            "own_new_release_leaf_rank": 3,
            "own_new_release_leaf_category": "Milk Frothers",
            "own_new_release_leaf_source": "pangolin:amzNewReleases",
            "bsr_capture_status": "measured",
        }
    )

    assert values == {
        "BSR Major Category Rank": "8",
        "BSR Major Category": "Kitchen & Dining",
        "BSR Leaf Category Rank": "2",
        "BSR Leaf Category": "Milk Frothers",
        "BSR Leaf Source": "pangolin:amzBestSellers",
        "New Release Major Category Rank": "3",
        "New Release Major Category": "Kitchen & Dining",
        "New Release Leaf Category Rank": "3",
        "New Release Leaf Category": "Milk Frothers",
        "New Release Leaf Source": "pangolin:amzNewReleases",
        "BSR Capture Status": "measured",
    }
    assert "Best Seller Rank" not in values
    assert "New Release Rank" not in values


def test_own_ranking_values_hide_empty_new_release_major_rows(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)

    values = app.own_ranking_values(
        {
            "own_bsr_major_rank": 32132,
            "own_bsr_major_category": "Home & Kitchen",
            "own_bsr_leaf_rank": 53,
            "own_bsr_leaf_category": "Milk Frothers",
            "own_new_release_leaf_rank": 4,
            "own_new_release_leaf_category": "Milk Frothers",
            "own_new_release_leaf_source": "pangolin:amzNewReleases",
            "bsr_capture_status": "measured",
        }
    )

    assert "New Release Major Category Rank" not in values
    assert "New Release Major Category" not in values
    assert values["New Release Leaf Category Rank"] == "4"
    assert values["New Release Leaf Category"] == "Milk Frothers"


def test_attach_operations_context_copies_supply_snapshot(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    data = {"context": {"inventory": {"fba_fulfillable": 120}}, "source_status": {"warnings": []}}
    operations = {
        "sales_plan": {"planned_daily_units": 100},
        "stockout_risk": {"level": "high", "coverage_days": 25.0},
    }

    result = app.attach_operations_context(data, operations)

    assert result["context"]["operations"] == operations
    assert data["context"].get("operations") is None


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

    window = app.render_header({"asin": "B0TEST0001", "marketplace": "US"})

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

    window = app.render_header({"asin": "B0TEST0001", "marketplace": "US"})

    assert window.preset == "Custom"
    assert window.label == "Jun 1 - Jun 3"
    assert window.start_date == "2026-06-01"
    assert window.end_date == "2026-06-03"


def test_enrich_public_context_without_token_preserves_configured_keywords(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    data = {
        "asin": "B0TEST0001",
        "context": {"listing": {"title": "Sample milk frother"}},
        "source_status": {"warnings": []},
    }

    enriched = app.enrich_public_context(
        data,
        {
            "asin": "B0TEST0001",
            "marketplace": "US",
            "core_keywords": ["milk frother", "coffee frother"],
        },
    )

    assert enriched["context"]["public_context_status"]["status"] == "missing_token"
    assert enriched["context"]["core_keywords"][0]["keyword"] == "milk frother"
    assert enriched["context"]["core_keywords"][0]["rank_status"] == "not_checked"
    assert "PANGOLINFO_API_TOKEN" in enriched["source_status"]["warnings"][0]


def test_load_market_context_downgrades_unexpected_timeout(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    data = {
        "asin": "B0TEST0001",
        "context": {"listing": {"title": "Sample milk frother"}},
        "source_status": {"warnings": []},
    }

    def raise_timeout(*args, **kwargs):
        raise TimeoutError("Pangolin keyword search timed out")

    monkeypatch.setattr(app, "enrich_public_context", raise_timeout)

    result = app.load_market_context(
        1,
        data,
        {
            "asin": "B0TEST0001",
            "marketplace": "US",
            "core_keywords": ["milk frother", "coffee frother"],
        },
    )

    status = result["context"]["public_context_status"]
    assert status["status"] == "failed"
    assert "TimeoutError" in status["message"]
    assert result["context"]["core_keywords"][0]["rank_status"] == "not_checked"
    assert "Market context failed" in result["source_status"]["warnings"][0]


def test_market_context_starts_background_fetch_without_blocking(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    app.st.session_state = SessionState()
    data = {
        "asin": "B0TEST0001",
        "pulled_at": "2026-06-14T00:00:00Z",
        "date_window": {"start_date": "2026-06-13", "end_date": "2026-06-13"},
        "context": {"listing": {"title": "Sample milk frother"}},
        "source_status": {"warnings": []},
    }
    targets = {"asin": "B0TEST0001", "marketplace": "US", "core_keywords": ["milk frother"]}
    submitted = []

    class PendingFuture:
        def done(self):
            return False

    monkeypatch.setattr(app, "secrets_get", lambda key, default=None: "token-123" if key == "PANGOLINFO_API_TOKEN" else default)
    monkeypatch.setattr(app, "market_context_from_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "_submit_market_context_job", lambda data, targets, token: submitted.append((data, targets, token)) or PendingFuture())
    monkeypatch.setattr(
        app,
        "enrich_public_context_with_token",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Market context should not load synchronously")),
    )

    result = app.market_context_render_data(data, targets, force_refresh=False)

    assert submitted and submitted[0][2] == "token-123"
    assert result["context"]["public_context_status"]["status"] == "loading"
    assert "background" in result["context"]["public_context_status"]["message"].lower()


def test_market_context_uses_completed_background_result(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    app.st.session_state = SessionState()
    data = {
        "asin": "B0TEST0001",
        "pulled_at": "2026-06-14T00:00:00Z",
        "date_window": {"start_date": "2026-06-13", "end_date": "2026-06-13"},
        "context": {"listing": {"title": "Sample milk frother"}},
        "source_status": {"warnings": []},
    }
    enriched = {
        **data,
        "context": {
            "public_context_status": {
                "status": "ok",
                "message": "Pangolin public context loaded.",
                "source": "pangolin",
                "freshness": "2026-06-14T00:01:00Z",
            }
        },
    }

    class DoneFuture:
        def done(self):
            return True

        def result(self):
            return enriched

    key = app.market_context_request_key(data, {"asin": "B0TEST0001"}, 0)
    app.st.session_state["market_context_future"] = {"key": key, "future": DoneFuture()}
    monkeypatch.setattr(app, "market_context_from_snapshot", lambda *args, **kwargs: None)

    result = app.market_context_render_data(data, {"asin": "B0TEST0001"}, force_refresh=False)

    assert result is enriched
    assert app.st.session_state["market_context_result"]["data"] is enriched


def test_market_context_pending_future_times_out_without_resubmitting(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    app.st.session_state = SessionState()
    data = {
        "asin": "B0TEST0001",
        "pulled_at": "2026-06-14T00:00:00Z",
        "date_window": {"start_date": "2026-06-13", "end_date": "2026-06-13"},
        "context": {"listing": {"title": "Sample milk frother"}},
        "source_status": {"warnings": []},
    }
    targets = {
        "asin": "B0TEST0001",
        "marketplace": "US",
        "core_keywords": ["milk frother"],
        "market_context_background_timeout_seconds": 25,
    }
    submitted = []

    class PendingFuture:
        def done(self):
            return False

    future = PendingFuture()
    key = app.market_context_request_key(data, targets, 0)
    app.st.session_state["market_context_future"] = {"key": key, "future": future, "started_at": 0.0}
    monkeypatch.setattr(app, "market_context_now", lambda: 31.0, raising=False)
    monkeypatch.setattr(app, "market_context_from_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "_submit_market_context_job", lambda *args: submitted.append(args) or future)

    result = app.market_context_render_data(data, targets, force_refresh=False)

    status = result["context"]["public_context_status"]
    assert status["status"] == "partial"
    assert "timed out" in status["message"].lower()
    assert app.st.session_state["market_context_future"]["future"] is future
    assert submitted == []


def test_market_context_completed_future_replaces_timeout_preview(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    app.st.session_state = SessionState()
    data = {
        "asin": "B0TEST0001",
        "pulled_at": "2026-06-14T00:00:00Z",
        "date_window": {"start_date": "2026-06-13", "end_date": "2026-06-13"},
        "context": {"listing": {"title": "Sample milk frother"}},
        "source_status": {"warnings": []},
    }
    targets = {"asin": "B0TEST0001", "marketplace": "US", "core_keywords": ["milk frother"]}
    enriched = {
        **data,
        "context": {
            "public_context_status": {
                "status": "ok",
                "message": "Pangolin public context loaded.",
                "source": "pangolin",
                "freshness": "2026-06-14T00:01:00Z",
            }
        },
    }

    class DoneFuture:
        def done(self):
            return True

        def result(self):
            return enriched

    key = app.market_context_request_key(data, targets, 0)
    app.st.session_state["market_context_future"] = {"key": key, "future": DoneFuture(), "started_at": 0.0}
    app.st.session_state["market_context_result"] = {
        "key": key,
        "data": app._market_context_preview(data, "partial", "Market context timed out.", targets),
        "preview": True,
    }
    monkeypatch.setattr(app, "market_context_from_snapshot", lambda *args, **kwargs: None)

    result = app.market_context_render_data(data, targets, force_refresh=False)

    assert result is enriched
    assert app.st.session_state["market_context_result"]["data"] is enriched
    assert "preview" not in app.st.session_state["market_context_result"]


def test_market_context_reads_remote_snapshot_when_configured(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    app.st.session_state = SessionState()
    data = {"context": {"listing": {"title": "Lingxing"}}, "source_status": {"warnings": []}}
    targets = {
        "market_context_snapshot_url": "https://example.test/latest.json",
        "market_context_snapshot_stale_minutes": 10,
        "market_context_snapshot_expired_minutes": 120,
    }
    snapshot = {
        "schema_version": "1.0",
        "snapshot_status": "complete",
        "captured_at": "2026-06-14T12:00:00Z",
        "source_versions": {"generator": "test"},
        "market_context": {
            "public_listing": {
                "title": "SampleWhisk Milk Frother",
                "price_display": "$39.99",
                "rating": 4.8,
                "review_count": 36,
                "delivery_promise": "Mon, Jun 15",
                "fulfillment_method": "FBA",
                "coupon_present": False,
                "deal_present": False,
            },
            "rank": {"own_bsr_leaf_rank": 53, "own_bsr_leaf_category": "Milk Frothers"},
            "core_keywords": [{"keyword": "milk frother"}, {"keyword": "coffee frother"}, {"keyword": "handheld milk frother"}],
            "market": {"selected_competitors": [{"asin": "B111111111"}]},
            "public_context_status": {"status": "ok", "message": "Complete"},
        },
        "warnings": [],
    }

    monkeypatch.setattr(app, "secrets_get", lambda key, default=None: "unit-test-secret" if key == "MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY" else default)
    monkeypatch.setattr(app, "load_remote_market_context_snapshot", lambda url, encryption_key, timeout=5: snapshot)
    monkeypatch.setattr(app, "_submit_market_context_job", lambda *args: (_ for _ in ()).throw(AssertionError("snapshot mode should not submit live job")))

    result = app.market_context_render_data(data, targets, force_refresh=False)

    assert result["context"]["public_listing"]["title"] == "SampleWhisk Milk Frother"
    assert result["context"]["rank"]["own_bsr_leaf_rank"] == 53
    assert result["context"]["public_context_status"]["source"] == "market_context_snapshot"


def test_market_context_snapshot_effective_url_adds_time_bucket(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    monkeypatch.setattr(app.time, "time", lambda: 125.0)

    url = app.market_context_snapshot_effective_url(
        "https://example.test/latest.enc.json",
        {"market_context_snapshot_cache_bust_seconds": 60},
        force_refresh=False,
    )

    assert url == "https://example.test/latest.enc.json?_snapshot_bucket=2"


def test_market_context_snapshot_effective_url_preserves_existing_query(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    monkeypatch.setattr(app.time, "time", lambda: 125.0)

    url = app.market_context_snapshot_effective_url(
        "https://example.test/latest.enc.json?raw=1",
        {"market_context_snapshot_cache_bust_seconds": 60},
        force_refresh=False,
    )

    assert url == "https://example.test/latest.enc.json?raw=1&_snapshot_bucket=2"


def test_market_context_snapshot_force_refresh_adds_nonce_and_clears_hot_cache(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    app.st.session_state = SessionState()
    app.st.session_state["market_context_snapshot_hot_cache"] = {"url": "https://example.test/latest.json", "data": {}}
    data = {"context": {}, "source_status": {"warnings": []}}
    targets = {"market_context_snapshot_url": "https://example.test/latest.json"}
    called_urls = []
    clear_calls = []

    monkeypatch.setattr(app, "secrets_get", lambda key, default=None: "unit-test-secret" if key == "MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY" else default)
    monkeypatch.setattr(app, "clear_remote_market_context_snapshot_cache", lambda: clear_calls.append("cleared"))

    def capture_url(url, encryption_key, timeout=5):
        called_urls.append(url)
        raise TimeoutError("remote timeout")

    monkeypatch.setattr(app, "load_remote_market_context_snapshot", capture_url)

    result = app.market_context_from_snapshot(data, targets, force_refresh=True)

    assert clear_calls == ["cleared"]
    assert "market_context_snapshot_hot_cache" not in app.st.session_state
    assert called_urls and "_snapshot_nonce=" in called_urls[0]
    assert result["context"]["public_context_status"]["status"] == "failed"


def test_market_context_uses_hot_cache_when_remote_snapshot_fails(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    app.st.session_state = SessionState()
    data = {"context": {}, "source_status": {"warnings": []}}
    targets = {"market_context_snapshot_url": "https://example.test/latest.json"}
    cached = {
        "context": {
            "public_context_status": {"status": "fresh", "message": "cached"},
            "rank": {"own_bsr_leaf_rank": 53},
        },
        "source_status": {"warnings": []},
    }
    app.st.session_state["market_context_snapshot_hot_cache"] = {
        "url": "https://example.test/latest.json",
        "data": cached,
    }
    monkeypatch.setattr(app, "secrets_get", lambda key, default=None: "unit-test-secret" if key == "MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY" else default)

    def fail(*args, **kwargs):
        raise TimeoutError("remote timeout")

    monkeypatch.setattr(app, "load_remote_market_context_snapshot", fail)

    result = app.market_context_render_data(data, targets, force_refresh=False)

    assert result["context"]["rank"]["own_bsr_leaf_rank"] == 53
    assert result["context"]["public_context_status"]["status"] == "stale"
    assert "remote timeout" in result["context"]["public_context_status"]["message"]
    assert "fallback" in result["context"]["public_context_status"]["message"].lower()


def test_market_context_uses_hot_cache_by_base_url_when_effective_url_changes(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)
    app.st.session_state = SessionState()
    base_url = "https://example.test/latest.json"
    data = {"context": {}, "source_status": {"warnings": []}}
    targets = {"market_context_snapshot_url": base_url, "market_context_snapshot_cache_bust_seconds": 60}
    cached = {
        "context": {
            "public_context_status": {"status": "fresh", "message": "cached"},
            "rank": {"own_bsr_leaf_rank": 53},
        },
        "source_status": {"warnings": []},
    }
    app.st.session_state["market_context_snapshot_hot_cache"] = {"url": base_url, "data": cached}
    monkeypatch.setattr(app, "secrets_get", lambda key, default=None: "unit-test-secret" if key == "MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY" else default)
    monkeypatch.setattr(app.time, "time", lambda: 125.0)
    monkeypatch.setattr(app, "load_remote_market_context_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("remote timeout")))

    result = app.market_context_from_snapshot(data, targets, force_refresh=False)

    assert result["context"]["rank"]["own_bsr_leaf_rank"] == 53
    assert result["context"]["public_context_status"]["status"] == "stale"


def test_market_context_banner_level_handles_snapshot_freshness(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)

    assert app.market_context_banner_level("fresh") == "success"
    assert app.market_context_banner_level("stale") == "warning"
    assert app.market_context_banner_level("expired") == "error"


def test_offer_value_formatting_uses_yes_no_and_none(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)

    assert app.offer_value(True) == "Yes"
    assert app.offer_value(False) == "No"
    assert app.offer_value(None) == "None"
    assert app.offer_value("") == "None"


def test_source_health_label_marks_partial_live_data(monkeypatch):
    app = import_app_with_fake_streamlit(monkeypatch)

    assert app.source_health_label({"mode": "live_api", "missing_fields": [], "warnings": []}) == "Healthy"
    assert app.source_health_label({"mode": "live_api", "missing_fields": ["advertising.campaigns"], "warnings": []}) == "Partial"
    assert app.source_health_label({"mode": "live_api", "missing_fields": [], "warnings": ["campaigns failed"]}) == "Degraded"
    assert app.source_health_label({"mode": "fixture_no_live_url", "missing_fields": [], "warnings": []}) == "Sample data"
