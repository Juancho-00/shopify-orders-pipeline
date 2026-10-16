"""
Configuración del pipeline.

Todos los secretos se leen de variables de entorno (o de un archivo ``.env`` local
que NUNCA se versiona). Ningún valor sensible debe quedar escrito en el código.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from shopify_pipeline.exceptions import ConfigError

DEFAULT_API_VERSION = "2026-10"  # Última versión estable (oct-2026). Revisar cada trimestre.


def load_env_file(path: str | Path | None = None) -> None:
    """Carga ``.env`` si python-dotenv está instalado. No sobrescribe variables ya definidas."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dependencia opcional
        return
    load_dotenv(dotenv_path=path, override=False)


@dataclass(frozen=True)
class ShopifyConfig:
    """Configuración de conexión a Shopify. Los secretos se excluyen de ``repr``."""

    shop_domain: str
    api_version: str = DEFAULT_API_VERSION
    access_token: str | None = field(default=None, repr=False)
    client_id: str | None = field(default=None, repr=False)
    client_secret: str | None = field(default=None, repr=False)
    connect_timeout: float = 10.0
    read_timeout: float = 60.0
    max_attempts: int = 6
    throttle_threshold: float = 0.8  # Fracción del bucket a partir de la cual se pausa.

    def __post_init__(self) -> None:
        domain = self.shop_domain.strip().lower()
        domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        if not domain.endswith(".myshopify.com"):
            raise ConfigError(
                "SHOPIFY_SHOP_DOMAIN debe ser el dominio interno 'tienda.myshopify.com', "
                "no el dominio público de la tienda."
            )
        object.__setattr__(self, "shop_domain", domain)
        if not self.access_token and not (self.client_id and self.client_secret):
            raise ConfigError(
                "Faltan credenciales: defina SHOPIFY_ACCESS_TOKEN, o bien "
                "SHOPIFY_CLIENT_ID y SHOPIFY_CLIENT_SECRET."
            )
        if not 0 < self.throttle_threshold <= 1:
            raise ConfigError("throttle_threshold debe estar en (0, 1].")

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.connect_timeout, self.read_timeout)

    @classmethod
    def from_env(cls) -> ShopifyConfig:
        """Construye la configuración desde variables de entorno."""
        domain = os.environ.get("SHOPIFY_SHOP_DOMAIN")
        if not domain:
            raise ConfigError("Variable de entorno SHOPIFY_SHOP_DOMAIN no definida.")
        return cls(
            shop_domain=domain,
            api_version=os.environ.get("SHOPIFY_API_VERSION") or DEFAULT_API_VERSION,
            access_token=os.environ.get("SHOPIFY_ACCESS_TOKEN") or None,
            client_id=os.environ.get("SHOPIFY_CLIENT_ID") or None,
            client_secret=os.environ.get("SHOPIFY_CLIENT_SECRET") or None,
        )
