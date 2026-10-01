from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from restaurants.meal.models import Accompaniment
from restaurants.meal.models import Boisson
from restaurants.meal.models import Category
from restaurants.meal.models import Meal
from restaurants.users.models import Address
from restaurants.users.models import RegistrationOtp
from restaurants.users.models import User


@pytest.mark.django_db
def test_mobile_authentication_requires_otp_and_returns_jwt():
    client = APIClient()
    response = client.post(
        "/api/v1/auth/register/",
        {
            "email": "mobile@example.com",
            "first_name": "Mobile",
            "last_name": "Client",
            "phone": "+237690000000",
            "password": "MotDePasseSolide123!",
            "confirm_password": "MotDePasseSolide123!",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["email"] == "mobile@example.com"
    assert response.data["detail"] == "OTP envoyé par email."

    otp = RegistrationOtp.objects.get(email="mobile@example.com", purpose="register")
    assert otp.otp_code

    verify = client.post(
        "/api/v1/auth/verify-otp/",
        {
            "email": "mobile@example.com",
            "otp": otp.otp_code,
        },
        format="json",
    )

    assert verify.status_code == 201
    assert "access" in verify.data
    assert "refresh" in verify.data
    assert verify.data["user"]["email"] == "mobile@example.com"


@pytest.mark.django_db
def test_mobile_order_is_priced_on_the_server():
    user = User.objects.create_user(
        email="order@example.com",
        phone="+237691000000",
        password="MotDePasseSolide123!",
    )
    category = Category.objects.create(name="Plats")
    accompaniment = Accompaniment.objects.create(name="Plantain", price=Decimal("500"))
    meal = Meal.objects.create(name="Poulet", category=category, price=Decimal("2500"))
    meal.accompaniments.add(accompaniment)
    boisson = Boisson.objects.create(name="Jus", price=Decimal("700"))
    address = Address.objects.create(
        client=user.client_profile,
        city="Bafoussam",
        street="Centre-ville",
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/v1/orders/create_order/",
        {
            "delivery_address_id": str(address.id),
            "payment_method": "cash",
            "items": [
                {
                    "meal_id": str(meal.id),
                    "quantity": 2,
                    "accompaniments": [str(accompaniment.id)],
                    "boissons": [str(boisson.id)],
                },
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    assert Decimal(response.data["total_amount"]) == Decimal("8400")
    assert response.data["items"][0]["quantity"] == 2


@pytest.mark.django_db
def test_cart_accepts_a_meal_and_a_boisson():
    category = Category.objects.create(name="Menu")
    meal = Meal.objects.create(name="Ndolé", category=category, price=Decimal("3000"))
    boisson = Boisson.objects.create(name="Eau", price=Decimal("300"))
    client = APIClient()

    response = client.post(
        "/api/v1/cart/add/",
        {
            "meal_id": str(meal.id),
            "quantity": 2,
            "boissons": [{"id": str(boisson.id), "quantity": 1}],
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert Decimal(response.data["total"]) == Decimal("6600")


@pytest.mark.django_db
def test_only_an_admin_can_manage_categories():
    client = APIClient()
    user = User.objects.create_user(
        email="client@example.com",
        phone="+237692000000",
        password="MotDePasseSolide123!",
    )
    client.force_authenticate(user)
    forbidden = client.post(
        "/api/v1/admin/categories/",
        {"name": "Soupes"},
        format="json",
    )
    assert forbidden.status_code == 403

    admin = User.objects.create_superuser(
        email="admin@example.com",
        password="MotDePasseSolide123!",
    )
    client.force_authenticate(admin)
    response = client.post(
        "/api/v1/admin/categories/",
        {"name": "Soupes", "display_order": 4},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["name"] == "Soupes"


@pytest.mark.django_db
def test_client_and_admin_can_exchange_chat_messages():
    client_user = User.objects.create_user(
        email="chat-client@example.com",
        phone="+237693000000",
        password="MotDePasseSolide123!",
    )
    admin = User.objects.create_superuser(
        email="chat-admin@example.com",
        password="MotDePasseSolide123!",
    )
    client = APIClient()

    client.force_authenticate(client_user)
    sent = client.post(
        "/api/v1/chat/",
        {"content": "Bonjour, où est ma commande ?"},
        format="json",
    )
    assert sent.status_code == 201
    assert sent.data["sender_role"] == "client"

    conversation_id = str(client_user.conversation.id)
    client.force_authenticate(admin)
    inbox = client.get("/api/v1/admin/chats/")
    assert inbox.status_code == 200
    assert inbox.data[0]["unread_count"] == 1

    reply = client.post(
        f"/api/v1/admin/chats/{conversation_id}/messages/",
        {"content": "Votre commande est en préparation."},
        format="json",
    )
    assert reply.status_code == 201
    assert reply.data["sender_role"] == "admin"
