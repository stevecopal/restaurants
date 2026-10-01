"""Documentation Swagger des endpoints publics du menu."""

from drf_spectacular.utils import OpenApiResponse, extend_schema


MENU_TAG = "Menu public"

category_list_doc = extend_schema(
    tags=[MENU_TAG],
    summary="Lister les catégories",
    description="Retourne les catégories du menu, dans leur ordre d'affichage.",
    responses={200: OpenApiResponse(description="Liste des catégories du menu.")},
)

meal_list_doc = extend_schema(
    tags=[MENU_TAG],
    summary="Lister les plats disponibles",
    description="Retourne uniquement les plats actuellement disponibles à la commande.",
    responses={200: OpenApiResponse(description="Liste des plats disponibles.")},
)

meal_detail_doc = extend_schema(
    tags=[MENU_TAG],
    summary="Consulter un plat",
    description="Retourne le détail d'un plat disponible, avec sa catégorie et ses accompagnements.",
    responses={200: OpenApiResponse(description="Détail du plat."), 404: OpenApiResponse(description="Plat introuvable.")},
)

boisson_list_doc = extend_schema(
    tags=[MENU_TAG],
    summary="Lister les boissons disponibles",
    description="Retourne uniquement les boissons disponibles à la commande.",
    responses={200: OpenApiResponse(description="Liste des boissons disponibles.")},
)

daily_menu_list_doc = extend_schema(
    tags=[MENU_TAG],
    summary="Lister les menus journaliers",
    description=(
        "Retourne les menus actifs de la semaine (jour, libellé et plats "
        "du jour). Le champ ``days`` de ``/api/v1/meals/`` donne le même "
        "information plat par plat."
    ),
    responses={200: OpenApiResponse(description="Liste des menus journaliers actifs.")},
)
