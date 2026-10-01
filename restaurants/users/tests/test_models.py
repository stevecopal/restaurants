from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from restaurants.users.models import User


def test_user_is_stringified_by_its_email(user: User):
    assert str(user) == user.email
