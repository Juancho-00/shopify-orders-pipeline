"""Jerarquía de excepciones del pipeline."""

from __future__ import annotations


class PipelineError(Exception):
    """Error base de todo el pipeline."""


# --------------------------------------------------------------------- Shopify
class ShopifyError(PipelineError):
    """Error base de la integración con Shopify."""


class ShopifyAuthError(ShopifyError):
    """401: token ausente, inválido, revocado o expirado."""


class ShopifyPermissionError(ShopifyError):
    """403: el token no tiene el scope requerido (read_orders / read_all_orders)."""


class ShopifyNotFoundError(ShopifyError):
    """404: dominio de tienda, versión de API o recurso inexistente."""


class ShopifyClientError(ShopifyError):
    """Otros 4xx no recuperables (400, 402, 406, 422, 423...)."""


class ShopifyRetryableError(ShopifyError):
    """429 / 5xx: error transitorio; se reintenta."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# Errores que indican un problema de configuración (no se resuelven reintentando).
CONFIGURATION_ERRORS: tuple[type[Exception], ...] = (
    ShopifyAuthError,
    ShopifyPermissionError,
    ShopifyNotFoundError,
    ValueError,
)
