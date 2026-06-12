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
        return []

    def best_sellers(self, *, category_keyword, site, zipcode):
        return []

    def new_releases(self, *, category_keyword, site, zipcode):
        return []


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
    assert context["market"]["selected_competitors"][0]["asin"] == "B111111111"
    assert "operator_pinned" in context["market"]["selected_competitors"][0]["why_selected"]
