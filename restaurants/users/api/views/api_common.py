import logging
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema_view
from restaurants.meal.models import Boisson, Category, CustomOrderRequest, DailyMenu, Meal, Order
from restaurants.users.cart import Cart
from restaurants.users.enum import TestimonialStatus
from restaurants.users.models import Address, Client, NewsletterSubscriber, RegistrationOtp, Testimonial, User
from restaurants.users.utils.emails import EmailUtil

from ..serializers.mobile_serializers import (
    AddressSerializer, BoissonSerializer, CategorySerializer, CustomOrderRequestSerializer,
    DailyMenuSerializer, LoginSerializer, MealSerializer, NewsletterSerializer, OrderCreateSerializer,
    OrderSerializer, RegisterOtpSerializer, UserSerializer, VerifyOtpSerializer, TestimonialSerializer,
)
from ..docs.address import (
    address_create_doc, address_delete_doc, address_detail_doc, address_list_doc,
    address_partial_update_doc, address_set_default_doc, address_update_doc,
)
from ..docs.auth import login_doc, logout_doc, register_doc, verify_otp_doc
from ..docs.newsletter import newsletter_create_doc
from ..docs.order import (
    custom_order_request_create_doc, custom_order_request_detail_doc,
    custom_order_request_list_doc, order_create_doc, order_detail_doc, order_list_doc,
)
from ..docs.profile import profile_get_doc, profile_update_doc
from ..docs.testimonial import testimonial_get_doc, testimonial_update_doc

logger = logging.getLogger(__name__)


def client_profile_of(user):
    """Profil client de l'utilisateur, ou ``None`` (admin sans profil client).

    Évite un ``RelatedObjectDoesNotExist`` (500) quand un administrateur
    appelle un endpoint réservé aux clients.
    """
    return getattr(user, "client_profile", None)


class EmptySerializer(serializers.Serializer):
    """Corps vide utilisé par l'endpoint de déconnexion dans Swagger."""


class RegisterAPIView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterOtpSerializer

    @register_doc
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].lower()
        phone = serializer.validated_data["phone"]

        if User.objects.filter(email=email).exists():
            raise ValidationError({"email": ["Cette adresse email est déjà utilisée."]})

        if User.objects.filter(phone=phone).exists():
            raise ValidationError({"phone": ["Ce numéro de téléphone existe déjà."]})

        otp_code = f"{random.randint(100000, 999999):06d}"
        expires_at = timezone.now() + timedelta(
            minutes=getattr(settings, "OTP_EXPIRY_MINUTES", 10),
        )
        registration_otp = RegistrationOtp.objects.create(
            email=email,
            data={
                "first_name": serializer.validated_data["first_name"],
                "last_name": serializer.validated_data["last_name"],
                "phone": phone,
                "email": email,
                "password": make_password(serializer.validated_data["password"]),
            },
            otp_code=otp_code,
            expires_at=expires_at,
            purpose="register",
        )

        # L'envoi d'email ne doit jamais faire échouer l'inscription :
        # l'OTP est stocké en base, le problème est journalisé côté serveur.
        try:
            email_sent = EmailUtil().send_otp_verification(
                User(email=email),
                otp_code,
                purpose="Inscription",
            )
        except Exception:  # noqa: BLE001 - provider email indisponible
            logger.exception("Échec de l'envoi de l'OTP pour %s", email)
            email_sent = False
        if not email_sent:
            logger.warning("OTP %s non envoyé pour %s", registration_otp.pk, email)

        return Response(
            {
                "detail": "OTP envoyé par email.",
                "email": email,
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyOtpAPIView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = VerifyOtpSerializer

    @verify_otp_doc
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].lower()
        otp_value = serializer.validated_data["otp"].strip()

        registration_otp = RegistrationOtp.objects.filter(
            email=email,
            purpose="register",
            is_verified=False,
            expires_at__gt=timezone.now(),
        ).first()

        if not registration_otp or registration_otp.otp_code != otp_value:
            raise ValidationError({"otp": ["Code OTP invalide ou expiré."]})

        registration_data = registration_otp.data
        if User.objects.filter(email=registration_data["email"]).exists():
            raise ValidationError(
                {"email": ["Un compte existe déjà pour cette adresse email."]}
            )

        user = User(
            email=registration_data["email"],
            phone=registration_data["phone"],
            first_name=registration_data["first_name"],
            last_name=registration_data["last_name"],
        )
        user.password = registration_data["password"]
        user.save()
        Client.objects.get_or_create(user=user)

        registration_otp.is_verified = True
        registration_otp.save(update_fields=["is_verified"])

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginAPIView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = LoginSerializer

    @login_doc
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            }
        )


class LogoutAPIView(generics.GenericAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = EmptySerializer

    @logout_doc
    def post(self, request, *args, **kwargs):
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(get=profile_get_doc, put=profile_update_doc, patch=profile_update_doc)
class ProfileAPIView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


@extend_schema_view(
    list=address_list_doc,
    create=address_create_doc,
    retrieve=address_detail_doc,
    update=address_update_doc,
    partial_update=address_partial_update_doc,
    destroy=address_delete_doc,
    set_default=address_set_default_doc,
)
class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer

    def get_queryset(self):
        client = client_profile_of(self.request.user)
        if client is None:
            return Address.objects.none()
        return client.addresses.order_by("-is_default", "-created")

    def perform_create(self, serializer):
        client = client_profile_of(self.request.user)
        if client is None:
            raise ValidationError({"detail": ["Seul un client peut créer une adresse."]})
        serializer.save(client=client)

    def perform_destroy(self, instance):
        instance.soft_delete()

    @action(detail=True, methods=["post"])
    def set_default(self, request, pk=None):
        address = self.get_object()
        address.is_default = True
        address.save()
        return Response(self.get_serializer(address).data)


class CategoryListAPIView(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = CategorySerializer
    queryset = Category.objects.all().order_by("display_order", "name")


class MealViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (permissions.AllowAny,)
    serializer_class = MealSerializer
    queryset = (
        Meal.objects.filter(is_available=True)
        .select_related("category")
        .prefetch_related("accompaniments", "daily_menus")
    )


class DailyMenuListAPIView(generics.ListAPIView):
    """Menus journaliers actifs : jour, libellé et plats du jour."""

    permission_classes = (permissions.AllowAny,)
    serializer_class = DailyMenuSerializer
    queryset = DailyMenu.objects.filter(is_active=True).prefetch_related(
        "meals__category", "meals__accompaniments", "meals__daily_menus"
    ).order_by("day")


class BoissonListAPIView(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = BoissonSerializer
    queryset = Boisson.objects.filter(is_available=True)


@extend_schema_view(list=order_list_doc, retrieve=order_detail_doc, create_order=order_create_doc)
class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        client = client_profile_of(self.request.user)
        if client is None:
            return Order.objects.none()
        return Order.objects.filter(client=client).select_related(
            "delivery_address", "client__user"
        ).prefetch_related(
            "items__meal__category", "items__meal__accompaniments", "items__order_item_accompaniments__accompaniment", "items__order_item_boissons__boisson"
        )

    @action(detail=False, methods=["post"])
    def create_order(self, request):
        cart = Cart(request)
        serializer = OrderCreateSerializer(
            data=request.data,
            context={"request": request, "cart": cart, "cart_items": list(cart)},
        )
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        return Response(OrderSerializer(order, context={"request": request}).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=custom_order_request_list_doc,
    retrieve=custom_order_request_detail_doc,
    create=custom_order_request_create_doc,
)
class CustomOrderRequestViewSet(viewsets.ModelViewSet):
    serializer_class = CustomOrderRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        client = client_profile_of(self.request.user)
        if client is None:
            return CustomOrderRequest.objects.none()
        return CustomOrderRequest.objects.filter(client=client)

    def perform_create(self, serializer):
        client = client_profile_of(self.request.user)
        if client is None:
            raise ValidationError({"detail": ["Seul un client peut faire une demande sur mesure."]})
        serializer.save(client=client)


class TestimonialAPIView(generics.GenericAPIView):
    serializer_class = TestimonialSerializer

    def get_object(self):
        client = client_profile_of(self.request.user)
        if client is None:
            return None
        return Testimonial.objects.filter(client=client).first()

    @testimonial_get_doc
    def get(self, request, *args, **kwargs):
        testimonial = self.get_object()
        return Response(self.get_serializer(testimonial).data if testimonial else None)

    @testimonial_update_doc
    def put(self, request, *args, **kwargs):
        client = client_profile_of(self.request.user)
        if client is None:
            raise ValidationError({"detail": ["Seul un client peut laisser un avis."]})
        testimonial = self.get_object()
        serializer = self.get_serializer(testimonial, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(client=client, status=TestimonialStatus.PENDING)
        return Response(serializer.data)


@extend_schema_view(post=newsletter_create_doc)
class NewsletterAPIView(generics.CreateAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = NewsletterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subscriber = NewsletterSubscriber.all_objects.filter(email=serializer.validated_data["email"]).first()
        if subscriber:
            if subscriber.is_deleted:
                subscriber.restore()
                return Response(status=status.HTTP_200_OK)
            return Response({"email": ["Cette adresse est déjà abonnée."]}, status=status.HTTP_400_BAD_REQUEST)
        try:
            serializer.save()
        except IntegrityError:
            return Response({"email": ["Cette adresse est déjà abonnée."]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
