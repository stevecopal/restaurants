"""Catalogue public : jours des plats, menus, images, infos restaurant."""

from __future__ import annotations

import base64
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from restaurants.meal.models import Boisson
from restaurants.meal.models import Category
from restaurants.meal.models import DailyMenu
from restaurants.meal.models import Meal
from restaurants.users.models import CompanySetting
from restaurants.users.models import User

MEALS_URL = "/api/v1/meals/"
MENUS_URL = "/api/v1/menus/"
CATEGORIES_URL = "/api/v1/categories/"
BOISSONS_URL = "/api/v1/boissons/"
COMPANY_URL = "/api/v1/company-settings/"
NEWSLETTER_URL = "/api/v1/newsletter/"

# PNG 1 x 1 valide : Pillow vérifie réellement les images envoyées.
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
)


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def category(db):
    return Category.objects.create(name="Plats")


@pytest.fixture
def meal(db, category):
    return Meal.objects.create(name="Ndolé", category=category, price=Decimal("3000"))


@pytest.fixture
def monday_menu(db, meal):
    menu = DailyMenu.objects.create(day="monday")
    menu.meals.add(meal)
    return menu


@pytest.mark.django_db
def test_menus_endpoint_exposes_active_days_and_their_meals(
    anonymous_client,
    monday_menu,
    meal,
):
    DailyMenu.objects.create(day="tuesday", is_active=False)

    response = anonymous_client.get(MENUS_URL)

    assert response.status_code == 200
    assert [menu["day"] for menu in response.data] == ["monday"]
    assert response.data[0]["day_label"] == "Lundi"
    assert response.data[0]["is_active"] is True
    embedded = response.data[0]["meals"][0]
    assert embedded["name"] == "Ndolé"
    assert "monday" in embedded["days"]


@pytest.mark.django_db
def test_meals_expose_their_days_and_availability_mode(
    anonymous_client,
    monday_menu,
    meal,
):
    response = anonymous_client.get(MEALS_URL)

    assert response.status_code == 200
    item = response.data[0]
    assert item["availability_mode"] == "always"
    assert item["days"] == ["monday"]

    detail = anonymous_client.get(f"{MEALS_URL}{meal.id}/")
    assert detail.status_code == 200
    assert detail.data["days"] == ["monday"]


@pytest.mark.django_db
def test_unavailable_meals_are_hidden_from_the_public_menu(anonymous_client, category):
    Meal.objects.create(
        name="Plat épuisé",
        category=category,
        price=Decimal("1000"),
        is_available=False,
    )

    response = anonymous_client.get(MEALS_URL)

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_meal_image_url_is_absolute(anonymous_client, category):
    meal = Meal.objects.create(
        name="Poulet braisé",
        category=category,
        price=Decimal("4000"),
    )
    meal.image = SimpleUploadedFile("poulet.png", PIXEL_PNG, content_type="image/png")
    meal.save()

    response = anonymous_client.get(f"{MEALS_URL}{meal.id}/")

    assert response.status_code == 200
    assert response.data["image_url"].startswith("http")
    assert response.data["image_url"].endswith("poulet.png")


@pytest.mark.django_db
def test_api_returns_the_complete_cloudinary_url(
    anonymous_client,
    category,
    monkeypatch,
):
    meal = Meal.objects.create(name="Poulet", category=category, price=Decimal("2500"))
    Meal.objects.filter(pk=meal.pk).update(image="media/meals/poulet")
    secure_url = (
        "https://res.cloudinary.com/demo/image/upload/v1756291702/media/meals/poulet"
    )
    storage = Meal._meta.get_field("image").storage
    monkeypatch.setattr(storage, "url", lambda name: secure_url)

    response = anonymous_client.get(f"/api/v1/meals/{meal.id}/")

    assert response.status_code == 200
    assert response.data["image_url"] == secure_url
    assert response.data["image_url"].startswith("https://")


@pytest.mark.django_db
def test_categories_and_boissons_are_public(anonymous_client, category):
    Boisson.objects.create(name="Eau minérale", price=Decimal("200"))
    Boisson.objects.create(name="Bière", price=Decimal("500"), is_available=False)

    categories = anonymous_client.get(CATEGORIES_URL)
    assert categories.status_code == 200
    assert [item["name"] for item in categories.data] == ["Plats"]

    boissons = anonymous_client.get(BOISSONS_URL)
    assert boissons.status_code == 200
    assert [item["name"] for item in boissons.data] == ["Eau minérale"]


@pytest.mark.django_db
def test_company_settings_returns_200_even_when_empty(anonymous_client):
    assert anonymous_client.get(COMPANY_URL).data == {}

    setting = CompanySetting.objects.create(
        restaurant_name="Mam's",
        slogan="Le meilleur de Bafoussam",
    )
    setting.logo = SimpleUploadedFile("logo.png", PIXEL_PNG, content_type="image/png")
    setting.save()
    response = anonymous_client.get(COMPANY_URL)

    assert response.status_code == 200
    assert response.data["restaurant_name"] == "Mam's"
    assert response.data["logo_url"].startswith("http")


@pytest.mark.django_db
def test_newsletter_subscription_and_duplicate(anonymous_client):
    created = anonymous_client.post(
        NEWSLETTER_URL,
        {"email": "fan@example.com"},
        format="json",
    )
    assert created.status_code == 201

    duplicate = anonymous_client.post(
        NEWSLETTER_URL,
        {"email": "fan@example.com"},
        format="json",
    )
    assert duplicate.status_code == 400
    assert "email" in duplicate.data

    invalid = anonymous_client.post(
        NEWSLETTER_URL,
        {"email": "pas-un-email"},
        format="json",
    )
    assert invalid.status_code == 400


@pytest.mark.django_db
def test_custom_requests_need_a_client_profile(anonymous_client, auth_client, db):
    payload = {"description": "Un plateau pour 10 personnes", "quantity": 1}

    assert (
        anonymous_client.post(
            "/api/v1/custom-requests/",
            payload,
            format="json",
        ).status_code
        == 401
    )

    created = auth_client.post("/api/v1/custom-requests/", payload, format="json")
    assert created.status_code == 201

    listed = auth_client.get("/api/v1/custom-requests/")
    assert listed.status_code == 200
    assert len(listed.data) == 1


@pytest.mark.django_db
def test_admin_can_create_a_meal_with_an_image_and_a_day(db):
    admin = APIClient()
    admin_user = User.objects.create_superuser(
        email="chef@example.com",
        password="MotDePasseSolide123!",
    )
    admin.force_authenticate(admin_user)

    category = Category.objects.create(name="Spécialités")
    menu = DailyMenu.objects.create(day="friday")
    image = SimpleUploadedFile("sadza.png", PIXEL_PNG, content_type="image/png")

    created = admin.post(
        "/api/v1/admin/meals/",
        {
            "name": "Sadza",
            "price": "2000",
            "category": str(category.id),
            "daily_menus": [str(menu.id)],
            "availability_mode": "specific_days",
            "image": image,
        },
        format="multipart",
    )

    assert created.status_code == 201
    assert created.data["slug"] == "sadza"
    # Un upload multipart sans booléens explicites ne doit pas désactiver le plat.
    assert created.data["is_available"] is True
    assert created.data["is_active"] is True
    assert [str(pk) for pk in created.data["daily_menus"]] == [str(menu.id)]

    meal_id = created.data["id"]
    public = APIClient().get(f"/api/v1/meals/{meal_id}/")
    assert public.status_code == 200
    assert public.data["image_url"].startswith("http")
    assert public.data["days"] == ["friday"]
