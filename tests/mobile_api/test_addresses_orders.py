"""Adresses (UUID) et création de commandes : contrat exact du mobile."""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from restaurants.meal.enum import PaymentStatus
from restaurants.meal.models import Accompaniment
from restaurants.meal.models import Boisson
from restaurants.meal.models import Category
from restaurants.meal.models import Meal
from restaurants.meal.models import Order
from restaurants.meal.models import Payment
from restaurants.users.models import Address

ADDRESSES_URL = "/api/v1/addresses/"
ORDERS_URL = "/api/v1/orders/"
CREATE_ORDER_URL = "/api/v1/orders/create_order/"
CART_URL = "/api/v1/cart/add/"

ADDRESS_PAYLOAD = {
    "street": "Rue des Palmiers",
    "city": "Bafoussam",
    "description": "Près de la pharmacie",
    "is_default": True,
}


@pytest.fixture
def category(db):
    return Category.objects.create(name="Plats")


@pytest.fixture
def accompaniment(db):
    return Accompaniment.objects.create(name="Plantain", price=Decimal("500"))


@pytest.fixture
def boisson(db):
    return Boisson.objects.create(name="Jus d'orange", price=Decimal("700"))


@pytest.fixture
def meal(db, category, accompaniment):
    meal = Meal.objects.create(
        name="Poulet DG",
        category=category,
        price=Decimal("2500"),
    )
    meal.accompaniments.add(accompaniment)
    return meal


@pytest.fixture
def address(db, client_user):
    return Address.objects.create(
        client=client_user.client_profile,
        city="Bafoussam",
        street="Centre-ville",
    )


def order_payload(meal, accompaniment, boisson, address, **overrides):
    payload = {
        "delivery_address_id": str(address.id),
        "payment_method": "cash",
        "items": [
            {
                "meal_id": str(meal.id),
                "quantity": 2,
                "accompaniments": [str(accompaniment.id)],
                "boissons": [{"id": str(boisson.id), "quantity": 1}],
            },
        ],
    }
    payload.update(overrides)
    return payload


# ── Adresses ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_address_crud_and_default_flag(auth_client, client_user):
    created = auth_client.post(ADDRESSES_URL, ADDRESS_PAYLOAD, format="json")
    assert created.status_code == 201
    address_id = created.data["id"]
    assert created.data["is_default"] is True

    listed = auth_client.get(ADDRESSES_URL)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.data] == [address_id]

    detail = auth_client.get(f"{ADDRESSES_URL}{address_id}/")
    assert detail.status_code == 200
    assert detail.data["city"] == "Bafoussam"

    updated = auth_client.patch(
        f"{ADDRESSES_URL}{address_id}/",
        {"city": "Douala"},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.data["city"] == "Douala"

    second = auth_client.post(
        ADDRESSES_URL,
        {**ADDRESS_PAYLOAD, "street": "Quartier Akwa", "is_default": False},
        format="json",
    )
    assert second.status_code == 201

    set_default = auth_client.post(f"{ADDRESSES_URL}{second.data['id']}/set_default/")
    assert set_default.status_code == 200
    assert set_default.data["is_default"] is True

    # La suppression est logique : l'adresse disparaît de l'API.
    deleted = auth_client.delete(f"{ADDRESSES_URL}{address_id}/")
    assert deleted.status_code == 204
    assert address_id not in [
        item["id"] for item in auth_client.get(ADDRESSES_URL).data
    ]


@pytest.mark.django_db
def test_addresses_are_private_to_each_client(auth_client, other_user, db):
    foreign = Address.objects.create(
        client=other_user.client_profile,
        city="Yaoundé",
        street="Bastos",
    )

    assert auth_client.get(f"{ADDRESSES_URL}{foreign.id}/").status_code == 404
    assert (
        auth_client.patch(
            f"{ADDRESSES_URL}{foreign.id}/",
            {"city": "Limbe"},
            format="json",
        ).status_code
        == 404
    )
    assert auth_client.delete(f"{ADDRESSES_URL}{foreign.id}/").status_code == 404


@pytest.mark.django_db
def test_address_detail_with_a_malformed_uuid_is_not_a_500(auth_client):
    assert auth_client.get(f"{ADDRESSES_URL}pas-un-uuid/").status_code == 404
    assert auth_client.delete(f"{ADDRESSES_URL}pas-un-uuid/").status_code == 404


@pytest.mark.django_db
def test_addresses_require_authentication(anonymous_client):
    assert anonymous_client.get(ADDRESSES_URL).status_code == 401
    assert (
        anonymous_client.post(ADDRESSES_URL, ADDRESS_PAYLOAD, format="json").status_code
        == 401
    )


# ── Commandes ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_create_order_is_priced_on_the_server(
    auth_client,
    client_user,
    meal,
    accompaniment,
    boisson,
    address,
):
    response = auth_client.post(
        CREATE_ORDER_URL,
        order_payload(meal, accompaniment, boisson, address),
        format="json",
    )

    assert response.status_code == 201
    # (2500 + 500 + 700) x 2 = 7400, + livraison 1000.
    assert Decimal(response.data["total_amount"]) == Decimal("8400")
    assert response.data["status"] == "pending"
    assert response.data["payment_method"] == "cash"
    assert response.data["delivery_address"]["id"] == str(address.id)

    item = response.data["items"][0]
    assert item["quantity"] == 2
    assert item["meal_name"] == "Poulet DG"
    assert item["accompaniments"][0]["name"] == "Plantain"
    assert item["boissons"][0]["name"] == "Jus d'orange"

    order = Order.objects.get(pk=response.data["id"])
    assert order.client == client_user.client_profile
    assert order.items.count() == 1
    assert Payment.objects.filter(order=order, status=PaymentStatus.PENDING).exists()
    client_user.client_profile.refresh_from_db()
    assert client_user.client_profile.loyalty_points == 10


@pytest.mark.django_db
def test_create_order_ignores_any_client_supplied_amount(
    auth_client,
    meal,
    accompaniment,
    boisson,
    address,
):
    response = auth_client.post(
        CREATE_ORDER_URL,
        order_payload(meal, accompaniment, boisson, address, total_amount="1"),
        format="json",
    )

    assert response.status_code == 201
    assert Decimal(response.data["total_amount"]) == Decimal("8400")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "address_value",
    ["", "not-a-uuid", "11111111-1111-1111-1111-111111111111"],
)
def test_create_order_rejects_an_unusable_address(
    auth_client,
    meal,
    accompaniment,
    boisson,
    address,
    address_value,
):
    response = auth_client.post(
        CREATE_ORDER_URL,
        order_payload(
            meal,
            accompaniment,
            boisson,
            address,
            delivery_address_id=address_value,
        ),
        format="json",
    )

    assert response.status_code == 400
    assert "delivery_address_id" in response.data
    assert Order.objects.count() == 0


@pytest.mark.django_db
def test_create_order_rejects_another_clients_address(
    auth_client,
    other_user,
    meal,
    accompaniment,
    boisson,
):
    foreign = Address.objects.create(
        client=other_user.client_profile,
        city="Yaoundé",
        street="Bastos",
    )

    response = auth_client.post(
        CREATE_ORDER_URL,
        order_payload(meal, accompaniment, boisson, foreign),
        format="json",
    )

    assert response.status_code == 400
    assert Order.objects.count() == 0


@pytest.mark.django_db
def test_create_order_without_items_and_empty_cart_is_rejected(auth_client, address):
    response = auth_client.post(
        CREATE_ORDER_URL,
        {"delivery_address_id": str(address.id)},
        format="json",
    )

    assert response.status_code == 400
    assert "items" in response.data
    assert Order.objects.count() == 0


@pytest.mark.django_db
def test_create_order_can_use_the_session_cart_and_clears_it(
    auth_client,
    meal,
    boisson,
    address,
):
    added = auth_client.post(
        CART_URL,
        {
            "meal_id": str(meal.id),
            "quantity": 2,
            "boissons": [{"id": str(boisson.id), "quantity": 1}],
        },
        format="json",
    )
    assert added.status_code == 200
    # La boisson entre dans le prix unitaire : (2500 + 700) x 2.
    assert Decimal(added.data["total"]) == Decimal("6400")

    response = auth_client.post(
        CREATE_ORDER_URL,
        {"delivery_address_id": str(address.id)},
        format="json",
    )

    assert response.status_code == 201
    # (2500 + 700) x 2 = 6400, + livraison 1000.
    assert Decimal(response.data["total_amount"]) == Decimal("7400")

    cart = auth_client.get("/api/v1/cart/")
    assert cart.status_code == 200
    assert cart.data["count"] == 0
    assert cart.data["total"] == "0"


@pytest.mark.django_db
def test_create_order_requires_authentication(anonymous_client, meal, address):
    response = anonymous_client.post(
        CREATE_ORDER_URL,
        {
            "delivery_address_id": str(address.id),
            "items": [{"meal_id": str(meal.id), "quantity": 1}],
        },
        format="json",
    )

    assert response.status_code == 401
    assert Order.objects.count() == 0


@pytest.mark.django_db
def test_orders_are_scoped_to_the_authenticated_client(
    auth_client,
    admin_user,
    meal,
    accompaniment,
    boisson,
    address,
):
    mine = auth_client.post(
        CREATE_ORDER_URL,
        order_payload(meal, accompaniment, boisson, address),
        format="json",
    )
    assert mine.status_code == 201

    listed = auth_client.get(ORDERS_URL)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.data] == [mine.data["id"]]

    detail = auth_client.get(f"{ORDERS_URL}{mine.data['id']}/")
    assert detail.status_code == 200
    assert Decimal(detail.data["total_amount"]) == Decimal("8400")

    # Un autre client (ici l'admin sans profil client) ne voit rien.
    other = APIClient()
    other.force_authenticate(admin_user)
    assert other.get(ORDERS_URL).status_code == 200
    assert other.get(ORDERS_URL).data == []
    assert other.get(f"{ORDERS_URL}{mine.data['id']}/").status_code == 404


@pytest.mark.django_db
def test_an_admin_can_list_every_order(
    admin_user,
    auth_client,
    meal,
    accompaniment,
    boisson,
    address,
):
    auth_client.post(
        CREATE_ORDER_URL,
        order_payload(meal, accompaniment, boisson, address),
        format="json",
    )

    admin = APIClient()
    admin.force_authenticate(admin_user)

    listed = admin.get("/api/v1/admin/orders/")
    assert listed.status_code == 200
    assert len(listed.data) == 1
