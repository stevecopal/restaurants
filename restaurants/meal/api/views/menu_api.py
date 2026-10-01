"""Endpoints publics des menus journaliers (jours de la semaine)."""

from drf_spectacular.utils import extend_schema_view

from restaurants.meal.api.docs.menu import daily_menu_list_doc
from restaurants.users.api.views.api_common import DailyMenuListAPIView

DailyMenuListAPIView = extend_schema_view(get=daily_menu_list_doc)(DailyMenuListAPIView)

__all__ = ["DailyMenuListAPIView"]
