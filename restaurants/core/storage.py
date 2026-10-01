"""Stockage Cloudinary exposant la ``secure_url`` réellement servie par Cloudinary."""

from __future__ import annotations

import logging

import cloudinary.api
from cloudinary.exceptions import NotFound
from cloudinary_storage.storage import MediaCloudinaryStorage
from django.core.cache import cache

logger = logging.getLogger(__name__)

FOUND_TTL = 7 * 24 * 3600
MISS_TTL = 5 * 60
MAX_EXTENSION_LENGTH = 8


class SecureUrlCloudinaryStorage(MediaCloudinaryStorage):
    """``MediaCloudinaryStorage`` dont ``url()`` retourne la vraie ``secure_url``.

    ``MediaCloudinaryStorage.url()`` se contente de composer une chaîne
    (préfixe ``MEDIA_URL`` + nom du champ) : l'URL est syntaxiquement valide
    même lorsque la ressource n'existe pas sur Cloudinary (fichier jamais
    téléversé, nom issu de l'ancien stockage fichier, ...) et retourne alors
    un 404.

    Ici l'URL provient des métadonnées renvoyées par l'API Cloudinary, mises en
    cache. Si la ressource est introuvable ou si l'API échoue, on retombe sur
    l'URL composée d'origine : aucun fichier ni aucune donnée n'est modifié.
    """

    def _upload(self, name, content):
        response = super()._upload(name, content)
        # La réponse d'upload contient déjà la secure_url : on alimente le cache.
        self._remember(response)
        return response

    def url(self, name: str) -> str:
        if not name:
            return ""
        # Une URL déjà complète (ancienne donnée) est telle quelle.
        if name.startswith(("http://", "https://")):
            return name
        try:
            secure_url = self._secure_url(self._public_id(name))
            if secure_url:
                return secure_url
            return super().url(name)
        except Exception:
            logger.exception("Cloudinary: impossible de construire l'URL de %s", name)
            return ""

    def _public_id(self, name: str) -> str:
        return self._prepend_prefix(self._normalise_name(name))

    def _secure_url(self, public_id: str) -> str | None:
        secure_url = self._lookup(public_id)
        if secure_url:
            return secure_url
        stem, dot, extension = public_id.rpartition(".")
        if (
            dot
            and stem
            and "/" not in extension
            and len(extension) <= MAX_EXTENSION_LENGTH
        ):
            # Cloudinary enregistre les images sans extension (use_filename) :
            # on réessaie le même identifiant dépouillé de son extension.
            return self._lookup(stem)
        return None

    def _lookup(self, public_id: str) -> str | None:
        cache_key = self._cache_key(public_id)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached or None
        try:
            resource = cloudinary.api.resource(
                public_id,
                type="upload",
                resource_type=self._get_resource_type(public_id),
            )
        except NotFound:
            logger.info("Cloudinary: ressource absente (%s)", public_id)
            cache.set(cache_key, "", MISS_TTL)
            return None
        except Exception:
            logger.exception(
                "Cloudinary: échec de lecture des métadonnées de %s",
                public_id,
            )
            cache.set(cache_key, "", MISS_TTL)
            return None
        self._remember(resource)
        return resource.get("secure_url") or None

    @classmethod
    def _remember(cls, resource) -> None:
        public_id = resource.get("public_id")
        secure_url = resource.get("secure_url")
        if public_id and secure_url:
            cache.set(cls._cache_key(public_id), secure_url, FOUND_TTL)

    @staticmethod
    def _cache_key(public_id: str) -> str:
        return f"cloudinary:secure_url:{public_id}"
