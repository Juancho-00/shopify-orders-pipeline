"""
Validación de esquema de las filas del reporte Siesa, ANTES de escribirlas.

QUÉ VALIDA
    Tipos y reglas estructurales que, si fallan, indican un dato corrupto o un bug, no un
    dato de negocio faltante:

    * Todas las columnas del reporte están presentes y los textos son ``str`` (nunca ``None``).
    * Llaves del pedido no vacías: ``documento_referencia``, ``pedido_shopify``,
      ``id_pedido_shopify`` (solo dígitos), ``fecha_compra`` (``AAAA-MM-DD HH:MM:SS``).
    * ``tipo_linea`` es ``PRODUCTO`` o ``ENVIO``; ``numero_linea`` y ``cantidad`` son
      enteros positivos.
    * Montos ``Decimal`` no negativos y consistentes: ``valor_total_linea`` =
      ``precio_neto × cantidad``. ``tasa_iva`` entre 0 y 1.

QUÉ NO VALIDA (y por qué)
    Datos de negocio que pueden faltar (SKU, cédula, dirección...) siguen siendo ALERTAS:
    el pedido sale en el reporte para que alguien lo revise, y la fase 3 no lo carga a
    Siesa si le falta un obligatorio (R-34). Exigirlos aquí lo sacaría del reporte de
    revisión y cambiaría esa regla.

POR PEDIDO, NUNCA POR FILA
    Si una sola fila falla, se excluye el pedido COMPLETO (``ESQUEMA_INVALIDO``): cargar a
    Siesa un pedido con parte de sus líneas es peor que no cargarlo.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
MAX_ERRORES_DETALLE = 5  # Errores que se listan en el log por pedido (el resto se resume).


def _entero(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class Regla:
    tipo: Callable[[Any], bool]
    condicion: Callable[[Any], bool] | None = None
    descripcion: str = ""


_NO_VACIO = Regla(lambda v: isinstance(v, str), lambda v: bool(v.strip()), "texto no vacío")
_MONTO = Regla(lambda v: isinstance(v, Decimal), lambda v: v >= 0, "Decimal ≥ 0")

# Columnas con regla propia. El resto de columnas del reporte solo debe ser texto (puede ir vacío).
ESQUEMA: dict[str, Regla] = {
    "documento_referencia": _NO_VACIO,
    "pedido_shopify": _NO_VACIO,
    "id_pedido_shopify": Regla(lambda v: isinstance(v, str), str.isdigit, "solo dígitos"),
    "fecha_compra": Regla(
        lambda v: isinstance(v, str), lambda v: bool(_FECHA.match(v)), "AAAA-MM-DD HH:MM:SS"
    ),
    "tipo_linea": Regla(
        lambda v: isinstance(v, str), lambda v: v in {"PRODUCTO", "ENVIO"}, "PRODUCTO o ENVIO"
    ),
    "numero_linea": Regla(_entero, lambda v: v >= 1, "entero ≥ 1"),
    "cantidad": Regla(_entero, lambda v: v > 0, "entero > 0"),
    "precio_unitario": _MONTO,
    "descuento_linea": _MONTO,
    "precio_neto": _MONTO,
    "valor_total_linea": _MONTO,
    "tasa_iva": Regla(lambda v: isinstance(v, Decimal), lambda v: 0 <= v <= 1, "Decimal entre 0 y 1"),
}
_TEXTO = Regla(lambda v: isinstance(v, str), None, "texto")


def errores_de_fila(fila: dict[str, Any], columnas: Iterable[str]) -> list[str]:
    """Reglas que incumple una fila: ``["cantidad: entero > 0", ...]``. Vacía = válida."""
    errores: list[str] = []
    for col in columnas:
        if col not in fila:
            errores.append(f"{col}: falta la columna")
            continue
        regla = ESQUEMA.get(col, _TEXTO)
        valor = fila[col]
        if not regla.tipo(valor) or (regla.condicion is not None and not regla.condicion(valor)):
            errores.append(f"{col}: {regla.descripcion} (tipo {type(valor).__name__})")
    if not errores and fila["precio_neto"] * fila["cantidad"] != fila["valor_total_linea"]:
        errores.append("valor_total_linea: distinto de precio_neto × cantidad")
    return errores


def validar_pedido(filas: list[dict[str, Any]], columnas: Iterable[str]) -> list[str]:
    """
    Errores de esquema de TODAS las filas de un pedido, con su número de línea.
    El detalle nunca incluye el valor del dato (puede ser personal): solo campo, regla y tipo.
    """
    columnas = tuple(columnas)
    errores = [
        f"línea {fila.get('numero_linea', '?')}: {error}"
        for fila in filas
        for error in errores_de_fila(fila, columnas)
    ]
    if len(errores) > MAX_ERRORES_DETALLE:
        resto = len(errores) - MAX_ERRORES_DETALLE
        errores = [*errores[:MAX_ERRORES_DETALLE], f"(+{resto} más)"]
    return errores
