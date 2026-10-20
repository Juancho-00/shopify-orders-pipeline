"""
Fase 3 · Plantilla de pedidos: hojas ``Pedidos`` (encabezado) y ``Movto Pedidos comercial``
(detalle). Definidas por TI el 2026-10-20.

``Pedidos`` es el encabezado del documento: una fila por pedido de Shopify.
``Movto Pedidos comercial`` es el detalle: una fila por producto, más la del envío si se
cobró (``SERV01``). Las une el par ``_id_tipo_docto`` + ``_consec_docto``.

TIPO DE DOCUMENTO
    Sale de la bodega de salida (``catalogos/bodegas_siesa.csv``): CEDI Guarne → ``CPW``,
    tiendas → ``CPT``, Melonn → ``CPM``. Los pedidos de las bodegas de vending no se cargan
    a Siesa (``NO_CARGA``). Según TI no hay pedidos con productos de bodegas de tipos
    distintos; si llegara uno, queda en el log como control (``PEDIDO_BODEGAS_MIXTAS``).

NOTAS
    El campo ``_notas`` de Siesa admite 500 caracteres: lo que sobre se corta y el pedido
    queda con la alerta ``NOTAS_RECORTADAS``.

CONSECUTIVO
    Empieza en 1 y se reinicia por cada tipo de documento. Los pedidos van por bloques:
    primero los ``CPW``, luego los ``CPT`` y al final los ``CPM`` (y dentro de cada bloque,
    por fecha de compra).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from shopify_pipeline.transform.catalogos import NO_CARGA, tipo_docto_bodega

PEDIDOS_COLUMNS: tuple[str, ...] = (
    "_id_co",
    "_id_tipo_docto",
    "_consec_docto",
    "_id_fecha(AAAAMMDD)",
    "_ind_backorder",
    "_id_tercero_fact",
    "_id_sucursal_fact",
    "_id_tercero_rem",
    "_id_sucursal_rem",
    "_id_co_fact",
    "_fecha_entrega(AAAAMMDD)",
    "_num_docto_referencia",
    "_id_cond_pago",
    "_notas",
    "_id_punto_envio",
    "_id_tercero_vendedor",
)

MOVTO_COLUMNS: tuple[str, ...] = (
    "_id_co",
    "_id_tipo_docto",
    "_consec_docto",
    "_nro_registro",
    "_referencia_item",
    "_id_ext1_COLOR",
    "_id_ext2_TALLA",
    "_id_bodega",
    "_id_motivo",
    "_ind_obsequio(0=No, 1=Si)",
    "_id_co_movto",
    "ccosto_movto",
    "_fecha_entrega(AAAAMMDD)",
    "_id_lista_precio",
    "_id_unidad_medida",
    "_cant_pedida_base",
    "_precio_unitario",
    "_ind_impto_asumidoDebe ser 0=No liquida; 1=Asume compañía, 2=Asume cliente.)",
    "ind_precio (0=Reliquida precio con lista de precio del cliente 1=Liquida precio con lista de "
    "precio del registro 2=Liquida con precio del registro.)",
)

# Orden de los bloques en el archivo (el consecutivo se reinicia en cada uno).
ORDEN_TIPOS: tuple[str, ...] = ("CPW", "CPT", "CPM")

CO = "001"
LARGO_NOTAS = 500  # Límite del campo _notas en Siesa.
SUCURSAL = "001"

FIJOS_PEDIDO: dict[str, str] = {
    "_id_co": CO,
    "_ind_backorder": "4",
    "_id_sucursal_fact": SUCURSAL,
    "_id_sucursal_rem": SUCURSAL,
    "_id_co_fact": CO,
    "_id_cond_pago": "03D",
    "_id_punto_envio": "000",
    "_id_tercero_vendedor": "900733097",
}

FIJOS_MOVTO: dict[str, str] = {
    "_id_co": CO,
    "_id_ext1_COLOR": "",
    "_id_ext2_TALLA": "",
    "_id_motivo": "06",
    "_ind_obsequio(0=No, 1=Si)": "0",
    "_id_co_movto": CO,
    "ccosto_movto": "",
    "_id_lista_precio": "03",
    "_id_unidad_medida": "UND",
    MOVTO_COLUMNS[17]: "0",  # _ind_impto_asumido: no liquida
    MOVTO_COLUMNS[18]: "2",  # ind_precio: liquida con el precio del registro
}


@dataclass(frozen=True)
class Validacion:
    tipo_docto: str
    motivo: str = ""  # Código de exclusión; vacío = el pedido se puede cargar.
    detalle: str = ""

    @property
    def cargable(self) -> bool:
        return not self.motivo


def _entero(valor: str) -> str:
    """``"89999"`` / ``"89999.00"`` → ``"89999"``; ``""`` si no es un entero válido."""
    try:
        numero = Decimal(valor or "")
    except InvalidOperation:
        return ""
    return str(int(numero)) if numero == numero.to_integral_value() else ""


def validar_pedido(lineas: list[dict[str, str]]) -> Validacion:
    """Revisa que el pedido tenga lo que exige la plantilla (R-34) y define su tipo de documento."""
    faltantes: list[str] = []
    for i, linea in enumerate(lineas, start=1):
        for campo in ("referencia", "bodega_siesa"):
            if not (linea.get(campo) or "").strip():
                faltantes.append(f"{campo} (línea {i})")
        if not _entero(linea.get("cantidad", "")) or _entero(linea.get("cantidad", "")) == "0":
            faltantes.append(f"cantidad (línea {i})")
        if not _entero(linea.get("precio_neto", "")):
            faltantes.append(f"precio_neto (línea {i})")
    if faltantes:
        return Validacion("", "PEDIDO_INCOMPLETO", "falta: " + ", ".join(faltantes))

    productos = [lin for lin in lineas if lin.get("tipo_linea") != "ENVIO"] or lineas
    bodegas = sorted({lin["bodega_siesa"].strip().upper() for lin in productos})
    tipos = {tipo_docto_bodega(b) for b in bodegas}
    if NO_CARGA in tipos:  # Vending: sus pedidos no van a Siesa. No es un error.
        vending = [b for b in bodegas if tipo_docto_bodega(b) == NO_CARGA]
        return Validacion("", "BODEGA_NO_SE_CARGA", "bodega " + ", ".join(vending))
    if "" in tipos:
        sin_tipo = [b for b in bodegas if not tipo_docto_bodega(b)]
        return Validacion("", "TIPO_DOCTO_SIN_EQUIVALENCIA", "bodega " + ", ".join(sin_tipo))
    if len(tipos) > 1:
        return Validacion(
            "", "PEDIDO_BODEGAS_MIXTAS", " / ".join(f"{b}={tipo_docto_bodega(b)}" for b in bodegas)
        )
    return Validacion(tipos.pop())


def numerar(pedidos: list[tuple[str, list[dict[str, str]]]]) -> list[tuple[str, int, list[dict[str, str]]]]:
    """
    Asigna el consecutivo: por bloques CPW → CPT → CPM, desde 1 en cada bloque, y dentro de
    cada bloque por fecha de compra. Recibe ``(tipo_docto, líneas)`` por pedido.
    """

    def clave(item: tuple[str, list[dict[str, str]]]) -> tuple[int, str, str]:
        tipo, lineas = item
        bloque = ORDEN_TIPOS.index(tipo) if tipo in ORDEN_TIPOS else len(ORDEN_TIPOS)
        return bloque, lineas[0].get("fecha_compra", ""), lineas[0].get("documento_referencia", "")

    numerados: list[tuple[str, int, list[dict[str, str]]]] = []
    consecutivos: dict[str, int] = {}
    for tipo, lineas in sorted(pedidos, key=clave):
        consecutivos[tipo] = consecutivos.get(tipo, 0) + 1
        numerados.append((tipo, consecutivos[tipo], lineas))
    return numerados


def fila_pedido(
    lineas: list[dict[str, str]], tipo: str, consec: int, fecha: str, documento: str
) -> dict[str, str]:
    """Encabezado (hoja ``Pedidos``). ``documento`` es el del tercero (``F200_ID``)."""
    primera = lineas[0]
    fila = {
        **FIJOS_PEDIDO,
        "_id_tipo_docto": tipo,
        "_consec_docto": str(consec),
        "_id_fecha(AAAAMMDD)": fecha,
        "_id_tercero_fact": documento,
        "_id_tercero_rem": documento,
        "_fecha_entrega(AAAAMMDD)": fecha,
        "_num_docto_referencia": (primera.get("documento_referencia") or "").strip(),
        "_notas": (primera.get("notas") or "").strip()[:LARGO_NOTAS],
    }
    return {col: fila[col] for col in PEDIDOS_COLUMNS}


def filas_movimiento(
    lineas: list[dict[str, str]], tipo: str, consec: int, fecha: str
) -> list[dict[str, str]]:
    """Detalle (hoja ``Movto Pedidos comercial``): una fila por línea, numeradas desde 1."""
    filas = []
    for nro, linea in enumerate(lineas, start=1):
        fila = {
            **FIJOS_MOVTO,
            "_id_tipo_docto": tipo,
            "_consec_docto": str(consec),
            "_nro_registro": str(nro),
            "_referencia_item": linea["referencia"].strip(),
            "_id_bodega": linea["bodega_siesa"].strip().upper(),
            "_fecha_entrega(AAAAMMDD)": fecha,
            "_cant_pedida_base": _entero(linea["cantidad"]),
            # Precio neto: el que pagó el cliente, con el descuento aplicado (R-13).
            "_precio_unitario": _entero(linea["precio_neto"]),
        }
        filas.append({col: fila[col] for col in MOVTO_COLUMNS})
    return filas
