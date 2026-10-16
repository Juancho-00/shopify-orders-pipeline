"""
Pedido de Shopify → líneas planas para Siesa.

Cada fila es un producto (o el envío) de un pedido, y repite los datos del cliente y
del pedido. Ese formato "una fila por línea" es el que suelen usar las plantillas de
carga de pedidos del ERP.

Reglas principales (detalle en ``docs/mapeo_siesa.md``):

* Cliente: se toma de ``billing_address``; si falta, de ``shipping_address``; si falta,
  del cliente (``customer``).
* Cédula/NIT: viene en ``billing_address.company`` (respaldo: ``shipping_address.company``).
* Envío: si el valor cobrado es mayor a cero, se agrega una línea con la referencia
  configurada (por defecto ``ENVIO``).
* Solo pasan pedidos con pago confirmado. Los cancelados y de prueba se excluyen.
* Un pedido que ya salió en un reporte anterior no se repite (registro de reportados).
* Nada se descarta en silencio: las exclusiones, los datos faltantes o dudosos y los
  pedidos que no se pudieron transformar quedan como *eventos* en el log de alertas.
* Un pedido con datos malos no detiene la corrida: queda como ``ERROR_TRANSFORMACION``
  y los demás siguen.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from shopify_pipeline.exceptions import DataError
from shopify_pipeline.shopify.fulfillment import FULFILLMENT_KEY, location_by_line_item
from shopify_pipeline.transform.alertas import Evento
from shopify_pipeline.transform.normalize import (
    TWO_PLACES,
    clean_text,
    normalize_phone,
    parse_documento,
    split_apellidos,
    split_nombres,
    to_bogota,
    to_decimal,
)

if TYPE_CHECKING:
    from shopify_pipeline.state import Ledger

logger = logging.getLogger(__name__)

# Campos del pedido que usa esta transformación. Si se extrae con ``--fields``, la CLI
# los agrega siempre (salvo con ``--solo-raw``) para no generar un reporte incompleto.
CAMPOS_REQUERIDOS: tuple[str, ...] = (
    "id",
    "name",
    "order_number",
    "created_at",
    "updated_at",
    "processed_at",
    "financial_status",
    "cancelled_at",
    "cancel_reason",
    "test",
    "taxes_included",
    "current_total_price",
    "total_price",
    "billing_address",
    "shipping_address",
    "customer",
    "email",
    "contact_email",
    "phone",
    "line_items",
    "shipping_lines",
    "note",
    "note_attributes",
)

# Claves sin las cuales las exclusiones o los controles fallarían EN SILENCIO (p. ej. sin
# ``test`` un pedido de prueba pasaría al reporte). Shopify incluye la clave con ``null``
# cuando el campo se pidió; si la clave falta es porque se proyectó con ``--fields``.
CLAVES_CRITICAS: frozenset[str] = frozenset(
    {"id", "test", "cancelled_at", "financial_status", "line_items", "taxes_included"}
)

COLUMNS: tuple[str, ...] = (
    # Pedido
    "documento_referencia",
    "pedido_shopify",
    "id_pedido_shopify",
    "fecha_compra",
    "fecha_creacion",
    "estado_pago",
    # Cliente
    "tipo_documento",
    "numero_documento",
    "digito_verificacion",
    "primer_nombre",
    "segundo_nombre",
    "primer_apellido",
    "segundo_apellido",
    "direccion",
    "ciudad",
    "departamento",
    "codigo_postal",
    "pais",
    "telefono",
    "email",
    # Línea
    "numero_linea",
    "tipo_linea",
    "referencia",
    "descripcion",
    "id_bodega_shopify",
    "bodega",
    "cantidad",
    "precio_unitario",
    "descuento_linea",
    "valor_total_linea",
    "tasa_iva",
    "precio_incluye_iva",
    "notas",
)

NUMERIC_COLUMNS = frozenset(
    {"cantidad", "precio_unitario", "descuento_linea", "valor_total_linea", "tasa_iva"}
)

# Estados de pago de Shopify que cuentan como "pago confirmado".
#   paid               → pagado.
#   partially_refunded → pagado y con un reembolso parcial (las líneas reembolsadas
#                        completas ya salen con cantidad 0 y se omiten).
# Quedan fuera: pending (p. ej. contraentrega sin cobrar), authorized (autorizado sin
# capturar), partially_paid, refunded, voided y expired.
DEFAULT_ESTADOS_PAGO: frozenset[str] = frozenset({"paid", "partially_refunded"})


@dataclass(frozen=True)
class SiesaLinesOptions:
    codigo_envio: str = "ENVIO"
    estados_pago: frozenset[str] | None = DEFAULT_ESTADOS_PAGO  # None = no filtra por pago
    incluir_cancelados: bool = False
    incluir_pruebas: bool = False


@dataclass
class PedidoTransformado:
    rows: list[dict[str, Any]] = field(default_factory=list)
    eventos: list[Evento] = field(default_factory=list)

    @property
    def codigos(self) -> list[str]:
        return [e.codigo for e in self.eventos]


@dataclass
class TransformResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    eventos: list[Evento] = field(default_factory=list)
    pedidos_procesados: int = 0
    pedidos_excluidos: dict[str, int] = field(default_factory=dict)
    # (id del pedido, total) de los pedidos que salieron en el reporte: se registran en el
    # ledger solo después de escribir los archivos.
    reportados: list[tuple[int, str]] = field(default_factory=list)

    @property
    def errores(self) -> int:
        """Pedidos que no se pudieron transformar (dato malo o campos faltantes)."""
        return sum(self.pedidos_excluidos.get(c, 0) for c in ("ERROR_TRANSFORMACION", "DATOS_INCOMPLETOS"))

    @property
    def alertas(self) -> list[Evento]:
        return [e for e in self.eventos if e.tipo == "ALERTA"]

    @property
    def pedidos_con_alertas(self) -> int:
        return len({e.pedido_shopify for e in self.alertas})


# ------------------------------------------------------------------ helpers
def _first(*values: object) -> object:
    """Primer valor no vacío."""
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _tasa(tax_lines: list[dict[str, Any]] | None) -> Decimal:
    """Suma de las tasas de impuesto de la línea (0.19 para IVA general)."""
    total = sum((Decimal(str(t.get("rate") or 0)) for t in tax_lines or []), Decimal("0"))
    return total.quantize(Decimal("0.0001"))


def _descuento(item: dict[str, Any], cantidad: int) -> Decimal:
    """
    Descuento de la línea para la ``cantidad`` vigente.

    Shopify calcula ``discount_allocations`` sobre la cantidad ORIGINAL (``quantity``).
    Si después se reembolsaron unidades (``current_quantity`` menor), se prorratea: de lo
    contrario el descuento completo se restaría a menos unidades y la línea quedaría
    subvaluada.
    """
    allocations = item.get("discount_allocations") or []
    if allocations:
        total = sum((to_decimal(a.get("amount")) for a in allocations), Decimal("0.00"))
    else:
        total = to_decimal(item.get("total_discount"))
    original = item.get("quantity") or cantidad
    if 0 < cantidad < original:
        total = (total * cantidad / original).quantize(TWO_PLACES, ROUND_HALF_UP)
    return total


def _notas(order: dict[str, Any]) -> str:
    partes = [clean_text(order.get("note"))]
    for attr in order.get("note_attributes") or []:
        name, value = clean_text(attr.get("name")), clean_text(attr.get("value"))
        if name or value:
            partes.append(f"{name}: {value}")
    return " | ".join(p for p in partes if p)


def _cliente(order: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    billing = order.get("billing_address") or {}
    shipping = order.get("shipping_address") or {}
    customer = order.get("customer") or {}
    default = customer.get("default_address") or {}
    alertas: list[str] = []

    # Se usa una sola dirección completa (no se mezclan campos de varias).
    addr = billing or shipping or default

    first_name = _first(addr.get("first_name"), customer.get("first_name"))
    last_name = _first(addr.get("last_name"), customer.get("last_name"))
    primer_nombre, segundo_nombre = split_nombres(first_name)
    primer_apellido, segundo_apellido = split_apellidos(last_name)
    if not primer_nombre:
        alertas.append("SIN_NOMBRE")
    if not primer_apellido:
        alertas.append("SIN_APELLIDO")

    doc = parse_documento(_first(billing.get("company"), shipping.get("company"), default.get("company")))
    alertas.extend(doc.alertas)

    direccion = " ".join(p for p in (clean_text(addr.get("address1")), clean_text(addr.get("address2"))) if p)
    if not direccion:
        alertas.append("SIN_DIRECCION")

    telefono = normalize_phone(
        _first(
            billing.get("phone"),
            shipping.get("phone"),
            order.get("phone"),
            customer.get("phone"),
            default.get("phone"),
        )
    )
    if not telefono:
        alertas.append("SIN_TELEFONO")

    email = clean_text(_first(order.get("email"), order.get("contact_email"), customer.get("email")))
    if not email:
        alertas.append("SIN_EMAIL")

    datos = {
        "tipo_documento": doc.tipo,
        "numero_documento": doc.numero,
        "digito_verificacion": doc.dv,
        "primer_nombre": primer_nombre,
        "segundo_nombre": segundo_nombre,
        "primer_apellido": primer_apellido,
        "segundo_apellido": segundo_apellido,
        "direccion": direccion,
        "ciudad": clean_text(addr.get("city")),
        "departamento": clean_text(addr.get("province")),
        "codigo_postal": clean_text(addr.get("zip")),
        "pais": clean_text(addr.get("country_code")),
        "telefono": telefono,
        "email": email,
    }
    return datos, alertas


def _pedido_ids(order: dict[str, Any]) -> tuple[str, str]:
    return clean_text(order.get("name")), str(order.get("order_number") or "")


# --------------------------------------------------------------- principal
def order_to_lines(order: dict[str, Any], options: SiesaLinesOptions | None = None) -> PedidoTransformado:
    """Convierte un pedido en sus filas (productos + envío) y sus alertas."""
    options = options or SiesaLinesOptions()
    pedido, doc_ref = _pedido_ids(order)
    out = PedidoTransformado()

    def alerta(codigo: str, linea: int | None = None, referencia: str = "", detalle: str = "") -> None:
        out.eventos.append(Evento("ALERTA", codigo, pedido, doc_ref, linea, referencia, detalle))

    cliente, alertas_cliente = _cliente(order)
    for codigo in alertas_cliente:
        alerta(codigo)
    if order.get("cancelled_at"):
        alerta("PEDIDO_CANCELADO")

    base = {
        "documento_referencia": doc_ref,
        "pedido_shopify": pedido,
        "id_pedido_shopify": str(order.get("id") or ""),
        "fecha_compra": to_bogota(_first(order.get("processed_at"), order.get("created_at"))),
        "fecha_creacion": to_bogota(order.get("created_at")),
        "estado_pago": clean_text(order.get("financial_status")),
        **cliente,
        "precio_incluye_iva": "SI" if order.get("taxes_included") else "NO",
        "notas": _notas(order),
    }

    has_fulfillment = FULFILLMENT_KEY in order
    bodegas = location_by_line_item(order.get(FULFILLMENT_KEY) or [])

    for item in order.get("line_items") or []:
        cantidad = item.get("current_quantity")
        if cantidad is None:
            cantidad = item.get("quantity") or 0
        if cantidad <= 0:  # Línea eliminada del pedido o reembolsada por completo.
            continue

        numero_linea = len(out.rows) + 1
        referencia = clean_text(item.get("sku"))
        if not referencia:
            alerta("SIN_SKU", numero_linea, detalle=clean_text(item.get("name")))

        bodega_id, bodega = bodegas.get(item.get("id"), (None, ""))
        if not bodega:
            alerta("SIN_BODEGA" if has_fulfillment else "BODEGA_NO_CONSULTADA", numero_linea, referencia)

        precio = to_decimal(item.get("price"))
        descuento = _descuento(item, cantidad)
        out.rows.append(
            base
            | {
                "numero_linea": numero_linea,
                "tipo_linea": "PRODUCTO",
                "referencia": referencia,
                "descripcion": clean_text(item.get("name") or item.get("title")),
                "id_bodega_shopify": str(bodega_id or ""),
                "bodega": bodega,
                "cantidad": int(cantidad),
                "precio_unitario": precio,
                "descuento_linea": descuento,
                "valor_total_linea": (precio * cantidad - descuento).quantize(TWO_PLACES, ROUND_HALF_UP),
                "tasa_iva": _tasa(item.get("tax_lines")),
            }
        )

    for shipping in order.get("shipping_lines") or []:
        if shipping.get("is_removed"):
            continue
        # discounted_price = lo que realmente pagó el cliente por el envío.
        valor = to_decimal(_first(shipping.get("discounted_price"), shipping.get("price")))
        if valor <= 0:
            continue
        out.rows.append(
            base
            | {
                "numero_linea": len(out.rows) + 1,
                "tipo_linea": "ENVIO",
                "referencia": options.codigo_envio,
                "descripcion": clean_text(shipping.get("title")) or "Envío",
                "id_bodega_shopify": "",
                "bodega": "",
                "cantidad": 1,
                "precio_unitario": valor,
                "descuento_linea": Decimal("0.00"),
                "valor_total_linea": valor,
                "tasa_iva": _tasa(shipping.get("tax_lines")),
            }
        )

    diferencia = _diferencia_total(order, out.rows)
    if diferencia:
        alerta("TOTAL_NO_CUADRA", detalle=diferencia)
    return out


def _diferencia_total(order: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """
    Control de calidad: con precios IVA incluido, la suma de las líneas debe ser igual al
    total del pedido en Shopify (tolerancia de $1). Devuelve el detalle si no cuadra.
    """
    if not rows or not order.get("taxes_included"):
        return ""
    total_shopify = to_decimal(_first(order.get("current_total_price"), order.get("total_price")))
    total_lineas = sum((r["valor_total_linea"] for r in rows), Decimal("0.00"))
    if abs(total_shopify - total_lineas) <= Decimal("1.00"):
        return ""
    return f"Shopify {total_shopify} vs líneas {total_lineas}"


def validar_contrato(order: dict[str, Any]) -> None:
    """Falla si al pedido le faltan claves sin las cuales el resultado sería incorrecto."""
    faltan = CLAVES_CRITICAS - order.keys()
    if faltan:
        raise DataError(f"faltan campos {sorted(faltan)} (¿extracción con --fields?)")


def total_pedido(order: dict[str, Any]) -> str:
    """Total vigente del pedido (tras reembolsos), como texto con 2 decimales."""
    return str(to_decimal(_first(order.get("current_total_price"), order.get("total_price"))))


def _motivo_exclusion(order: dict[str, Any], options: SiesaLinesOptions) -> tuple[str, str] | None:
    if order.get("test") and not options.incluir_pruebas:
        return "PRUEBA", ""
    if order.get("cancelled_at") and not options.incluir_cancelados:
        return "CANCELADO", clean_text(order.get("cancel_reason"))
    estado = clean_text(order.get("financial_status"))
    if options.estados_pago is not None and estado not in options.estados_pago:
        return "PAGO_NO_CONFIRMADO", f"estado_pago={estado or 'vacío'}"
    return None


def va_al_reporte(order: dict[str, Any], options: SiesaLinesOptions, ledger: Ledger | None = None) -> bool:
    """
    ¿El pedido saldrá en el reporte Siesa de una corrida NUEVA? Se usa antes de consultar
    la bodega para no gastar una llamada a Shopify en pedidos que se van a excluir.
    Ante la duda (p. ej. faltan claves), responde True: mejor una llamada de más que una
    línea sin bodega.
    """
    if CLAVES_CRITICAS - order.keys():
        return True
    if _motivo_exclusion(order, options) is not None:
        return False
    return ledger is None or ledger.get(order["id"]) is None


def _motivo_ledger(order: dict[str, Any], ledger: Ledger, run_id: str) -> tuple[str, str] | None:
    """
    ¿El pedido ya salió en el reporte de OTRA corrida? Con ventanas solapadas (modo
    incremental) un pedido aparece en varias extracciones; aquí se evita duplicarlo.
    Regenerar el reporte de la misma corrida (``transform``) no lo excluye.
    """
    previo = ledger.get(order["id"])
    if previo is None or previo.run_id == run_id:
        return None
    total = total_pedido(order)
    if total == previo.total:
        return "YA_REPORTADO", f"run={previo.run_id}"
    return "CAMBIO_POST_REPORTE", f"total {previo.total} → {total} (run={previo.run_id})"


def transform_orders(
    orders: Iterable[dict[str, Any]],
    options: SiesaLinesOptions | None = None,
    ledger: Ledger | None = None,
    run_id: str = "",
) -> TransformResult:
    """
    Transforma los pedidos, aplica las exclusiones y acumula los eventos para el log.

    ``ledger`` (opcional) es el registro de pedidos ya reportados en corridas anteriores.
    """
    options = options or SiesaLinesOptions()
    result = TransformResult()

    def excluir(order: dict[str, Any], codigo: str, detalle: str) -> None:
        pedido, doc_ref = _pedido_ids(order)
        result.eventos.append(Evento("EXCLUIDO", codigo, pedido, doc_ref, detalle=detalle))
        result.pedidos_excluidos[codigo] = result.pedidos_excluidos.get(codigo, 0) + 1

    for order in orders:
        # Cada pedido se procesa aislado: un dato malo (monto o fecha con formato raro,
        # estructura inesperada) excluye ESE pedido y queda en el log; los demás siguen.
        try:
            validar_contrato(order)
            motivo = _motivo_exclusion(order, options)
            if motivo is None and ledger is not None:
                motivo = _motivo_ledger(order, ledger, run_id)
            if motivo:
                excluir(order, *motivo)
                continue
            transformado = order_to_lines(order, options)
            total = total_pedido(order)
        except DataError as exc:
            excluir(order, "DATOS_INCOMPLETOS", str(exc))
            continue
        except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as exc:
            logger.exception("No se pudo transformar el pedido %s", clean_text(order.get("name")))
            excluir(order, "ERROR_TRANSFORMACION", f"{type(exc).__name__}: {exc}"[:300])
            continue
        result.rows.extend(transformado.rows)
        result.eventos.extend(transformado.eventos)
        result.pedidos_procesados += 1
        if transformado.rows:
            result.reportados.append((order["id"], total))
    return result
