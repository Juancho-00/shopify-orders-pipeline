"""
Fase 2: conciliación de pedidos reportados (Shopify) contra el exporte de Siesa.

QUÉ HACE
    1. Lee los reportes oficiales que generó la fase 1 (``pedidos_siesa_<run_id>.csv``;
       los ``*_revision`` no cuentan porque no se cargan a Siesa).
    2. Lee el exporte de pedidos de Siesa (``data/siesa/exportes/``, el más reciente).
    3. Por cada pedido reportado verifica que su número exista en Siesa en el campo
       ``_num_docto_referencia`` (R-21, R-22). No compara valores: Siesa no maneja
       decimales y los precios ya se enviaron netos (R-13, R-23).

SALIDA
    data/reconciliation/conciliacion_<AAAAMMDDTHHMMSS>.csv / .xlsx
        Un renglón por pedido con estado EN_SIESA, FALTA_EN_SIESA o NO_SE_CARGA (pedidos
        de bodegas de vending, que no van a Siesa: no se buscan ni cuentan como faltantes).

    Además se avisa en la bitácora si una referencia aparece más de una vez en Siesa
    (no debería pasar: el permiso del usuario de Siesa lo impide, R-35).
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from shopify_pipeline.reconciliation.siesa_export import ExporteSiesa, leer_exporte
from shopify_pipeline.sinks.tabular import write_csv, write_xlsx
from shopify_pipeline.transform.catalogos import bodega_no_se_carga
from shopify_pipeline.transform.normalize import BOGOTA

logger = logging.getLogger(__name__)

DEFAULT_EXPORTES_DIR = Path("data/siesa/exportes")
DEFAULT_RECONCILIATION_DIR = Path("data/reconciliation")

EN_SIESA, FALTA_EN_SIESA, NO_SE_CARGA = "EN_SIESA", "FALTA_EN_SIESA", "NO_SE_CARGA"
_ORDEN_ESTADOS = {FALTA_EN_SIESA: 0, EN_SIESA: 1, NO_SE_CARGA: 2}  # Lo que hay que revisar, primero.

COLUMNAS = (
    "estado",
    "documento_referencia",
    "documento_siesa",
    "pedido_shopify",
    "fecha_compra",
    "cliente",
    "numero_documento",
    "lineas",
    "valor_total",
    "reporte_origen",
)
COLUMNAS_NUMERICAS = frozenset({"lineas", "valor_total"})


@dataclass(frozen=True)
class Conciliacion:
    filas: list[dict[str, object]]
    exporte: ExporteSiesa
    csv_file: Path
    xlsx_file: Path

    @property
    def faltantes(self) -> int:
        return sum(1 for f in self.filas if f["estado"] == FALTA_EN_SIESA)


@dataclass
class _Pedido:
    documento_referencia: str
    pedido_shopify: str
    fecha_compra: str
    cliente: str
    numero_documento: str
    reporte_origen: str
    lineas: int = 0
    valor_total: Decimal = Decimal("0")
    vending: bool = False  # Sale de una bodega que no se carga a Siesa.


def _reportes(processed_dir: Path) -> Iterator[Path]:
    for path in sorted(processed_dir.glob("pedidos_siesa_*.csv")):
        if not path.stem.endswith("_revision"):
            yield path


def _decimal(valor: str) -> Decimal:
    try:
        return Decimal(valor or "0")
    except InvalidOperation:
        return Decimal("0")


def pedidos_reportados(processed_dir: Path, desde: date | None = None) -> dict[str, dict[str, object]]:
    """
    Pedidos de los reportes oficiales, agrupados por ``documento_referencia``.

    Si un pedido aparece en varios reportes (p. ej. se regeneró una corrida), se conserva
    el reporte más reciente.
    """
    pedidos: dict[str, dict[str, object]] = {}
    for path in _reportes(processed_dir):
        actuales: dict[str, _Pedido] = {}
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                ref = (row.get("documento_referencia") or "").strip()
                fecha = row.get("fecha_compra") or ""
                if not ref or (desde and fecha[:10] < desde.isoformat()):
                    continue
                pedido = actuales.get(ref)
                if pedido is None:
                    nombre = (row.get("primer_nombre"), row.get("primer_apellido"))
                    pedido = actuales[ref] = _Pedido(
                        documento_referencia=ref,
                        pedido_shopify=row.get("pedido_shopify") or "",
                        fecha_compra=fecha,
                        cliente=" ".join(p for p in nombre if p),
                        numero_documento=row.get("numero_documento") or "",
                        reporte_origen=path.name,
                    )
                pedido.lineas += 1
                pedido.valor_total += _decimal(row.get("valor_total_linea") or "")
                pedido.vending = pedido.vending or bodega_no_se_carga(row.get("bodega_siesa") or "")
        pedidos.update({ref: asdict(p) for ref, p in actuales.items()})
    return pedidos


def conciliar(
    exporte_file: Path,
    processed_dir: Path,
    output_dir: Path = DEFAULT_RECONCILIATION_DIR,
    desde: date | None = None,
    columna: str | None = None,
    ahora: datetime | None = None,
) -> Conciliacion:
    exporte = leer_exporte(exporte_file, columna)
    logger.info(
        "Exporte Siesa %s: %d referencias en la columna '%s'.",
        exporte_file.name,
        len(exporte.referencias),
        exporte.columna,
    )
    if exporte.duplicadas:
        logger.warning(
            "Referencias repetidas en Siesa (revisar, R-35): %s",
            ", ".join(f"{ref} x{n}" for ref, n in sorted(exporte.duplicadas.items())),
        )

    pedidos = pedidos_reportados(processed_dir, desde)
    filas: list[dict[str, object]] = []
    for ref, pedido in sorted(pedidos.items(), key=lambda kv: (str(kv[1]["fecha_compra"]), kv[0])):
        if pedido.pop("vending"):
            estado = NO_SE_CARGA
        else:
            estado = EN_SIESA if ref in exporte.referencias else FALTA_EN_SIESA
        filas.append({"estado": estado, "documento_siesa": exporte.documentos.get(ref, ""), **pedido})
    # Primero los que faltan: es lo que hay que revisar.
    filas.sort(key=lambda f: _ORDEN_ESTADOS[str(f["estado"])])

    marca = (ahora or datetime.now(timezone.utc)).astimezone(BOGOTA).strftime("%Y%m%dT%H%M%S")
    csv_file = output_dir / f"conciliacion_{marca}.csv"
    xlsx_file = output_dir / f"conciliacion_{marca}.xlsx"
    write_csv(filas, csv_file, COLUMNAS)
    write_xlsx(filas, xlsx_file, COLUMNAS, COLUMNAS_NUMERICAS, sheet_title="Conciliacion")

    resultado = Conciliacion(filas, exporte, csv_file, xlsx_file)
    desde_txt = f" desde {desde.isoformat()}" if desde else ""
    vending = sum(1 for f in filas if f["estado"] == NO_SE_CARGA)
    a_cargar = len(filas) - vending
    if vending:
        logger.info("%d pedidos de vending no se buscan en Siesa (no se cargan).", vending)
    if resultado.faltantes:
        logger.warning(
            "Conciliación%s: %d de %d pedidos NO están en Siesa. Detalle en %s",
            desde_txt,
            resultado.faltantes,
            a_cargar,
            xlsx_file,
        )
    else:
        logger.info("Conciliación%s: los %d pedidos están en Siesa.", desde_txt, a_cargar)
    return resultado
