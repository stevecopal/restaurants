from __future__ import annotations

import pytest
from rest_framework.test import APIRequestFactory

from restaurants.users.api.views import UserViewSet
from restaurants.users.models import User


class TestUserViewSet:
    @pytest.fixture
    def api_rf(self) -> APIRequestFactory:
        return APIRequestFactory()

    def test_get_queryset(self, user: User, api_rf: APIRequestFactory):
        view = UserViewSet()
        request = api_rf.get("/fake-url/")
        request.user = user

        view.request = request

        assert user in view.get_queryset()

    def test_get_queryset_excludes_other_users(
        self, user: User, api_rf: APIRequestFactory,
    ):
        other = User.objects.create_user(
            email="other@example.com",
            phone="+237690000001",
            password="MotDePasseSolide123!",  # noqa: S106
        )
        view = UserViewSet()
        request = api_rf.get("/fake-url/")
        request.user = user

        view.request = request

        assert other not in view.get_queryset()
