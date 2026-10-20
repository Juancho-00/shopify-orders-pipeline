"""Fase 2: conciliación contra un exporte de Siesa. Todos los datos son sintéticos."""

from __future__ import annotations

import csv
import os
from datetime import date, datetime, timezone

import pytest
from openpyxl import Workbook

from shopify_pipeline import cli
from shopify_pipeline.exceptions import ConfigError, DataError
from shopify_pipeline.reconciliation.run import (
    EN_SIESA,
    FALTA_EN_SIESA,
    NO_SE_CARGA,
    conciliar,
    pedidos_reportados,
)
from shopify_pipeline.reconciliation.siesa_export import (
    leer_exporte,
    normalizar_referencia,
    ultimo_exporte,
)

AHORA = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)


def _reporte(path, filas):
    """Reporte de la fase 1 reducido a las columnas que usa la conciliación."""
    columnas = ["documento_referencia", "pedido_shopify", "fecha_compra", "primer_nombre",
                "primer_apellido", "numero_documento", "valor_total_linea"]  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(columnas)
        w.writerows(filas)


def _exporte_xlsx(path, filas, titulo=True):
    wb = Workbook()
    ws = wb.active
    if titulo:  # Los exportes de Siesa suelen traer filas de título antes del encabezado.
        ws.append(["Consulta de pedidos"])
        ws.append([])
    ws.append(["Nro documento", "_num_docto_referencia"])  # como el exporte real de Siesa
    for fila in filas:
        ws.append(fila)
    wb.save(path)


@pytest.fixture
def processed(tmp_path):
    carpeta = tmp_path / "processed"
    _reporte(
        carpeta / "pedidos_siesa_20261015T120000Z.csv",
        [
            ["1006", "#1006", "2026-10-08 17:59:15", "Ana", "Pérez", "1017000001", "89999"],
            ["1006", "#1006", "2026-10-08 17:59:15", "Ana", "Pérez", "1017000001", "12294"],
            ["1007", "#1007", "2026-10-09 10:00:00", "Luis", "Gómez", "70123456", "50000"],
        ],
    )
    # Un reporte de revisión nunca se carga a Siesa: no entra a la conciliación.
    _reporte(
        carpeta / "pedidos_siesa_20261015T130000Z_revision.csv",
        [["2000", "#2000", "2026-10-09 10:00:00", "X", "Y", "1", "1"]],
    )
    return carpeta


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("1006", "1006"), (" #1006 ", "1006"), (1006, "1006"), (1006.0, "1006"), ("1006.0", "1006"),
     (None, ""), ("", "")],
)  # fmt: skip
def test_normalizar_referencia(valor, esperado):
    assert normalizar_referencia(valor) == esperado


def test_leer_exporte_xlsx_con_filas_de_titulo(tmp_path):
    path = tmp_path / "siesa.xlsx"
    _exporte_xlsx(
        path,
        [["CPM-00000001", 1006], ["CPM-00000002", "#1008"], ["CPM-00000003", None], ["CPM-00000004", 1008]],
    )
    exporte = leer_exporte(path)
    assert exporte.columna == "_num_docto_referencia"
    assert exporte.referencias == {"1006", "1008"}
    assert exporte.duplicadas == {"1008": 2}
    assert exporte.documentos == {"1006": "CPM-00000001", "1008": "CPM-00000002, CPM-00000004"}


def test_exporte_con_formato_real_de_siesa(tmp_path):
    """Como el exporte real: encabezado en la fila 1, referencia numérica y tabla con filtros."""
    path = tmp_path / "siesa.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["Nro documento", "_num_docto_referencia"])
    ws.append(["CPM-00009001", 2000001])
    ws.append(["CPM-00009002", 2000005])
    ws.auto_filter.ref = "A1:B3"
    wb.save(path)
    exporte = leer_exporte(path)
    assert exporte.referencias == {"2000001", "2000005"}
    assert exporte.documentos["2000005"] == "CPM-00009002"


def test_leer_exporte_csv_punto_y_coma_y_mayusculas(tmp_path):
    path = tmp_path / "siesa.csv"
    path.write_text("CO;CONSECUTIVO;NUM DOCTO REFERENCIA\n001;1;1006\n001;2;1007\n", encoding="cp1252")
    assert leer_exporte(path).referencias == {"1006", "1007"}


def test_columna_personalizada(tmp_path):
    path = tmp_path / "siesa.csv"
    path.write_text("pedido_web,otro\n1006,x\n", encoding="utf-8")
    assert leer_exporte(path, columna="Pedido Web").referencias == {"1006"}


def test_exporte_sin_columna_de_referencia(tmp_path):
    path = tmp_path / "siesa.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(DataError, match="_num_docto_referencia"):
        leer_exporte(path)


def test_ultimo_exporte_ignora_temporales_de_excel(tmp_path):
    viejo, nuevo = tmp_path / "a.xlsx", tmp_path / "b.csv"
    viejo.write_text("x")
    nuevo.write_text("x")
    (tmp_path / "~$b.xlsx").write_text("x")  # archivo de bloqueo de Excel abierto
    os.utime(viejo, (1, 1))
    assert ultimo_exporte(tmp_path) == nuevo
    with pytest.raises(ConfigError):
        ultimo_exporte(tmp_path / "no-existe")


def test_pedidos_reportados_agrupa_lineas_y_excluye_revision(processed):
    pedidos = pedidos_reportados(processed)
    assert set(pedidos) == {"1006", "1007"}
    assert pedidos["1006"]["lineas"] == 2
    assert str(pedidos["1006"]["valor_total"]) == "102293"
    assert pedidos["1006"]["cliente"] == "Ana Pérez"


def test_pedidos_reportados_desde(processed):
    assert set(pedidos_reportados(processed, desde=date(2026, 10, 9))) == {"1007"}


def test_conciliar_marca_faltantes_primero(processed, tmp_path):
    exporte = tmp_path / "siesa.xlsx"
    _exporte_xlsx(exporte, [["CPM-00000001", 1006]])
    resultado = conciliar(exporte, processed, tmp_path / "out", ahora=AHORA)

    assert [(f["documento_referencia"], f["estado"], f["documento_siesa"]) for f in resultado.filas] == [
        ("1007", FALTA_EN_SIESA, ""),
        ("1006", EN_SIESA, "CPM-00000001"),
    ]
    assert resultado.faltantes == 1
    assert resultado.csv_file.name == "conciliacion_20261019T100000.csv"  # hora Colombia
    assert resultado.xlsx_file.exists()


def test_cli_conciliar_strict(processed, tmp_path):
    exportes = tmp_path / "exportes"
    exportes.mkdir()
    _exporte_xlsx(exportes / "siesa.xlsx", [["CPM-00000001", 1006]], titulo=False)
    base = ["--log-dir", str(tmp_path / "logs"), "conciliar", "--exportes-dir", str(exportes),
            "--processed-dir", str(processed), "--output-dir", str(tmp_path / "out"),
            "--desde", "2026-10-01"]  # fmt: skip
    assert cli.main(base) == cli.EXIT_OK
    assert cli.main([*base, "--strict"]) == cli.EXIT_UNRECONCILED


def test_cli_conciliar_sin_exportes(tmp_path):
    vacia = tmp_path / "exportes"
    vacia.mkdir()
    args = ["--log-dir", str(tmp_path / "logs"), "conciliar", "--exportes-dir", str(vacia)]
    assert cli.main(args) == cli.EXIT_CONFIG


def test_pedidos_de_vending_no_se_buscan_en_siesa(tmp_path):
    carpeta = tmp_path / "processed"
    carpeta.mkdir()
    with (carpeta / "pedidos_siesa_20261020T113000Z.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["documento_referencia", "pedido_shopify", "fecha_compra", "bodega_siesa", "valor_total_linea"]
        )
        w.writerow(["5001", "#5001", "2026-10-19 09:00:00", "LCM55", "50000"])  # vending
        w.writerow(["5002", "#5002", "2026-10-19 10:00:00", "LCD01", "60000"])
    exporte = tmp_path / "siesa.xlsx"
    _exporte_xlsx(exporte, [["CPW-00000001", 5002]])
    resultado = conciliar(exporte, carpeta, tmp_path / "out", ahora=AHORA)
    assert [(f["documento_referencia"], f["estado"]) for f in resultado.filas] == [
        ("5002", EN_SIESA),
        ("5001", NO_SE_CARGA),
    ]
    assert resultado.faltantes == 0
