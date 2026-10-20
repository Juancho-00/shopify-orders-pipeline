"""
Línea de comandos: lo que se ejecuta al escribir ``shopify-pipeline ...`` en la terminal.

QUÉ HACE
    1. Lee los argumentos (``--days``, ``--since``, ``--codigo-envio``...).
    2. Carga el ``.env`` y configura los logs.
    3. Llama al orquestador que corresponda (``extract``, ``transform`` o ``conciliar``).
    4. Convierte cualquier error en un código de salida (0 a 5) para que una tarea
       programada sepa si la corrida salió bien.

    Este archivo NO contiene lógica de negocio: solo traduce lo que escribe el usuario a
    llamadas a ``extract.py``, ``transform/run.py`` y ``reconciliation/run.py``.

    shopify-pipeline extract --days 7
    shopify-pipeline extract --since 2026-10-01 --until 2026-10-08 --status any
    shopify-pipeline extract --incremental          # tarea programada: retoma desde la última corrida buena
    shopify-pipeline extract --days 3 --filtrar-por actualizacion   # captura pagos confirmados tarde
    shopify-pipeline transform                      # rehace el reporte Siesa de la última extracción
    shopify-pipeline conciliar                      # fase 2: ¿los pedidos reportados ya están en Siesa?
    shopify-pipeline plantillas                     # fase 3: plantillas de clientes y pedidos para Siesa
    shopify-pipeline notificar                      # correo con el resultado de la última corrida

Logs (en --log-dir, por defecto data/logs):
    shopify_pipeline_AAAAMMDD.log   # bitácora de cada ejecución del día
    alertas_<run_id>.csv            # alertas de datos y pedidos excluidos de cada corrida

Códigos de salida:
    0  éxito
    1  error transitorio (red / Shopify) tras agotar reintentos
    2  error de configuración o credenciales (no se arregla reintentando)
    3  extracción completa pero el conteo no cuadró contra Shopify (--strict), o
       (conciliar --strict) hay pedidos reportados que no están en Siesa
    4  error de datos: archivo crudo dañado, extracción incompleta, o (con --strict)
       pedidos que no se pudieron transformar
    5  error inesperado (bug): revisar la bitácora; reintentar no sirve
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from shopify_pipeline import __version__
from shopify_pipeline.config import ShopifyConfig, load_env_file
from shopify_pipeline.erp.run import DEFAULT_CARGAS_DIR, generar_plantillas, ultimo_reporte
from shopify_pipeline.exceptions import CONFIGURATION_ERRORS, ConfigError, DataError, ShopifyError
from shopify_pipeline.extract import DEFAULT_OUTPUT_DIR, run_extraction
from shopify_pipeline.logs import setup_logging
from shopify_pipeline.notificaciones import notificar
from shopify_pipeline.reconciliation.run import (
    DEFAULT_EXPORTES_DIR,
    DEFAULT_RECONCILIATION_DIR,
    conciliar,
)
from shopify_pipeline.reconciliation.siesa_export import ultimo_exporte
from shopify_pipeline.shopify.client import ShopifyClient
from shopify_pipeline.shopify.orders import VALID_STATUSES, OrderFilter
from shopify_pipeline.state import DEFAULT_STATE_DIR, Ledger, incremental_window, save_watermark
from shopify_pipeline.transform.normalize import BOGOTA
from shopify_pipeline.transform.run import (
    DEFAULT_LOG_DIR,
    DEFAULT_PROCESSED_DIR,
    latest_raw_file,
    run_transform,
)
from shopify_pipeline.transform.siesa_lines import (
    CAMPOS_REQUERIDOS,
    DEFAULT_ESTADOS_PAGO,
    SiesaLinesOptions,
    va_al_reporte,
)

logger = logging.getLogger("shopify_pipeline")

EXIT_OK, EXIT_TRANSIENT, EXIT_CONFIG, EXIT_UNRECONCILED, EXIT_DATA, EXIT_UNEXPECTED = 0, 1, 2, 3, 4, 5

DATE_FIELDS = {"creacion": "created_at", "actualizacion": "updated_at"}


def _parse_date(value: str) -> datetime:
    """
    Acepta ``YYYY-MM-DD`` o un ISO 8601 completo con zona horaria.

    Una fecha sola es la medianoche en hora de COLOMBIA: "pedidos del 1 de octubre" debe
    ser el día de la tienda, no el día UTC (que empieza a las 19:00 del día anterior).
    """
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time.min, tzinfo=BOGOTA)
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Fecha inválida: {value!r}") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(f"Incluya zona horaria en {value!r} (ej. -05:00).")
    return parsed


def _add_siesa_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("reporte Siesa")
    g.add_argument(
        "--codigo-envio",
        default=os.environ.get("SIESA_CODIGO_ENVIO", "SERV01"),
        help="Referencia del ítem de envío en Siesa (default: $SIESA_CODIGO_ENVIO o SERV01).",
    )
    g.add_argument(
        "--estados-pago",
        default=",".join(sorted(DEFAULT_ESTADOS_PAGO)),
        help="Estados de pago que pasan a Siesa, separados por coma, o 'todos' "
        "(default: paid,partially_refunded = pago confirmado).",
    )
    g.add_argument("--incluir-cancelados", action="store_true", help="Incluye pedidos cancelados.")
    g.add_argument("--incluir-pruebas", action="store_true", help="Incluye pedidos de prueba (test).")
    g.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    g.add_argument(
        "--sin-ledger",
        action="store_true",
        help="No consulta ni actualiza el registro de pedidos ya reportados "
        "(data/state/reportados.json). Genera archivos *_revision: para revisar, no para cargar a Siesa.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shopify-pipeline", description="Pipeline de integración Shopify → Siesa."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    parser.add_argument("--env-file", type=Path, default=None, help="Ruta al .env (default: ./.env)")
    parser.add_argument(
        "--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="Carpeta de logs (default: data/logs)."
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
        help="Estado entre corridas: watermark y pedidos reportados (default: data/state).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ext = sub.add_parser("extract", help="Fase 1: extrae pedidos de Shopify y genera el reporte Siesa.")
    window = ext.add_mutually_exclusive_group()
    window.add_argument("--days", type=int, default=None, help="Últimos N días (default: 7).")
    window.add_argument(
        "--since",
        type=_parse_date,
        help="Inicio de la ventana (YYYY-MM-DD en hora Colombia, o ISO con zona horaria).",
    )
    window.add_argument(
        "--incremental",
        action="store_true",
        help="Ventana desde la última extracción completa (menos 30 min) hasta ahora, sobre la "
        "fecha de actualización. Recomendado para la tarea programada: no deja huecos.",
    )
    ext.add_argument(
        "--until",
        type=_parse_date,
        help="Fin de la ventana (default: ahora). Mismo formato que --since. Requiere --since.",
    )
    ext.add_argument(
        "--filtrar-por",
        choices=sorted(DATE_FIELDS),
        default="creacion",
        help="Fecha a la que se aplica la ventana: creación del pedido (default) o última "
        "actualización (incluye pedidos antiguos cuyo pago se confirmó en la ventana).",
    )
    ext.add_argument("--status", default="any", choices=sorted(VALID_STATUSES))
    ext.add_argument("--fields", default=None, help="Campos separados por coma, ej: id,name,created_at")
    ext.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    ext.add_argument(
        "--sin-bodega", action="store_true", help="No consulta la bodega (ahorra una llamada por pedido)."
    )
    ext.add_argument(
        "--bodega-todos",
        action="store_true",
        help="Consulta la bodega de todos los pedidos. Por defecto solo la de los que van al reporte "
        "(pagados, no cancelados ni de prueba, no reportados antes).",
    )
    ext.add_argument(
        "--solo-raw", action="store_true", help="Solo guarda el JSONL; no genera el reporte Siesa."
    )
    ext.add_argument(
        "--strict",
        action="store_true",
        help="Código 3 si el conteo no cuadra con Shopify; 4 si hay pedidos que no se pudieron transformar.",
    )
    _add_siesa_options(ext)

    tr = sub.add_parser("transform", help="Regenera el reporte Siesa desde un JSONL ya extraído.")
    tr.add_argument(
        "--input", type=Path, default=None, help="Archivo .jsonl (default: la última extracción)."
    )
    tr.add_argument("--raw-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    tr.add_argument(
        "--strict",
        action="store_true",
        help="Código 3 si la extracción no cuadró; 4 si hay pedidos que no se pudieron transformar.",
    )
    _add_siesa_options(tr)

    co = sub.add_parser("conciliar", help="Fase 2: verifica que los pedidos reportados existan en Siesa.")
    co.add_argument(
        "--exporte",
        type=Path,
        default=None,
        help="Exporte de pedidos de Siesa (.xlsx/.csv). Default: el más reciente de --exportes-dir.",
    )
    co.add_argument("--exportes-dir", type=Path, default=DEFAULT_EXPORTES_DIR)
    co.add_argument(
        "--columna",
        default=None,
        help="Columna del exporte con el número de pedido (default: _num_docto_referencia).",
    )
    co.add_argument(
        "--desde",
        type=_parse_date,
        default=None,
        help="Solo pedidos comprados desde esta fecha YYYY-MM-DD (default: últimos 30 días).",
    )
    co.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    co.add_argument("--output-dir", type=Path, default=DEFAULT_RECONCILIATION_DIR)
    co.add_argument(
        "--strict", action="store_true", help="Código 3 si algún pedido reportado no está en Siesa."
    )

    pl = sub.add_parser(
        "plantillas", help="Fase 3: genera las plantillas de clientes y de pedidos para cargar a Siesa."
    )
    pl.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Reporte pedidos_siesa_<run_id>.csv (default: el más reciente de --processed-dir).",
    )
    pl.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    pl.add_argument("--output-dir", type=Path, default=DEFAULT_CARGAS_DIR)
    pl.add_argument(
        "--strict",
        action="store_true",
        help="Código 4 si algún pedido no se puede cargar por datos faltantes.",
    )

    no = sub.add_parser("notificar", help="Envía por correo el resultado de la última corrida (ver .env).")
    no.add_argument(
        "--run-id",
        default="",
        help="run_id de la corrida, para incluir el conteo de las plantillas (lo pasa el script diario).",
    )
    return parser


def _parse_fields(args: argparse.Namespace) -> tuple[str, ...] | None:
    if not args.fields:
        return None
    fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
    if args.solo_raw:
        return fields
    # Se va a generar el reporte Siesa: sin estos campos saldría incompleto (p. ej. sin
    # ``test`` los pedidos de prueba pasarían). Se agregan siempre.
    extra = tuple(f for f in CAMPOS_REQUERIDOS if f not in fields)
    if extra:
        logger.info("--fields: se agregan %d campos que necesita el reporte Siesa.", len(extra))
    return fields + extra


def build_filter(args: argparse.Namespace) -> OrderFilter:
    fields = _parse_fields(args)
    if args.until and not args.since:
        raise ConfigError("--until requiere --since.")
    common = {"status": args.status, "fields": fields, "date_field": DATE_FIELDS[args.filtrar_por]}
    if args.incremental:
        # La ventana incremental siempre va sobre updated_at: así entran también los
        # pedidos antiguos cuyo pago se confirmó después (contraentrega).
        date_min, date_max = incremental_window(args.state_dir)
        return OrderFilter(date_min=date_min, date_max=date_max, **(common | {"date_field": "updated_at"}))
    if args.since:
        until = args.until or datetime.now(timezone.utc).replace(microsecond=0)
        return OrderFilter(date_min=args.since, date_max=until, **common)
    return OrderFilter.last_n_days(args.days or 7, **common)


def _parse_estados(value: str) -> frozenset[str] | None:
    if value.strip().lower() == "todos":
        return None
    estados = frozenset(e.strip().lower() for e in value.split(",") if e.strip())
    if not estados:
        raise ConfigError("--estados-pago no puede estar vacío (use 'todos' para no filtrar).")
    return estados


def _siesa_options(args: argparse.Namespace) -> SiesaLinesOptions:
    return SiesaLinesOptions(
        codigo_envio=args.codigo_envio,
        estados_pago=_parse_estados(args.estados_pago),
        incluir_cancelados=args.incluir_cancelados,
        incluir_pruebas=args.incluir_pruebas,
    )


def _ledger(args: argparse.Namespace) -> Ledger | None:
    return None if args.sin_ledger else Ledger.open(args.state_dir)


def _sufijo(args: argparse.Namespace) -> str:
    # Sin ledger el reporte puede traer pedidos ya cargados: nunca debe reemplazar al oficial.
    return "_revision" if args.sin_ledger else ""


def _codigo_strict(args: argparse.Namespace, reconciled: bool, errores: int) -> int:
    if not args.strict:
        return EXIT_OK
    if not reconciled:
        return EXIT_UNRECONCILED
    if errores:
        return EXIT_DATA
    return EXIT_OK


def _filtro_bodega(
    args: argparse.Namespace, ledger: Ledger | None
) -> Callable[[dict[str, Any]], bool] | None:
    """Qué pedidos merecen la llamada de bodega (una por pedido). None = todos."""
    if args.bodega_todos or args.solo_raw:
        return None
    options = _siesa_options(args)
    return lambda order: va_al_reporte(order, options, ledger)


def _cmd_extract(args: argparse.Namespace) -> int:
    flt = build_filter(args)
    # El ledger se abre antes de extraer: si está dañado, falla sin gastar llamadas a Shopify.
    ledger = None if args.solo_raw else _ledger(args)
    client = ShopifyClient(ShopifyConfig.from_env())
    result = run_extraction(
        client,
        flt,
        output_dir=args.output_dir,
        consultar_bodega=not args.sin_bodega,
        incremental=args.incremental,
        debe_consultar_bodega=_filtro_bodega(args, ledger),
    )
    errores = 0
    if not args.solo_raw:
        run = run_transform(
            args.output_dir / result.output_file,
            args.processed_dir,
            _siesa_options(args),
            args.log_dir,
            ledger=ledger,
            sufijo=_sufijo(args),
        )
        errores = run.result.errores
    if args.incremental:
        # El watermark solo avanza si la extracción quedó completa. Si no cuadró, la próxima
        # corrida vuelve a cubrir este periodo (el ledger evita reportar dos veces).
        if result.reconciled:
            save_watermark(flt.date_max, result.run_id, args.state_dir)
        else:
            logger.warning("Watermark sin cambios: la próxima corrida repetirá este periodo.")
    return _codigo_strict(args, result.reconciled, errores)


def _cmd_transform(args: argparse.Namespace) -> int:
    raw_file = args.input or latest_raw_file(args.raw_dir)
    if not raw_file.exists():
        raise ConfigError(f"No existe el archivo {raw_file}.")
    run = run_transform(
        raw_file,
        args.processed_dir,
        _siesa_options(args),
        args.log_dir,
        ledger=_ledger(args),
        sufijo=_sufijo(args),
    )
    return _codigo_strict(args, run.reconciled, run.result.errores)


def _cmd_conciliar(args: argparse.Namespace) -> int:
    exporte = args.exporte or ultimo_exporte(args.exportes_dir)
    if not exporte.exists():
        raise ConfigError(f"No existe el archivo {exporte}.")
    desde = args.desde.date() if args.desde else datetime.now(BOGOTA).date() - timedelta(days=30)
    resultado = conciliar(exporte, args.processed_dir, args.output_dir, desde, args.columna)
    return EXIT_UNRECONCILED if args.strict and resultado.faltantes else EXIT_OK


def _cmd_notificar(args: argparse.Namespace) -> int:
    # Siempre 0: un fallo del correo no debe marcar como fallida la corrida.
    notificar(args.log_dir, args.run_id, args.log_dir.parent)
    return EXIT_OK


def _cmd_plantillas(args: argparse.Namespace) -> int:
    reporte = args.input or ultimo_reporte(args.processed_dir)
    if not reporte.exists():
        raise ConfigError(f"No existe el archivo {reporte}.")
    if reporte.stem.endswith("_revision"):
        raise ConfigError(f"{reporte.name} es un reporte de revisión: no se carga a Siesa.")
    run = generar_plantillas(reporte, args.output_dir, args.log_dir)
    return EXIT_DATA if args.strict and run.no_cargados else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    # Paso 1: cargar el .env ANTES de leer los argumentos, porque el valor por defecto de
    # --codigo-envio sale de la variable SIESA_CODIGO_ENVIO definida en el .env.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file", type=Path, default=None)
    load_env_file(pre.parse_known_args(argv)[0].env_file)

    # Paso 2: leer todos los argumentos y preparar los logs.
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level, args.log_dir)
    logger.info("Inicio: shopify-pipeline %s %s", __version__, args.command)

    # Paso 3: ejecutar el comando. Paso 4: traducir errores a códigos de salida.
    try:
        if args.command == "extract":
            return _cmd_extract(args)
        if args.command == "transform":
            return _cmd_transform(args)
        if args.command == "conciliar":
            return _cmd_conciliar(args)
        if args.command == "plantillas":
            return _cmd_plantillas(args)
        if args.command == "notificar":
            return _cmd_notificar(args)
    except CONFIGURATION_ERRORS as exc:
        logger.error("Error de configuración/credenciales: %s", exc)
        return EXIT_CONFIG
    except DataError as exc:
        logger.error("Error de datos: %s", exc)
        return EXIT_DATA
    except ShopifyError as exc:
        logger.error("Error de Shopify: %s", exc)
        return EXIT_TRANSIENT
    except requests.RequestException as exc:  # Va antes de OSError: es una subclase.
        logger.error("Error de red tras agotar reintentos: %s", exc)
        return EXIT_TRANSIENT
    except OSError as exc:
        # Archivo abierto en Excel, bloqueado por la sincronización de Drive, disco lleno...
        logger.error("Error al leer o escribir archivos: %s. Cierre el archivo y reintente.", exc)
        return EXIT_TRANSIENT
    except Exception:
        logger.exception("Error inesperado (posible bug). Reintentar no lo resolverá.")
        return EXIT_UNEXPECTED
    return EXIT_OK  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
