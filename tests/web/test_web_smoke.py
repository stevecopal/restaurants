"""Pages du site web : accueil, inscription, connexion, panier, checkout."""

from __future__ import annotations

import base64
import json
from decimal import Decimal

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile

from restaurants.meal.models import Category
from restaurants.meal.models import Meal
from restaurants.meal.models import Order
from restaurants.meal.models import Payment
from restaurants.users.models import Address

PASSWORD = "MotDePasseSolide123!"

PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
)


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def meal(db):
    category = Category.objects.create(name="Plats")
    return Meal.objects.create(
        name="Poulet braisé",
        category=category,
        price=Decimal("2500"),
    )


def cart_add(client, meal, quantity=1):
    """Le panier du site attend un corps JSON, pas du form-data."""
    return client.post(
        "/api/cart/add/",
        data=json.dumps({"meal_id": str(meal.id), "quantity": quantity}),
        content_type="application/json",
    )


def test_home_page_renders_and_displays_the_meal_image(client, meal, settings, tmpdir):
    settings.MEDIA_ROOT = tmpdir.strpath
    meal.image = SimpleUploadedFile("poulet.png", PIXEL_PNG, content_type="image/png")
    meal.save()

    response = client.get("/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Poulet braisé" in content
    assert "poulet.png" in content


def test_home_page_displays_the_cloudinary_url(client, meal, monkeypatch):
    Meal.objects.filter(pk=meal.pk).update(image="media/meals/poulet")
    secure_url = (
        "https://res.cloudinary.com/demo/image/upload/v1756291702/media/meals/poulet"
    )
    storage = Meal._meta.get_field("image").storage
    monkeypatch.setattr(storage, "url", lambda name: secure_url)

    response = client.get("/")

    assert response.status_code == 200
    assert secure_url in response.content.decode()


@pytest.mark.django_db
def test_static_pages_render(client):
    for url in ("/", "/panier/", "/register/", "/verify-otp/", "/login/"):
        response = client.get(url)
        assert response.status_code == 200, f"{url} -> {response.status_code}"


def test_register_flow_sends_the_otp_by_email(client, db):
    payload = {
        "first_name": "Web",
        "last_name": "Client",
        "phone": "+237692222222",
        "email": "web@example.com",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
    }

    response = client.post("/register/", payload)

    assert response.status_code == 302
    assert response.url == "/verify-otp/"
    assert len(mail.outbox) == 1
    assert "web@example.com" in mail.outbox[0].to
    assert client.session.get("otp")
    assert client.session["register_data"]["email"] == "web@example.com"


def test_register_reports_errors_without_a_500(client, client_user):
    duplicate = client.post(
        "/register/",
        {
            "first_name": "Web",
            "last_name": "Client",
            "phone": "+237693333333",
            "email": client_user.email,
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
        follow=True,
    )
    assert duplicate.status_code == 200
    assert "déjà utilisée" in duplicate.content.decode()

    mismatch = client.post(
        "/register/",
        {
            "first_name": "Web",
            "last_name": "Client",
            "phone": "+237694444444",
            "email": "web2@example.com",
            "password": PASSWORD,
            "confirm_password": "AutreMotDePasse123!",
        },
        follow=True,
    )
    assert mismatch.status_code == 200
    assert "ne correspondent pas" in mismatch.content.decode()


def test_login_redirects_to_the_right_dashboard(client, client_user, admin_user):
    bad = client.post(
        "/login/",
        {"email": client_user.email, "password": "Mauvais123!"},
        follow=True,
    )
    assert bad.status_code == 200
    assert "Email ou mot de passe incorrect." in bad.content.decode()

    good = client.post("/login/", {"email": client_user.email, "password": PASSWORD})
    assert good.status_code == 302
    assert good.url == "/client/dashboard/"

    admin_login = client.post(
        "/login/",
        {"email": admin_user.email, "password": PASSWORD},
    )
    assert admin_login.status_code == 302
    assert admin_login.url == "/admin-dashboard/"


def test_client_pages_require_a_session(client, client_user):
    assert client.get("/client/dashboard/").status_code == 302

    client.force_login(client_user)
    for url in ("/client/dashboard/", "/client/commandes/", "/client/adresses/"):
        response = client.get(url)
        assert response.status_code == 200, f"{url} -> {response.status_code}"


def test_checkout_requires_a_non_empty_cart(client, client_user, meal):
    client.force_login(client_user)

    empty = client.get("/checkout/")
    assert empty.status_code == 302
    assert empty.url == "/"

    added = cart_add(client, meal)
    assert added.status_code == 200

    checkout = client.get("/checkout/")
    assert checkout.status_code == 200
    assert checkout.context["delivery_fee"] == 1000


def test_web_checkout_creates_the_order_with_the_delivery_fee(
    client,
    client_user,
    meal,
):
    client.force_login(client_user)
    address = Address.objects.create(
        client=client_user.client_profile,
        city="Bafoussam",
        street="Marché A",
    )
    assert cart_add(client, meal, quantity=2).status_code == 200

    response = client.post(
        "/checkout/",
        {"address_id": str(address.id), "payment_method": "cash"},
    )

    assert response.status_code == 302
    order = Order.objects.get()
    assert response.url == f"/checkout/success/{order.id}/"
    # 2500 x 2 = 5000, + livraison 1000.
    assert order.total_amount == Decimal("6000")
    assert order.delivery_address == address
    assert Payment.objects.filter(order=order).exists()
    client_user.client_profile.refresh_from_db()
    assert client_user.client_profile.loyalty_points == 10

    success = client.get(response.url)
    assert success.status_code == 200

    cart = client.get("/api/v1/cart/")
    assert cart.status_code == 200
    assert json.loads(cart.content)["count"] == 0


def test_admin_dashboard_is_reachable_for_an_admin(client, admin_user):
    assert client.get("/admin-dashboard/").status_code == 302

    client.force_login(admin_user)
    response = client.get("/admin-dashboard/")
    assert response.status_code == 200
