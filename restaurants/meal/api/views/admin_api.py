"""Endpoints REST réservés à l'administration du restaurant."""

from rest_framework import permissions, serializers, viewsets
from rest_framework.fields import empty
from rest_framework.utils import html
from drf_spectacular.utils import extend_schema_view

from restaurants.meal.enum import CustomRequestStatus, OrderStatus
from restaurants.meal.models import Accompaniment, Boisson, Category, CustomOrderRequest, DailyMenu, Meal, Order
from ..docs.admin_api import (
    admin_accompaniment_create_doc, admin_accompaniment_delete_doc, admin_accompaniment_detail_doc,
    admin_accompaniment_list_doc, admin_accompaniment_update_doc,
    admin_boisson_create_doc, admin_boisson_delete_doc, admin_boisson_detail_doc,
    admin_boisson_list_doc, admin_boisson_update_doc,
    admin_category_create_doc, admin_category_delete_doc, admin_category_detail_doc,
    admin_category_list_doc, admin_category_update_doc,
    admin_custom_request_detail_doc, admin_custom_request_list_doc, admin_custom_request_update_doc,
    admin_meal_create_doc, admin_meal_delete_doc, admin_meal_detail_doc,
    admin_meal_list_doc, admin_meal_update_doc,
    admin_order_detail_doc, admin_order_list_doc, admin_order_update_doc,
)


class MultipartSafeBooleanField(serializers.BooleanField):
    """Booléen qui respecte la valeur par défaut du modèle sur un formulaire.

    DRF transforme en ``False`` tout booléen absent d'un input HTML : créer un
    plat ou une boisson en multipart sans envoyer explicitement ``is_available``
    désactivait silencieusement l'objet (invisible sur le site et l'API).
    """

    def get_value(self, dictionary):
        if html.is_html_input(dictionary) and self.field_name not in dictionary:
            return empty
        return super().get_value(dictionary)


class AdminOnlyViewSet(viewsets.ModelViewSet):
    """Toutes les opérations ci-dessous exigent un token d'administrateur."""

    permission_classes = (permissions.IsAdminUser,)


class AdminCategorySerializer(serializers.ModelSerializer):
    is_active = MultipartSafeBooleanField(required=False, default=True)

    class Meta:
        model = Category
        fields = ("id", "name", "slug", "display_order", "is_active")
        read_only_fields = ("id", "slug")


class AdminAccompanimentSerializer(serializers.ModelSerializer):
    is_active = MultipartSafeBooleanField(required=False, default=True)

    class Meta:
        model = Accompaniment
        fields = ("id", "name", "slug", "price", "is_active")
        read_only_fields = ("id", "slug")


class AdminBoissonSerializer(serializers.ModelSerializer):
    is_active = MultipartSafeBooleanField(required=False, default=True)
    is_available = MultipartSafeBooleanField(required=False, default=True)

    class Meta:
        model = Boisson
        fields = ("id", "name", "slug", "price", "image", "is_available", "is_active")
        read_only_fields = ("id", "slug")


class AdminMealSerializer(serializers.ModelSerializer):
    daily_menus = serializers.PrimaryKeyRelatedField(
        queryset=DailyMenu.objects.all(),
        many=True,
        required=False,
        help_text="UUID des menus journaliers (jours) auxquels ce plat appartient.",
    )
    is_active = MultipartSafeBooleanField(required=False, default=True)
    is_available = MultipartSafeBooleanField(required=False, default=True)

    class Meta:
        model = Meal
        fields = (
            "id", "name", "slug", "description", "price", "image", "category",
            "accompaniments", "max_included_accompaniments", "availability_mode",
            "daily_menus", "is_available", "is_active",
        )
        read_only_fields = ("id", "slug")


@extend_schema_view(list=admin_category_list_doc, create=admin_category_create_doc, retrieve=admin_category_detail_doc, update=admin_category_update_doc, partial_update=admin_category_update_doc, destroy=admin_category_delete_doc)
class AdminCategoryViewSet(AdminOnlyViewSet):
    queryset = Category.objects.all().order_by("display_order", "name")
    serializer_class = AdminCategorySerializer


@extend_schema_view(list=admin_accompaniment_list_doc, create=admin_accompaniment_create_doc, retrieve=admin_accompaniment_detail_doc, update=admin_accompaniment_update_doc, partial_update=admin_accompaniment_update_doc, destroy=admin_accompaniment_delete_doc)
class AdminAccompanimentViewSet(AdminOnlyViewSet):
    queryset = Accompaniment.objects.all().order_by("name")
    serializer_class = AdminAccompanimentSerializer


@extend_schema_view(list=admin_boisson_list_doc, create=admin_boisson_create_doc, retrieve=admin_boisson_detail_doc, update=admin_boisson_update_doc, partial_update=admin_boisson_update_doc, destroy=admin_boisson_delete_doc)
class AdminBoissonViewSet(AdminOnlyViewSet):
    queryset = Boisson.objects.all().order_by("name")
    serializer_class = AdminBoissonSerializer


@extend_schema_view(list=admin_meal_list_doc, create=admin_meal_create_doc, retrieve=admin_meal_detail_doc, update=admin_meal_update_doc, partial_update=admin_meal_update_doc, destroy=admin_meal_delete_doc)
class AdminMealViewSet(AdminOnlyViewSet):
    queryset = Meal.objects.select_related("category").prefetch_related("accompaniments", "daily_menus")
    serializer_class = AdminMealSerializer


class AdminOrderSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.user.name", read_only=True)
    client_email = serializers.EmailField(source="client.user.email", read_only=True)

    class Meta:
        model = Order
        fields = ("id", "client_name", "client_email", "status", "payment_method", "total_amount", "created")
        read_only_fields = ("id", "client_name", "client_email", "payment_method", "total_amount", "created")

    def validate_status(self, value):
        if self.instance and self.instance.status == OrderStatus.CANCELLED:
            raise serializers.ValidationError("Une commande annulée ne peut plus être modifiée.")
        return value


@extend_schema_view(list=admin_order_list_doc, retrieve=admin_order_detail_doc, partial_update=admin_order_update_doc)
class AdminOrderViewSet(AdminOnlyViewSet):
    http_method_names = ("get", "patch", "head", "options")
    queryset = Order.objects.select_related("client__user").order_by("-created")
    serializer_class = AdminOrderSerializer

    def perform_update(self, serializer):
        order = serializer.save()
        try:
            from restaurants.users.tasks import send_order_status_update_task

            send_order_status_update_task.delay(order.id)
        except Exception:
            pass


class AdminCustomRequestSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.user.name", read_only=True)

    class Meta:
        model = CustomOrderRequest
        fields = (
            "id", "client_name", "description", "quantity", "target_date", "status",
            "proposed_price", "rejection_reason", "linked_meal", "created",
        )
        read_only_fields = ("id", "client_name", "linked_meal", "created")

    def update(self, instance, validated_data):
        price = validated_data.get("proposed_price")
        if price is not None and not instance.linked_meal:
            category, _ = Category.objects.get_or_create(name="Sur Mesure", defaults={"display_order": 999})
            instance.linked_meal = Meal.objects.create(
                name=f"Plat sur mesure #{str(instance.id)[:8].upper()}",
                description=instance.description,
                price=price,
                category=category,
                is_available=False,
            )
            validated_data.setdefault("status", CustomRequestStatus.PRICED)
        return super().update(instance, validated_data)


@extend_schema_view(list=admin_custom_request_list_doc, retrieve=admin_custom_request_detail_doc, partial_update=admin_custom_request_update_doc)
class AdminCustomRequestViewSet(AdminOnlyViewSet):
    http_method_names = ("get", "patch", "head", "options")
    queryset = CustomOrderRequest.objects.select_related("client__user", "linked_meal").order_by("-created")
    serializer_class = AdminCustomRequestSerializer
