"""
Catálogo de alertas y exclusiones que se escriben en el log ``alertas_<run_id>.csv``.

QUÉ HACE
    Define qué es un "evento" (una alerta o un pedido excluido), la lista de códigos
    posibles con su explicación, y las columnas del archivo de log.

POR QUÉ ESTÁ APARTE
    La transformación (``siesa_lines.py``) solo decide *cuándo* ocurre una alerta.
    Aquí se define *qué significa*. Para agregar una alerta nueva: se agrega el código
    y su descripción en ``DESCRIPCIONES`` y se dispara desde ``siesa_lines.py``.

PRIVACIDAD
    Un evento nunca guarda datos personales del cliente (nombre, cédula, teléfono,
    dirección): solo el número de pedido, la línea, la referencia y un detalle técnico.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Catálogo de eventos que van al log de alertas.
DESCRIPCIONES: dict[str, str] = {
    # Alertas de cliente (una por pedido)
    "SIN_DOCUMENTO": "El cliente no registró cédula/NIT en el campo company",
    "DOCUMENTO_INVALIDO": "El documento no tiene entre 5 y 11 dígitos",
    "DV_NIT_INVALIDO": "El dígito de verificación escrito no coincide con el calculado",
    "NIT_POR_VERIFICAR": "Clasificado como NIT solo por formato (9 dígitos que inician en 8 o 9)",
    "SIN_NOMBRE": "Pedido sin nombre del cliente",
    "SIN_APELLIDO": "Pedido sin apellido del cliente",
    "SIN_DIRECCION": "Pedido sin dirección",
    "SIN_TELEFONO": "Pedido sin teléfono",
    "SIN_EMAIL": "Pedido sin email",
    # Alertas de pedido
    "TOTAL_NO_CUADRA": "La suma de las líneas no coincide con el total del pedido en Shopify",
    "PEDIDO_CANCELADO": "Pedido cancelado incluido por --incluir-cancelados",
    # Alertas de línea
    "SIN_SKU": "Producto sin referencia (SKU)",
    "SIN_BODEGA": "Shopify no tiene la línea asignada a una bodega",
    "BODEGA_NO_CONSULTADA": "No se consultó la bodega (--sin-bodega o falta de permiso)",
    # Exclusiones
    "PAGO_NO_CONFIRMADO": "Excluido: el pago no está confirmado",
    "CANCELADO": "Excluido: pedido cancelado",
    "PRUEBA": "Excluido: pedido de prueba",
    "YA_REPORTADO": "Excluido: el pedido ya salió en el reporte de una corrida anterior",
    "CAMBIO_POST_REPORTE": "Excluido: ya se reportó, pero su total cambió después (revisar en Siesa)",
    "DATOS_INCOMPLETOS": "Excluido: al pedido le faltan campos necesarios (¿extracción con --fields?)",
    "ERROR_TRANSFORMACION": "Excluido: error inesperado al transformar el pedido (ver bitácora)",
}

EVENT_COLUMNS: tuple[str, ...] = (
    "tipo",
    "codigo",
    "descripcion",
    "pedido_shopify",
    "documento_referencia",
    "numero_linea",
    "referencia",
    "detalle",
)


@dataclass(frozen=True)
class Evento:
    """Una alerta o una exclusión. No incluye datos personales del cliente."""

    tipo: str  # "ALERTA" o "EXCLUIDO"
    codigo: str
    pedido_shopify: str
    documento_referencia: str
    numero_linea: int | None = None
    referencia: str = ""
    detalle: str = ""

    def as_row(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "codigo": self.codigo,
            "descripcion": DESCRIPCIONES.get(self.codigo, ""),
            "pedido_shopify": self.pedido_shopify,
            "documento_referencia": self.documento_referencia,
            "numero_linea": "" if self.numero_linea is None else self.numero_linea,
            "referencia": self.referencia,
            "detalle": self.detalle,
        }
