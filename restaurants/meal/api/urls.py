from django.urls import include, path
from rest_framework.routers import DefaultRouter


from .views.admin_api import (
    AdminAccompanimentViewSet,
    AdminBoissonViewSet,
    AdminCategoryViewSet,
    AdminCustomRequestViewSet,
    AdminMealViewSet,
    AdminOrderViewSet,
)

from .views.boisson_api import BoissonListAPIView
from .views.category_api import CategoryListAPIView
from .views.custom_request_api import CustomOrderRequestViewSet
from .views.meal_api import MealViewSet
from .views.menu_api import DailyMenuListAPIView



app_name = "meal_api"



router = DefaultRouter()



router.register(
    "meals",
    MealViewSet,
    basename="meal",
)


router.register(
    "custom-requests",
    CustomOrderRequestViewSet,
    basename="custom-request",
)



# ADMIN

router.register(
    "admin/categories",
    AdminCategoryViewSet,
    basename="admin-category",
)


router.register(
    "admin/meals",
    AdminMealViewSet,
    basename="admin-meal",
)


router.register(
    "admin/accompaniments",
    AdminAccompanimentViewSet,
    basename="admin-accompaniment",
)


router.register(
    "admin/boissons",
    AdminBoissonViewSet,
    basename="admin-boisson",
)


router.register(
    "admin/orders",
    AdminOrderViewSet,
    basename="admin-order",
)


router.register(
    "admin/custom-requests",
    AdminCustomRequestViewSet,
    basename="admin-custom-request",
)




urlpatterns = [


    path(
        "categories/",
        CategoryListAPIView.as_view(),
        name="category-list",
    ),


    path(
        "boissons/",
        BoissonListAPIView.as_view(),
        name="boisson-list",
    ),


    path(
        "menus/",
        DailyMenuListAPIView.as_view(),
        name="daily-menu-list",
    ),


    path(
        "",
        include(router.urls),
    ),

]
