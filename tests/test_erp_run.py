"""Fase 3: generación de la plantilla de terceros desde un reporte sintético."""

from __future__ import annotations

import csv
from datetime import date

import pytest
from openpyxl import load_workbook

from shopify_pipeline import cli
from shopify_pipeline.erp.run import generar_plantillas, ultimo_reporte
from shopify_pipeline.erp.terceros import TERCEROS_COLUMNS
from shopify_pipeline.exceptions import ConfigError

COLUMNAS = ["documento_referencia", "pedido_shopify", "fecha_compra", "tipo_documento", "numero_documento",
            "primer_nombre", "segundo_nombre", "primer_apellido", "segundo_apellido", "direccion",
            "direccion_complemento", "codigo_ciudad_siesa", "telefono", "email", "referencia"]  # fmt: skip


def _fila(ref, doc, fecha, **cambios):
    valores = [ref, f"#{ref}", fecha, "C", doc, "Ana", "", "Pérez", "Gómez", "Calle 1 # 2-3", "",
               "16905001", "3001112233", "ana@example.com", "SKU1"]  # fmt: skip
    base = dict(zip(COLUMNAS, valores, strict=True))
    return base | cambios


def _reporte(path, filas):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(filas)
    return path


@pytest.fixture
def reporte(tmp_path):
    return _reporte(
        tmp_path / "processed" / "pedidos_siesa_20261019T113000Z.csv",
        [
            _fila("1006", "1017000001", "2026-10-18 10:00:00"),
            _fila("1006", "1017000001", "2026-10-18 10:00:00", referencia="SERV01"),  # 2ª línea
            _fila("1007", "1017000001", "2026-10-18 15:00:00", direccion="Carrera 9 # 8-7"),  # mismo cliente
            _fila("1008", "70123456", "2026-10-18 16:00:00", codigo_ciudad_siesa=""),  # sin ciudad
        ],
    )


def test_genera_un_tercero_por_cliente(reporte, tmp_path):
    run = generar_plantillas(reporte, tmp_path / "cargas", tmp_path / "logs", date(2026, 10, 19))

    assert run.terceros_file.name == "terceros_20261019T113000Z.xlsx"
    assert run.terceros == 1  # 1006 y 1007 son del mismo cliente; 1008 no se carga
    assert run.pedidos_cargables == {"1006", "1007"}
    ws = load_workbook(run.terceros_file).active
    assert ws.title == "Terceros"
    assert [c.value for c in ws[1]] == list(TERCEROS_COLUMNS)
    fila = dict(zip(TERCEROS_COLUMNS, (c.value for c in ws[2]), strict=True))
    assert fila["F200_ID"] == 1017000001  # número, como en la plantilla
    assert fila["F200_FECHA_NACIMIENTO"] == "20261019"  # texto, como en la plantilla de ejemplo
    assert fila["F015_DIRECCION1"] == "Carrera 9 # 8-7"  # datos del pedido más reciente
    assert fila["F015_ID_DEPTO"] == "05" and ws.cell(row=2, column=14).number_format == "@"


def test_libro_tiene_las_4_hojas_de_la_plantilla(tmp_path):
    reporte = _reporte(
        tmp_path / "pedidos_siesa_20261019T113000Z.csv",
        [
            _fila("1006", "1017000001", "2026-10-18 10:00:00"),
            _fila("1007", "70123456", "2026-10-18 11:00:00"),
        ],
    )
    run = generar_plantillas(reporte, tmp_path / "cargas", tmp_path / "logs", date(2026, 10, 19))
    wb = load_workbook(run.terceros_file)
    assert wb.sheetnames == ["Terceros", "Clientes", "Imptos y Reten", "Ent. Dinamica Cliente"]

    clientes = [[c.value for c in fila] for fila in wb["Clientes"].iter_rows(min_row=2)]
    assert [f[0] for f in clientes] == [1017000001, 70123456]
    assert clientes[0][1:8] == ["001", "ANA PÉREZ GÓMEZ", "W001", "03D", "C001", "1", "500"]
    assert clientes[0][17:19] == ["20261019", "W001"]

    impuestos = [[c.value for c in fila] for fila in wb["Imptos y Reten"].iter_rows(min_row=2)]
    assert impuestos == [  # por bloques: 46 de todos, 47/1 de todos, 47/41 de todos
        ["46", 1017000001, "001", "1", "1"],
        ["46", 70123456, "001", "1", "1"],
        ["47", 1017000001, "001", "1", "0"],
        ["47", 70123456, "001", "1", "0"],
        ["47", 1017000001, "001", "41", "1"],
        ["47", 70123456, "001", "41", "1"],
    ]
    entidad = [[c.value for c in fila] for fila in wb["Ent. Dinamica Cliente"].iter_rows(min_row=2)]
    assert entidad == [[1017000001, "001", "ana@example.com"], [70123456, "001", "ana@example.com"]]


def test_pedido_con_cliente_incompleto_queda_en_el_log(reporte, tmp_path):
    run = generar_plantillas(reporte, tmp_path / "cargas", tmp_path / "logs", date(2026, 10, 19))
    with run.eventos_file.open(encoding="utf-8-sig") as fh:
        eventos = list(csv.DictReader(fh))
    assert [(e["codigo"], e["documento_referencia"], e["detalle"]) for e in eventos] == [
        ("TERCERO_INCOMPLETO", "1008", "falta: codigo_ciudad_siesa")
    ]
    assert "70123456" not in run.eventos_file.read_text(encoding="utf-8-sig")  # sin datos personales


def test_ultimo_reporte_ignora_revision(tmp_path):
    _reporte(tmp_path / "pedidos_siesa_20261018T113000Z.csv", [])
    _reporte(tmp_path / "pedidos_siesa_20261019T113000Z_revision.csv", [])
    assert ultimo_reporte(tmp_path).name == "pedidos_siesa_20261018T113000Z.csv"
    with pytest.raises(ConfigError):
        ultimo_reporte(tmp_path / "vacio")


def test_cli_plantillas(reporte, tmp_path):
    base = ["--log-dir", str(tmp_path / "logs"), "plantillas", "--processed-dir", str(reporte.parent),
            "--output-dir", str(tmp_path / "cargas")]  # fmt: skip
    assert cli.main(base) == cli.EXIT_OK
    assert cli.main([*base, "--strict"]) == cli.EXIT_DATA  # el 1008 no se pudo cargar
    assert (tmp_path / "cargas" / "terceros_20261019T113000Z.xlsx").exists()
