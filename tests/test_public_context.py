from src.public_context import build_public_context, normalize_public_listing


class FakePangolinClient:
    def __init__(self):
        self.best_seller_queries = []
        self.new_release_queries = []
        self.keyword_queries = []
        self.product_category_queries = []

    def product_detail(self, *, asin, site, zipcode):
        products = {
            "B0GXYYZPBW": {
                "asin": "B0GXYYZPBW",
                "title": "InstaWhisk Upgraded Milk Frother",
                "price": "$39.99",
                "strikethroughPrice": "$49.99",
                "coupon": "",
                "badge": "",
                "star": "4.8",
                "rating": "36 ratings",
                "category_id": "123",
                "category_name": "Milk Frothers",
                "bestSellersRankItems": [
                    {"rank": "#8", "category": "Kitchen & Dining"},
                    {"rank": "#2", "category": "Milk Frothers"},
                ],
                "image": "https://example.test/frother.jpg",
                "features": ["Rechargeable", "Variable speed", "Detachable whisk"],
                "deliveryTime": {"deliveryTime": "Mon, Jun 15", "fastestDelivery": "Sat, Jun 13"},
            },
            "B111111111": {
                "asin": "B111111111",
                "title": "Competing Milk Frother",
                "price": "$29.99",
                "badge": "Limited time deal",
                "star": "4.6",
                "rating": "1,200 ratings",
            },
        }
        return products.get(asin, {"asin": asin})

    def keyword_search(self, *, keyword, site, zipcode):
        self.keyword_queries.append(keyword)
        return [
            {"asin": "B111111111", "title": "Competing Milk Frother", "price": "$29.99", "star": "4.6", "rating": "1,200", "sponsored": True},
            {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36"},
        ]

    def product_of_category(self, *, category_id, site, zipcode):
        self.product_category_queries.append(category_id)
        return [
            {"asin": "B222222222", "title": "Category Milk Frother", "price": "$24.99", "star": "4.5", "rating": "980 ratings"},
            {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36 ratings"},
        ]

    def best_sellers(self, *, category_keyword, site, zipcode, category_node_id=None, category_url=None):
        self.best_seller_queries.append(
            {"keyword": category_keyword, "node_id": category_node_id, "url": category_url}
        )
        if category_node_id == "14042381":
            return [
                {"asin": "B333333333", "title": "Best Seller Milk Frother", "rank": "#1"},
                {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "rank": "#53"},
            ]
        if category_keyword == "Kitchen & Dining":
            return [
                {"asin": "B333333333", "title": "Kitchen Best Seller", "price": "$19.99", "star": "4.4", "rating": "3,100 ratings"},
                {"asin": "B555555555", "title": "Kitchen Competitor", "price": "$22.99", "star": "4.5", "rating": "1,900 ratings"},
                {"asin": "B666666666", "title": "Kitchen Competitor 2", "price": "$25.99", "star": "4.3", "rating": "980 ratings"},
                {"asin": "B777777777", "title": "Kitchen Competitor 3", "price": "$28.99", "star": "4.2", "rating": "510 ratings"},
                {"asin": "B888888888", "title": "Kitchen Competitor 4", "price": "$29.99", "star": "4.1", "rating": "430 ratings"},
                {"asin": "B999999999", "title": "Kitchen Competitor 5", "price": "$31.99", "star": "4.0", "rating": "320 ratings"},
                {"asin": "BAAAAAAAAA", "title": "Kitchen Competitor 6", "price": "$32.99", "star": "3.9", "rating": "210 ratings"},
                {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36 ratings"},
            ]
        return [
            {"asin": "B333333333", "title": "Best Seller Milk Frother", "price": "$19.99", "star": "4.4", "rating": "3,100 ratings"},
            {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36 ratings"},
        ]

    def new_releases(self, *, category_keyword, site, zipcode, category_node_id=None, category_url=None):
        self.new_release_queries.append(
            {"keyword": category_keyword, "node_id": category_node_id, "url": category_url}
        )
        if category_node_id == "14042381":
            return [
                {"asin": "B444444444", "title": "New Release Frother", "rank": "#1"},
                {"asin": "CCCCCCCCCC", "title": "New Release Frother 2", "rank": "#2"},
            ]
        if category_keyword == "Kitchen & Dining":
            return [
                {"asin": "B444444444", "title": "Kitchen New Release", "price": "$34.99", "star": "4.7", "rating": "120 ratings"},
                {"asin": "BBBBBBBBBB", "title": "Kitchen New Release 2", "price": "$36.99", "star": "4.6", "rating": "98 ratings"},
                {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36 ratings"},
            ]
        return [
            {"asin": "B444444444", "title": "New Release Frother", "price": "$34.99", "star": "4.7", "rating": "120 ratings"},
            {"asin": "CCCCCCCCCC", "title": "New Release Frother 2", "price": "$35.99", "star": "4.5", "rating": "88 ratings"},
            {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36 ratings"},
        ]


class TimeoutKeywordPangolinClient(FakePangolinClient):
    def keyword_search(self, *, keyword, site, zipcode):
        self.keyword_queries.append(keyword)
        if keyword == "coffee frother":
            raise TimeoutError("keyword search timed out")
        return [
            {"asin": "B111111111", "title": "Competing Milk Frother", "price": "$29.99", "star": "4.6", "rating": "1,200", "sponsored": True},
            {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36"},
        ]


class ListingBsrFallbackPangolinClient(FakePangolinClient):
    def product_detail(self, *, asin, site, zipcode):
        product = super().product_detail(asin=asin, site=site, zipcode=zipcode)
        product["category_id"] = ""
        product["bestSellersRankItems"] = [
            {"rank": "#53", "category": "Milk Frothers"},
        ]
        return product

    def best_sellers(self, *, category_keyword, site, zipcode, category_node_id=None, category_url=None):
        self.best_seller_queries.append(
            {"keyword": category_keyword, "node_id": category_node_id, "url": category_url}
        )
        return [
            {"asin": "B333333333", "title": "Best Seller Milk Frother", "rank": "#1"},
            {"asin": "B222222222", "title": "Another Milk Frother", "rank": "#2"},
        ]


class DirectUrlFallbackPangolinClient(FakePangolinClient):
    def product_detail(self, *, asin, site, zipcode):
        product = super().product_detail(asin=asin, site=site, zipcode=zipcode)
        product["category_id"] = ""
        product["category_name"] = "Milk Frothers"
        product["bestSellersRankItems"] = []
        product["bestSellersRank"] = ""
        return product

    def product_of_category(self, *, category_id, site, zipcode):
        self.product_category_queries.append(category_id)
        return []

    def best_sellers(self, *, category_keyword, site, zipcode, category_node_id=None, category_url=None):
        self.best_seller_queries.append(
            {"keyword": category_keyword, "node_id": category_node_id, "url": category_url}
        )
        return [
            {"asin": "B333333333", "title": "Best Seller Milk Frother", "rank": "#1"},
        ]


def test_normalize_public_listing_splits_discount_and_deal():
    listing = normalize_public_listing(
        {
            "asin": "B0GXYYZPBW",
            "price": "$39.99",
            "strikethroughPrice": "$49.99",
            "coupon": "",
            "badge": "",
        },
        source="pangolin:amzProductDetail",
        zipcode="10041",
    )

    assert listing["discount_present"] is True
    assert listing["deal_present"] is False


def test_normalize_public_listing_reads_delivery_promise_aliases():
    listing = normalize_public_listing(
        {
            "asin": "B0GXYYZPBW",
            "deliveryPromise": {"deliveryTime": "Mon, Jun 15", "fastestDelivery": "Sat, Jun 13"},
        },
        source="pangolin:amzProductDetail",
        zipcode="10041",
    )

    assert listing["delivery_promise"] == "Mon, Jun 15; fastest Sat, Jun 13"


def test_build_public_context_selects_keywords_and_competitors():
    client = FakePangolinClient()
    context = build_public_context(
        asin="B0GXYYZPBW",
        marketplace="US",
        zipcode="10041",
        core_keywords=["milk frother", "coffee frother"],
        pinned_competitor_asins=["B111111111"],
        excluded_competitor_asins=[],
        client=client,
        max_competitors=5,
    )

    assert context["public_listing"]["asin"] == "B0GXYYZPBW"
    assert context["public_listing"]["discount_present"] is True
    assert context["public_listing"]["deal_present"] is False
    assert [row["keyword"] for row in context["core_keywords"]] == ["milk frother", "coffee frother"]
    assert context["rank"]["core_keyword_ranks"][0]["own_organic_rank"] == 1
    assert context["rank"]["bsr_capture_status"] == "measured"
    assert [row["keyword"] for row in client.best_seller_queries] == ["Kitchen & Dining", "Milk Frothers"]
    assert [row["keyword"] for row in client.new_release_queries] == ["Kitchen & Dining", "Milk Frothers"]
    assert context["rank"]["own_bsr_major_rank"] == 8
    assert context["rank"]["own_bsr_major_category"] == "Kitchen & Dining"
    assert context["rank"]["own_bsr_leaf_rank"] == 2
    assert context["rank"]["own_bsr_leaf_category"] == "Milk Frothers"
    assert context["rank"]["own_new_release_major_rank"] == 3
    assert context["rank"]["own_new_release_major_category"] == "Kitchen & Dining"
    assert context["rank"]["own_new_release_leaf_rank"] == 3
    assert context["rank"]["own_new_release_leaf_category"] == "Milk Frothers"
    assert context["rank"]["own_bsr_rank"] == context["rank"]["own_bsr_leaf_rank"]
    assert context["rank"]["own_new_release_rank"] == context["rank"]["own_new_release_leaf_rank"]
    assert context["rank"]["own_category_list_rank"] == 2
    assert {row["rank_level"] for row in context["market"]["category_candidates"]} >= {"major", "leaf"}
    assert context["market"]["selected_competitors"][0]["asin"] == "B111111111"
    assert "operator_pinned" in context["market"]["selected_competitors"][0]["why_selected"]
    competitor_asins = {row["asin"] for row in context["market"]["selected_competitors"]}
    assert "B0GXYYZPBW" not in competitor_asins
    assert "B333333333" in competitor_asins
    assert "B444444444" in competitor_asins
    category_competitor = next(row for row in context["market"]["selected_competitors"] if row["asin"] == "B333333333")
    assert category_competitor["rank_relationship"]["best_bsr_rank"] == 1
    new_release_competitor = next(row for row in context["market"]["selected_competitors"] if row["asin"] == "B444444444")
    assert category_competitor["rank_relationship"]["category_rank_source"] == "pangolin:amzBestSellers"
    assert new_release_competitor["rank_relationship"]["category_rank_source"] == "pangolin:amzNewReleases"


def test_build_public_context_limits_keywords_and_keeps_partial_timeout_data():
    client = TimeoutKeywordPangolinClient()
    context = build_public_context(
        asin="B0GXYYZPBW",
        marketplace="US",
        zipcode="10041",
        core_keywords=["milk frother", "coffee frother", "matcha whisk", "protein mixer"],
        pinned_competitor_asins=[],
        excluded_competitor_asins=[],
        client=client,
        max_competitors=5,
        max_keywords=3,
        category_rankings_enabled=False,
    )

    assert client.keyword_queries == ["milk frother", "coffee frother", "matcha whisk"]
    assert context["public_listing"]["asin"] == "B0GXYYZPBW"
    assert [row["keyword"] for row in context["core_keywords"]] == ["milk frother", "coffee frother", "matcha whisk"]
    failed_keyword = context["core_keywords"][1]
    assert failed_keyword["rank_status"] == "failed"
    assert failed_keyword["missing_fields"] == ["pangolin_keyword_search"]
    assert context["public_context_status"]["status"] == "partial"
    assert "coffee frother" in context["public_context_status"]["message"]
    assert context["rank"]["core_keyword_ranks"][0]["rank_status"] == "measured"


def test_build_public_context_uses_configured_leaf_node_for_bsr_and_new_releases():
    client = FakePangolinClient()
    context = build_public_context(
        asin="B0GXYYZPBW",
        marketplace="US",
        zipcode="10041",
        core_keywords=["milk frother"],
        pinned_competitor_asins=[],
        excluded_competitor_asins=[],
        client=client,
        max_competitors=5,
        max_keywords=1,
        leaf_category_label="Milk Frothers",
        leaf_category_node_id="14042381",
        best_sellers_url="https://www.amazon.com/gp/bestsellers/home-garden/14042381/ref=pd_zg_hrsr_home-garden",
        new_releases_url="https://www.amazon.com/gp/new-releases/home-garden/14042381",
    )

    assert client.product_category_queries[-1] == "14042381"
    assert client.best_seller_queries[-1] == {
        "keyword": "Milk Frothers",
        "node_id": "14042381",
        "url": "https://www.amazon.com/gp/bestsellers/home-garden/14042381/ref=pd_zg_hrsr_home-garden",
    }
    assert client.new_release_queries[-1] == {
        "keyword": "Milk Frothers",
        "node_id": "14042381",
        "url": "https://www.amazon.com/gp/new-releases/home-garden/14042381",
    }
    assert context["rank"]["own_bsr_leaf_rank"] == 53
    assert context["rank"]["own_bsr_leaf_category"] == "Milk Frothers"
    assert context["rank"]["own_bsr_leaf_source"] == "pangolin:amzBestSellers"
    leaf_new_release_attempt = next(
        row
        for row in context["rank"]["bsr_capture_attempts"]
        if row["source"] == "pangolin:amzNewReleases" and row["category_node_id"] == "14042381"
    )
    assert leaf_new_release_attempt["bsr_capture_status"] == "not_in_leaf_new_release_window"


def test_build_public_context_uses_product_detail_bsr_when_leaf_list_misses_own_asin():
    client = ListingBsrFallbackPangolinClient()
    context = build_public_context(
        asin="B0GXYYZPBW",
        marketplace="US",
        zipcode="10041",
        core_keywords=["milk frother"],
        pinned_competitor_asins=[],
        excluded_competitor_asins=[],
        client=client,
        max_competitors=5,
        max_keywords=1,
        leaf_category_label="Milk Frothers",
        leaf_category_node_id="14042381",
        best_sellers_url="https://www.amazon.com/gp/bestsellers/home-garden/14042381/ref=pd_zg_hrsr_home-garden",
    )

    assert context["rank"]["own_bsr_leaf_rank"] == 53
    assert context["rank"]["own_bsr_leaf_category"] == "Milk Frothers"
    assert context["rank"]["own_bsr_leaf_source"] == "pangolin:amzProductDetail"
    assert any(
        row["source"] == "pangolin:amzProductDetail" and row["bsr_capture_status"] == "measured"
        for row in context["rank"]["bsr_capture_attempts"]
    )


def test_build_public_context_uses_direct_url_fallback_when_pangolin_leaf_list_misses():
    client = DirectUrlFallbackPangolinClient()

    def fake_fetcher(url, *, asin, category_label, source, timeout):
        assert asin == "B0GXYYZPBW"
        assert category_label == "Milk Frothers"
        assert source == "amazon:directBestSellersUrl"
        assert "14042381" in url
        return [
            {"asin": "B333333333", "rank": 52, "title": "Other Frother"},
            {"asin": "B0GXYYZPBW", "rank": 53, "title": "InstaWhisk Upgraded Milk Frother"},
        ]

    context = build_public_context(
        asin="B0GXYYZPBW",
        marketplace="US",
        zipcode="10041",
        core_keywords=["milk frother"],
        pinned_competitor_asins=[],
        excluded_competitor_asins=[],
        client=client,
        max_competitors=5,
        max_keywords=1,
        leaf_category_label="Milk Frothers",
        leaf_category_node_id="14042381",
        best_sellers_url="https://www.amazon.com/gp/bestsellers/home-garden/14042381/ref=pd_zg_hrsr_home-garden",
        direct_url_fetcher=fake_fetcher,
    )

    assert context["rank"]["own_bsr_leaf_rank"] == 53
    assert context["rank"]["own_bsr_leaf_source"] == "amazon:directBestSellersUrl"
    assert any(
        row["source"] == "amazon:directBestSellersUrl" and row["bsr_capture_status"] == "measured"
        for row in context["rank"]["bsr_capture_attempts"]
    )
