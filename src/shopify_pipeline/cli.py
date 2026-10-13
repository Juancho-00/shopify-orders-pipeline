"""
Línea de comandos del pipeline.

    shopify-pipeline extract --days 7
    shopify-pipeline extract --since 2026-10-01 --until 2026-10-08 --status any

Códigos de salida:
    0  éxito
    1  error transitorio (red / Shopify) tras agotar reintentos
    2  error de configuración o credenciales (no se arregla reintentando)
    3  extracción completa pero el conteo no cuadró contra Shopify (--strict)
"""

from __future__ import annotations

import argparse
import logging
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

logger = logging.getLogger("shopify_pipeline")

EXIT_OK, EXIT_TRANSIENT, EXIT_CONFIG, EXIT_UNRECONCILED = 0, 1, 2, 3


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shopify-pipeline", description="Pipeline de integración Shopify → ERP."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    parser.add_argument("--env-file", type=Path, default=None, help="Ruta al .env (default: ./.env)")
    sub = parser.add_subparsers(dest="command", required=True)

    ext = sub.add_parser("extract", help="Fase 1: extrae pedidos de Shopify a data/raw.")
    window = ext.add_mutually_exclusive_group()
    window.add_argument("--days", type=int, default=None, help="Últimos N días (default: 7).")
    window.add_argument("--since", type=_parse_date, help="Inicio de la ventana (YYYY-MM-DD o ISO).")
    ext.add_argument(
        "--until", type=_parse_date, help="Fin de la ventana (default: ahora). Requiere --since."
    )
    ext.add_argument("--status", default="any", choices=sorted(VALID_STATUSES))
    ext.add_argument("--fields", default=None, help="Campos separados por coma, ej: id,name,created_at")
    ext.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    ext.add_argument(
        "--strict", action="store_true", help="Sale con código 3 si el conteo no cuadra con Shopify."
    )
    return parser


def build_filter(args: argparse.Namespace) -> OrderFilter:
    fields = tuple(f.strip() for f in args.fields.split(",") if f.strip()) if args.fields else None
    if args.until and not args.since:
        raise ValueError("--until requiere --since.")
    if args.since:
        until = args.until or datetime.now(timezone.utc).replace(microsecond=0)
        return OrderFilter(created_at_min=args.since, created_at_max=until, status=args.status, fields=fields)
    return OrderFilter.last_n_days(args.days or 7, status=args.status, fields=fields)


def _cmd_extract(args: argparse.Namespace) -> int:
    flt = build_filter(args)
    client = ShopifyClient(ShopifyConfig.from_env())
    result = run_extraction(client, flt, output_dir=args.output_dir)
    if args.strict and not result.reconciled:
        return EXIT_UNRECONCILED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    load_env_file(args.env_file)

    try:
        if args.command == "extract":
            return _cmd_extract(args)
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
