"""API surface: auth, tracking, filtering, history, notifications."""

from __future__ import annotations

from fastapi.testclient import TestClient

TRACK_PAYLOAD = {
    "url": "https://www.zara.com/in/en/leather-effect-jacket-p07840321.html",
    "name": "Leather Effect Jacket",
    "store": "Zara",
    "store_slug": "zara",
    "brand": "Zara",
    "currency": "INR",
    "current_price": "12990.00",
    "original_price": "15990.00",
    "availability": "in_stock",
    "variants": [
        {"id": "S", "name": "S", "type": "size", "availability": "in_stock"},
        {"id": "M", "name": "M", "type": "size", "availability": "out_of_stock"},
        {"id": "L", "name": "L", "type": "size", "availability": "out_of_stock"},
    ],
    "watched_variant_ids": ["M", "L"],
    "target_price": "10000.00",
}


# ------------------------------------------------------------------ auth ----


def test_register_login_and_me(client: TestClient):
    register = client.post(
        "/api/auth/register", json={"email": "New@Example.com", "password": "correct-horse-9"}
    )
    assert register.status_code == 201
    assert register.json()["token_type"] == "bearer"

    # Email is normalised, so the same address in different case is one account.
    duplicate = client.post(
        "/api/auth/register", json={"email": "new@example.com", "password": "correct-horse-9"}
    )
    assert duplicate.status_code == 409

    login = client.post("/api/auth/login", json={"email": "new@example.com", "password": "correct-horse-9"})
    assert login.status_code == 200

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"


def test_weak_passwords_are_rejected(client: TestClient):
    assert client.post("/api/auth/register", json={"email": "a@b.com", "password": "short"}).status_code == 422
    assert (
        client.post("/api/auth/register", json={"email": "a@b.com", "password": "allletters"}).status_code == 422
    )


def test_wrong_password_is_indistinguishable_from_unknown_account(client: TestClient):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "correct-horse-9"})

    wrong = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong-horse-9"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@b.com", "password": "correct-horse-9"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_protected_routes_require_a_token(client: TestClient):
    assert client.get("/api/products").status_code == 401
    assert client.get("/api/products", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_a_refresh_token_is_not_an_access_token(client: TestClient):
    tokens = client.post(
        "/api/auth/register", json={"email": "a@b.com", "password": "correct-horse-9"}
    ).json()

    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    ).status_code == 401

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    ).status_code == 200


# -------------------------------------------------------------- tracking ----


def test_track_a_product(client: TestClient, auth_headers: dict[str, str]):
    response = client.post("/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["name"] == "Leather Effect Jacket"
    assert body["store"] == "Zara"
    assert body["discount_percentage"] == 19
    assert len(body["variants"]) == 3

    watched = {variant["variant_id"] for variant in body["variants"] if variant["is_watched"]}
    assert watched == {"M", "L"}


def test_tracking_the_same_url_twice_updates_rather_than_duplicates(
    client: TestClient, auth_headers: dict[str, str]
):
    first = client.post("/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers).json()

    again = {**TRACK_PAYLOAD, "current_price": "11990.00"}
    second = client.post("/api/products/track", json=again, headers=auth_headers).json()

    assert first["id"] == second["id"]
    assert client.get("/api/products", headers=auth_headers).json()["total"] == 1

    history = client.get(f"/api/products/{first['id']}/price-history", headers=auth_headers).json()
    assert len(history["points"]) == 2  # continuous, not restarted


def test_tracking_urls_are_cleaned(client: TestClient, auth_headers: dict[str, str]):
    payload = {**TRACK_PAYLOAD, "url": TRACK_PAYLOAD["url"] + "?utm_source=email&utm_campaign=x"}
    body = client.post("/api/products/track", json=payload, headers=auth_headers).json()
    assert "utm_source" not in body["url"]


def test_list_filter_and_sort(client: TestClient, auth_headers: dict[str, str]):
    # Watches S, which is available, so this one is in stock *for this user*.
    client.post(
        "/api/products/track",
        json={**TRACK_PAYLOAD, "watched_variant_ids": ["S"]},
        headers=auth_headers,
    )
    client.post(
        "/api/products/track",
        json={
            **TRACK_PAYLOAD,
            "url": "https://www.myntra.com/jeans/roadster/x/2296012/buy",
            "name": "Roadster Jeans",
            "store": "Myntra",
            "store_slug": "myntra",
            "current_price": "1149.00",
            "original_price": "2299.00",
            "availability": "out_of_stock",
            "variants": [],
            "watched_variant_ids": [],
        },
        headers=auth_headers,
    )

    assert client.get("/api/products", headers=auth_headers).json()["total"] == 2
    # The stock filters agree with the labels the cards show, because both read
    # the watched value rather than the retailer's.
    assert client.get("/api/products?status=in_stock", headers=auth_headers).json()["total"] == 1
    assert client.get("/api/products?status=out_of_stock", headers=auth_headers).json()["total"] == 1
    assert client.get("/api/products?store=myntra", headers=auth_headers).json()["total"] == 1
    assert client.get("/api/products?search=roadster", headers=auth_headers).json()["total"] == 1

    by_drop = client.get("/api/products?sort=price_drop", headers=auth_headers).json()
    assert by_drop["items"][0]["name"] == "Leather Effect Jacket"  # 3,000 off beats 1,150


def test_pause_resume_and_delete(client: TestClient, auth_headers: dict[str, str]):
    product_id = client.post("/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers).json()["id"]

    assert client.post(f"/api/products/{product_id}/pause", headers=auth_headers).json()["tracking_enabled"] is False
    assert client.post(f"/api/products/{product_id}/resume", headers=auth_headers).json()["tracking_enabled"] is True

    patched = client.patch(
        f"/api/products/{product_id}",
        json={"target_price": "9000.00", "watched_variant_ids": ["S"]},
        headers=auth_headers,
    ).json()
    assert patched["target_price"] == "9000.00"

    detail = client.get(f"/api/products/{product_id}", headers=auth_headers).json()
    assert {v["variant_id"] for v in detail["variants"] if v["is_watched"]} == {"S"}

    assert client.delete(f"/api/products/{product_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/products/{product_id}", headers=auth_headers).status_code == 404


def test_one_user_cannot_see_anothers_products(client: TestClient, auth_headers: dict[str, str]):
    product_id = client.post("/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers).json()["id"]

    other = client.post(
        "/api/auth/register", json={"email": "other@example.com", "password": "correct-horse-9"}
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    assert client.get(f"/api/products/{product_id}", headers=other_headers).status_code == 404
    assert client.delete(f"/api/products/{product_id}", headers=other_headers).status_code == 404
    assert client.get("/api/products", headers=other_headers).json()["total"] == 0


def test_price_history_and_stats(client: TestClient, auth_headers: dict[str, str]):
    product_id = client.post("/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers).json()["id"]
    client.post("/api/products/track", json={**TRACK_PAYLOAD, "current_price": "10990.00"}, headers=auth_headers)

    history = client.get(f"/api/products/{product_id}/price-history?range=30d", headers=auth_headers).json()
    assert len(history["points"]) == 2
    assert history["stats"]["lowest"] == "10990.00"
    assert history["stats"]["highest"] == "12990.00"
    assert history["stats"]["is_at_lowest"] is True

    detail = client.get(f"/api/products/{product_id}", headers=auth_headers).json()
    assert detail["price_stats"]["current"] == "10990.00"


def test_overview(client: TestClient, auth_headers: dict[str, str]):
    client.post("/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers)

    overview = client.get("/api/products/overview", headers=auth_headers).json()
    assert overview["tracked_total"] == 1
    # The payload watches M and L, both sold out, while S is available. The
    # counts answer "can I buy what I am watching", so this is not in stock.
    assert overview["in_stock"] == 0
    assert overview["out_of_stock"] == 1
    assert overview["total_saved"] == "3000.00"
    assert overview["currency"] == "INR"


def test_overview_counts_a_watched_size_that_is_available(client: TestClient, auth_headers: dict[str, str]):
    client.post(
        "/api/products/track",
        json={**TRACK_PAYLOAD, "watched_variant_ids": ["S"]},
        headers=auth_headers,
    )

    overview = client.get("/api/products/overview", headers=auth_headers).json()
    assert overview["in_stock"] == 1
    assert overview["out_of_stock"] == 0


# --------------------------------------------------------- notifications ----


def test_notifications_lifecycle(client: TestClient, auth_headers: dict[str, str]):
    client.post("/api/products/track", json=TRACK_PAYLOAD, headers=auth_headers)

    created = client.post("/api/notifications/test", json={"send_email": False}, headers=auth_headers)
    assert created.status_code == 201
    assert created.json()["product_name"] == "Leather Effect Jacket"

    listing = client.get("/api/notifications", headers=auth_headers).json()
    assert listing["total"] == 1

    # Test alerts are excluded from the browser delivery queue on purpose.
    assert client.get("/api/notifications/undelivered", headers=auth_headers).json()["items"] == []

    assert client.post("/api/notifications/read", json={}, headers=auth_headers).status_code == 200
    assert client.get("/api/notifications?unread_only=true", headers=auth_headers).json()["total"] == 0


def test_test_notification_needs_a_product(client: TestClient, auth_headers: dict[str, str]):
    assert client.post("/api/notifications/test", json={}, headers=auth_headers).status_code == 400


def test_health(client: TestClient):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/health/ready").json()["database"] == "ok"
