import uuid
from decimal import Decimal

from rest_framework import serializers

from restaurants.meal.enum import OrderStatus
from restaurants.meal.enum import PaymentMethod
from restaurants.meal.enum import PaymentStatus
from restaurants.meal.models import Accompaniment
from restaurants.meal.models import Boisson
from restaurants.meal.models import Category
from restaurants.meal.models import CustomOrderRequest
from restaurants.meal.models import DailyMenu
from restaurants.meal.models import Meal
from restaurants.meal.models import Order
from restaurants.meal.models import OrderItem
from restaurants.meal.models import OrderItemAccompaniment
from restaurants.meal.models import OrderItemBoisson
from restaurants.meal.models import Payment
from restaurants.users.models import Address
from restaurants.users.models import Client
from restaurants.users.models import NewsletterSubscriber
from restaurants.users.models import Testimonial
from restaurants.users.models import User

DELIVERY_FEE = Decimal("1000")
LOYALTY_GIFT_THRESHOLD = 100


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "phone", "name"]


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = [
            "id", "street", "city", "description", "complement",
            "gps_lat", "gps_lng", "is_default",
        ]


class RegisterOtpSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Confirmation du mot de passe (si fournie, doit correspondre).",
    )

    def validate(self, attrs):
        confirm = attrs.pop("confirm_password", "")
        if confirm and confirm != attrs["password"]:
            raise serializers.ValidationError(
                {"confirm_password": ["Les mots de passe ne correspondent pas."]},
            )
        return attrs


class VerifyOtpSerializer(serializers.Serializer):
    email = serializers.EmailField(
        help_text="Adresse email utilisée lors de l'inscription.",
    )
    otp = serializers.CharField(
        min_length=6,
        max_length=6,
        help_text="Code OTP à 6 chiffres reçu par email.",
    )


class OtpSentSerializer(serializers.Serializer):
    detail = serializers.CharField()
    email = serializers.EmailField()


class TokenResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


class ErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField(required=False)
    error = serializers.CharField(required=False)
    field = serializers.ListField(child=serializers.CharField(), required=False)


class CartComponentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class CartAddSerializer(serializers.Serializer):
    meal_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)
    accompaniments = CartComponentSerializer(many=True, required=False)
    boissons = CartComponentSerializer(many=True, required=False)


class CartBoissonSerializer(serializers.Serializer):
    boisson_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class CartItemUpdateSerializer(serializers.Serializer):
    item_id = serializers.CharField()
    quantity = serializers.IntegerField(min_value=0)


class CartItemRemoveSerializer(serializers.Serializer):
    item_id = serializers.CharField()


class CartComponentUpdateSerializer(serializers.Serializer):
    item_id = serializers.CharField()
    component_type = serializers.ChoiceField(choices=["accompaniment", "boisson"])
    component_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=0)


class CartItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    quantity = serializers.IntegerField()
    meal_id = serializers.UUIDField(required=False)
    boisson_id = serializers.UUIDField(required=False)
    meal_name = serializers.CharField()
    meal_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    meal_image_url = serializers.CharField(required=False, allow_blank=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    accompaniments = serializers.ListField()
    boissons = serializers.ListField()


class CartResponseSerializer(serializers.Serializer):
    items = CartItemSerializer(many=True)
    count = serializers.IntegerField()
    total = serializers.DecimalField(max_digits=10, decimal_places=2)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower()
        password = attrs["password"]
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist as exc:
            msg = {"email": ["Identifiants invalides."]}
            raise serializers.ValidationError(msg) from exc

        if not user.check_password(password):
            msg = {"email": ["Identifiants invalides."]}
            raise serializers.ValidationError(msg)

        attrs["user"] = user
        return attrs


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class BoissonSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Boisson
        fields = ["id", "name", "slug", "price", "image_url", "is_available"]

    def get_image_url(self, obj) -> str:
        request = self.context.get("request")
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url if obj.image else ""


class MealSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    accompaniments = serializers.StringRelatedField(many=True)
    image_url = serializers.SerializerMethodField()
    days = serializers.SerializerMethodField()

    class Meta:
        model = Meal
        fields = [
            "id", "name", "slug", "description", "price", "image_url", "category",
            "is_available", "max_included_accompaniments", "accompaniments",
            "availability_mode", "days",
        ]

    def get_image_url(self, obj) -> str:
        request = self.context.get("request")
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url if obj.image else ""

    def get_days(self, obj) -> list[str]:
        """Jours de la semaine où ce plat est au menu (DailyMenu actifs)."""
        return [menu.day for menu in obj.daily_menus.all() if menu.is_active]


class DailyMenuSerializer(serializers.ModelSerializer):
    day_label = serializers.CharField(source="get_day_display", read_only=True)
    meals = MealSerializer(many=True, read_only=True)

    class Meta:
        model = DailyMenu
        fields = ["id", "day", "day_label", "is_active", "meals"]


class OrderItemSerializer(serializers.ModelSerializer):
    meal_name = serializers.CharField(source="meal.name", read_only=True, default=None)
    meal_image_url = serializers.SerializerMethodField()
    accompaniments = serializers.SerializerMethodField()
    boissons = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id", "meal", "meal_name", "meal_image_url", "quantity", "unit_price",
            "subtotal", "extra_accompaniments_fee", "accompaniments", "boissons",
        ]

    def get_meal_image_url(self, obj) -> str:
        image = obj.meal.image if obj.meal else None
        request = self.context.get("request")
        if image and request:
            return request.build_absolute_uri(image.url)
        return image.url if image else ""

    def get_accompaniments(self, obj) -> list[dict]:
        return [
            {
                "id": str(link.accompaniment_id),
                "name": link.accompaniment.name,
                "price": str(link.accompaniment.price),
                "quantity": link.quantity,
            }
            for link in obj.order_item_accompaniments.select_related("accompaniment")
        ]

    def get_boissons(self, obj) -> list[dict]:
        return [
            {
                "id": str(link.boisson_id),
                "name": link.boisson.name,
                "price": str(link.boisson.price),
                "quantity": link.quantity,
            }
            for link in obj.order_item_boissons.select_related("boisson")
        ]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    delivery_address = AddressSerializer(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "status", "payment_method", "total_amount", "delivery_address",
            "created", "items",
        ]


class ComponentInputField(serializers.Field):
    """Liste d'identifiants UUID, avec quantité optionnelle par élément.

    Accepte à la fois ``["<uuid>", ...]`` et
    ``[{"id": "<uuid>", "quantity": 2}, ...]`` pour rester compatible avec
    les payloads envoyés par l'application React Native.
    """

    def to_internal_value(self, data):
        if not isinstance(data, (list, tuple)):
            msg = "Une liste est attendue."
            raise serializers.ValidationError(msg)
        components = []
        for item in data:
            if isinstance(item, dict):
                raw_id = item.get("id")
                quantity = item.get("quantity", 1)
            else:
                raw_id, quantity = item, 1
            try:
                component_id = uuid.UUID(str(raw_id))
                quantity = int(quantity)
            except (ValueError, TypeError, AttributeError) as exc:
                msg = "Identifiant ou quantité invalide."
                raise serializers.ValidationError(msg) from exc
            if quantity < 1:
                msg = "La quantité doit être supérieure à zéro."
                raise serializers.ValidationError(msg)
            components.append({"id": component_id, "quantity": quantity})
        return components

    def to_representation(self, value):
        return value


class OrderItemCreateSerializer(serializers.Serializer):
    meal_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)
    accompaniments = ComponentInputField(required=False, default=list)
    boissons = ComponentInputField(required=False, default=list)


class OrderCreateSerializer(serializers.Serializer):
    """Création de commande côté serveur (tarification jamais faite par le client)."""

    delivery_address_id = serializers.UUIDField(
        help_text="UUID de l'adresse de livraison du client (modèle Address).",
    )
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        required=False,
        default=PaymentMethod.CASH,
    )
    items = OrderItemCreateSerializer(
        many=True,
        required=False,
        help_text="Articles de la commande. Si omis, le panier de session est utilisé.",
    )

    def validate_delivery_address_id(self, value):
        request = self.context.get("request")
        client = getattr(request.user, "client_profile", None) if request else None
        address = None
        if client is not None:
            address = Address.objects.filter(pk=value, client=client).first()
        if address is None:
            # Même message pour "inexistant" et "appartenant à un autre client"
            # afin de ne pas révéler l'existence des adresses des autres clients.
            msg = "Adresse de livraison introuvable ou accès refusé."
            raise serializers.ValidationError(msg)
        return address

    def validate(self, attrs):
        items = attrs.get("items")
        if not items:
            cart = self.context.get("cart_items") or []
            if not cart:
                raise serializers.ValidationError(
                    {"items": ["Aucun article à commander (panier vide)."]},
                )
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        client, _ = Client.objects.get_or_create(user=request.user)
        items_data = validated_data.pop("items", None)
        address = validated_data.get("delivery_address_id")
        payment_method = validated_data.get("payment_method") or PaymentMethod.CASH
        cart = self.context.get("cart")

        order = Order.objects.create(
            client=client,
            delivery_address=address,
            status=OrderStatus.PENDING,
            payment_method=payment_method,
            total_amount=0,
        )

        if items_data:
            self._create_items_from_payload(order, items_data)
        else:
            self._create_items_from_cart(order, cart)

        order.total_amount = order.recalculate_total(save=False) + DELIVERY_FEE
        order.save()

        # Points de fidélité : identique au checkout du site web.
        client.loyalty_points += 10
        if client.loyalty_points >= LOYALTY_GIFT_THRESHOLD:
            order.has_loyalty_gift = True
            order.save(update_fields=["has_loyalty_gift"])
            client.loyalty_points -= LOYALTY_GIFT_THRESHOLD
        client.save(update_fields=["loyalty_points"])

        Payment.objects.create(
            order=order, method=payment_method, status=PaymentStatus.PENDING,
        )

        if not items_data and cart is not None:
            cart.clear()

        try:
            # Import local : les tâches Celery ne sont chargées qu'à la
            # création effective d'une commande.
            from restaurants.users.tasks import (  # noqa: PLC0415
                send_new_order_admin_notification_task,
            )

            send_new_order_admin_notification_task.delay(str(order.id))
        except Exception:  # noqa: BLE001, S110 - jamais bloquant pour le client
            pass

        return order

    @staticmethod
    def _create_items_from_payload(order, items_data):
        """Construit les lignes à partir du payload envoyé par le mobile."""
        for item in items_data:
            meal = Meal.objects.filter(pk=item["meal_id"], is_available=True).first()
            if meal is None:
                raise serializers.ValidationError(
                    {"items": ["Plat introuvable ou indisponible."]},
                )
            order_item = OrderItem.objects.create(
                order=order,
                meal=meal,
                quantity=item["quantity"],
                unit_price=meal.price,
            )
            allowed = set(meal.accompaniments.values_list("id", flat=True))
            for comp in item.get("accompaniments", []):
                if comp["id"] not in allowed:
                    raise serializers.ValidationError(
                        {"items": ["Accompagnement invalide pour ce plat."]},
                    )
                OrderItemAccompaniment.objects.create(
                    order_item=order_item,
                    accompaniment_id=comp["id"],
                    quantity=comp["quantity"],
                )
            for comp in item.get("boissons", []):
                boisson = Boisson.objects.filter(
                    pk=comp["id"], is_available=True,
                ).first()
                if boisson is None:
                    raise serializers.ValidationError(
                        {"items": ["Boisson indisponible."]},
                    )
                OrderItemBoisson.objects.create(
                    order_item=order_item,
                    boisson=boisson,
                    quantity=comp["quantity"],
                )
            order_item.recalculate(save=True)

    @staticmethod
    def _create_items_from_cart(order, cart):
        """Construit les lignes à partir du panier de session (flux site web)."""
        for item in cart:
            if item.get("is_standalone_boisson"):
                order_item = OrderItem.objects.create(
                    order=order, meal=None, quantity=item["quantity"], unit_price=0,
                )
                boisson = Boisson.objects.filter(
                    pk=item["boisson_id"], is_available=True,
                ).first()
                if boisson:
                    OrderItemBoisson.objects.create(
                        order_item=order_item,
                        boisson=boisson,
                        quantity=item["quantity"],
                    )
                order_item.recalculate(save=True)
                continue

            meal = Meal.objects.filter(
                pk=item["meal_id"], is_available=True,
            ).first()
            if meal is None:
                raise serializers.ValidationError(
                    {"items": ["Plat introuvable ou indisponible."]},
                )
            order_item = OrderItem.objects.create(
                order=order,
                meal=meal,
                quantity=item["quantity"],
                unit_price=meal.price,
            )
            for b_data in item.get("boissons", []):
                boisson = Boisson.objects.filter(
                    pk=b_data["id"], is_available=True,
                ).first()
                if boisson:
                    OrderItemBoisson.objects.create(
                        order_item=order_item,
                        boisson=boisson,
                        quantity=int(b_data["quantity"]),
                    )
            for a_data in item.get("accompaniments", []):
                accompaniment = Accompaniment.objects.filter(
                    pk=a_data["id"],
                ).first()
                if accompaniment:
                    OrderItemAccompaniment.objects.create(
                        order_item=order_item,
                        accompaniment=accompaniment,
                        quantity=int(a_data["quantity"]),
                    )
            order_item.recalculate(save=True)


class CustomOrderRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomOrderRequest
        fields = ["id", "description", "quantity", "target_date", "status", "created"]


class TestimonialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = ["id", "rating", "comment", "status", "created"]
        read_only_fields = ["id", "status", "created"]


class NewsletterSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsletterSubscriber
        fields = ["id", "email"]

