from src.public_context import build_public_context, normalize_public_listing


class FakePangolinClient:
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
                "bestSellersRank": "#12 in Milk Frothers",
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
        return [
            {"asin": "B111111111", "title": "Competing Milk Frother", "price": "$29.99", "star": "4.6", "rating": "1,200", "sponsored": True},
            {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36"},
        ]

    def product_of_category(self, *, category_id, site, zipcode):
        return [
            {"asin": "B222222222", "title": "Category Milk Frother", "price": "$24.99", "star": "4.5", "rating": "980 ratings"},
            {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36 ratings"},
        ]

    def best_sellers(self, *, category_keyword, site, zipcode):
        return [
            {"asin": "B333333333", "title": "Best Seller Milk Frother", "price": "$19.99", "star": "4.4", "rating": "3,100 ratings"},
            {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36 ratings"},
        ]

    def new_releases(self, *, category_keyword, site, zipcode):
        return [
            {"asin": "B444444444", "title": "New Release Frother", "price": "$34.99", "star": "4.7", "rating": "120 ratings"},
            {"asin": "B0GXYYZPBW", "title": "InstaWhisk Upgraded Milk Frother", "price": "$39.99", "star": "4.8", "rating": "36 ratings"},
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
    context = build_public_context(
        asin="B0GXYYZPBW",
        marketplace="US",
        zipcode="10041",
        core_keywords=["milk frother", "coffee frother"],
        pinned_competitor_asins=["B111111111"],
        excluded_competitor_asins=[],
        client=FakePangolinClient(),
        max_competitors=5,
    )

    assert context["public_listing"]["asin"] == "B0GXYYZPBW"
    assert context["public_listing"]["discount_present"] is True
    assert context["public_listing"]["deal_present"] is False
    assert [row["keyword"] for row in context["core_keywords"]] == ["milk frother", "coffee frother"]
    assert context["rank"]["core_keyword_ranks"][0]["own_organic_rank"] == 1
    assert context["rank"]["bsr_capture_status"] == "measured"
    assert context["rank"]["own_bsr_rank"] == 2
    assert context["rank"]["own_new_release_rank"] == 2
    assert context["rank"]["own_category_list_rank"] == 2
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
