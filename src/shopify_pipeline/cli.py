"""
Línea de comandos del pipeline.

    shopify-pipeline extract --days 7
    shopify-pipeline extract --since 2026-10-01 --until 2026-10-08 --status any
    shopify-pipeline extract --days 3 --filtrar-por actualizacion   # captura pagos confirmados tarde
    shopify-pipeline transform                      # rehace el reporte Siesa de la última extracción

Logs (en --log-dir, por defecto data/logs):
    shopify_pipeline_AAAAMMDD.log   # bitácora de cada ejecución del día
    alertas_<run_id>.csv            # alertas de datos y pedidos excluidos de cada corrida

Códigos de salida:
    0  éxito
    1  error transitorio (red / Shopify) tras agotar reintentos
    2  error de configuración o credenciales (no se arregla reintentando)
    3  extracción completa pero el conteo no cuadró contra Shopify (--strict)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

import requests

from shopify_pipeline import __version__
from shopify_pipeline.config import ShopifyConfig, load_env_file
from shopify_pipeline.exceptions import CONFIGURATION_ERRORS, ShopifyError
from shopify_pipeline.extract import DEFAULT_OUTPUT_DIR, run_extraction
from shopify_pipeline.shopify.client import ShopifyClient
from shopify_pipeline.shopify.orders import VALID_STATUSES, OrderFilter
from shopify_pipeline.transform.run import (
    DEFAULT_LOG_DIR,
    DEFAULT_PROCESSED_DIR,
    latest_raw_file,
    run_transform,
)
from shopify_pipeline.transform.siesa_lines import DEFAULT_ESTADOS_PAGO, SiesaLinesOptions

logger = logging.getLogger("shopify_pipeline")

EXIT_OK, EXIT_TRANSIENT, EXIT_CONFIG, EXIT_UNRECONCILED = 0, 1, 2, 3

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"
DATE_FIELDS = {"creacion": "created_at", "actualizacion": "updated_at"}


def _parse_date(value: str) -> datetime:
    """Acepta ``YYYY-MM-DD`` (00:00 UTC) o un ISO 8601 completo con zona horaria."""
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time.min, tzinfo=timezone.utc)
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
        default=os.environ.get("SIESA_CODIGO_ENVIO", "ENVIO"),
        help="Referencia del ítem de envío en Siesa (default: $SIESA_CODIGO_ENVIO o ENVIO).",
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
    sub = parser.add_subparsers(dest="command", required=True)

    ext = sub.add_parser("extract", help="Fase 1: extrae pedidos de Shopify y genera el reporte Siesa.")
    window = ext.add_mutually_exclusive_group()
    window.add_argument("--days", type=int, default=None, help="Últimos N días (default: 7).")
    window.add_argument("--since", type=_parse_date, help="Inicio de la ventana (YYYY-MM-DD o ISO).")
    ext.add_argument(
        "--until", type=_parse_date, help="Fin de la ventana (default: ahora). Requiere --since."
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
        "--solo-raw", action="store_true", help="Solo guarda el JSONL; no genera el reporte Siesa."
    )
    ext.add_argument(
        "--strict", action="store_true", help="Sale con código 3 si el conteo no cuadra con Shopify."
    )
    _add_siesa_options(ext)

    tr = sub.add_parser("transform", help="Regenera el reporte Siesa desde un JSONL ya extraído.")
    tr.add_argument(
        "--input", type=Path, default=None, help="Archivo .jsonl (default: la última extracción)."
    )
    tr.add_argument("--raw-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    _add_siesa_options(tr)
    return parser


def build_filter(args: argparse.Namespace) -> OrderFilter:
    fields = tuple(f.strip() for f in args.fields.split(",") if f.strip()) if args.fields else None
    if args.until and not args.since:
        raise ValueError("--until requiere --since.")
    common = {"status": args.status, "fields": fields, "date_field": DATE_FIELDS[args.filtrar_por]}
    if args.since:
        until = args.until or datetime.now(timezone.utc).replace(microsecond=0)
        return OrderFilter(date_min=args.since, date_max=until, **common)
    return OrderFilter.last_n_days(args.days or 7, **common)


def _parse_estados(value: str) -> frozenset[str] | None:
    if value.strip().lower() == "todos":
        return None
    estados = frozenset(e.strip().lower() for e in value.split(",") if e.strip())
    if not estados:
        raise ValueError("--estados-pago no puede estar vacío (use 'todos' para no filtrar).")
    return estados


def _siesa_options(args: argparse.Namespace) -> SiesaLinesOptions:
    return SiesaLinesOptions(
        codigo_envio=args.codigo_envio,
        estados_pago=_parse_estados(args.estados_pago),
        incluir_cancelados=args.incluir_cancelados,
        incluir_pruebas=args.incluir_pruebas,
    )


def _cmd_extract(args: argparse.Namespace) -> int:
    flt = build_filter(args)
    client = ShopifyClient(ShopifyConfig.from_env())
    result = run_extraction(client, flt, output_dir=args.output_dir, consultar_bodega=not args.sin_bodega)
    if not args.solo_raw:
        run_transform(
            args.output_dir / result.output_file, args.processed_dir, _siesa_options(args), args.log_dir
        )
    if args.strict and not result.reconciled:
        return EXIT_UNRECONCILED
    return EXIT_OK


def _cmd_transform(args: argparse.Namespace) -> int:
    raw_file = args.input or latest_raw_file(args.raw_dir)
    if not raw_file.exists():
        raise ValueError(f"No existe el archivo {raw_file}.")
    run_transform(raw_file, args.processed_dir, _siesa_options(args), args.log_dir)
    return EXIT_OK


def setup_logging(level: str, log_dir: Path | None) -> Path | None:
    """
    Consola + archivo diario ``shopify_pipeline_AAAAMMDD.log`` (se agrega al final).
    Devuelve la ruta del archivo de log.
    """
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT)
    pkg = logging.getLogger("shopify_pipeline")
    pkg.setLevel(level.upper())
    for handler in [h for h in pkg.handlers if getattr(h, "_shopify_pipeline", False)]:
        pkg.removeHandler(handler)
        handler.close()
    if log_dir is None:
        return None
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"shopify_pipeline_{date.today():%Y%m%d}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler._shopify_pipeline = True  # type: ignore[attr-defined]
    pkg.addHandler(handler)
    return path


def main(argv: list[str] | None = None) -> int:
    # El .env se carga antes de leer los argumentos para que SIESA_CODIGO_ENVIO aplique.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file", type=Path, default=None)
    load_env_file(pre.parse_known_args(argv)[0].env_file)

    args = build_parser().parse_args(argv)
    setup_logging(args.log_level, args.log_dir)
    logger.info("Inicio: shopify-pipeline %s %s", __version__, args.command)

    try:
        if args.command == "extract":
            return _cmd_extract(args)
        if args.command == "transform":
            return _cmd_transform(args)
    except CONFIGURATION_ERRORS as exc:
        logger.error("Error de configuración/credenciales: %s", exc)
        return EXIT_CONFIG
    except ShopifyError as exc:
        logger.error("Error de Shopify: %s", exc)
        return EXIT_TRANSIENT
    except requests.RequestException as exc:
        logger.error("Error de red tras agotar reintentos: %s", exc)
        return EXIT_TRANSIENT
    return EXIT_OK  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
