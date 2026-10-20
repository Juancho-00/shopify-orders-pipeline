"""Jerarquía de excepciones del pipeline."""

from __future__ import annotations


class PipelineError(Exception):
    """Error base de todo el pipeline."""


class ConfigError(PipelineError, ValueError):
    """
    Configuración o argumentos inválidos (``.env`` incompleto, ventana de fechas mal
    armada, carpeta sin extracciones...). Reintentar no sirve: hay que corregir algo.

    Hereda de ``ValueError`` para que el código que ya capturaba ``ValueError`` siga
    funcionando.
    """


class DataError(PipelineError):
    """
    Los datos de entrada no sirven para continuar: archivo JSONL corrupto, extracción
    hecha con ``--fields`` sin los campos que necesita la transformación, etc.
    """


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


class ShopifyCostoExcedidoError(ShopifyClientError):
    """GraphQL: la consulta supera el costo máximo por petición (1.000 puntos). Se achica la página."""


class ShopifyRetryableError(ShopifyError):
    """429 / 5xx: error transitorio; se reintenta."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# Errores que indican un problema de configuración (no se resuelven reintentando).
# Un ValueError genérico NO está aquí: casi siempre es un dato malo o un bug, no el .env.
CONFIGURATION_ERRORS: tuple[type[Exception], ...] = (
    ShopifyAuthError,
    ShopifyPermissionError,
    ShopifyNotFoundError,
    ConfigError,
)
