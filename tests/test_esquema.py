"""Validación de esquema de las filas del reporte, antes de escribirlas."""

import copy
import json
from decimal import Decimal

import pytest

from shopify_pipeline.shopify.fulfillment import FULFILLMENT_KEY, _slim
from shopify_pipeline.transform.esquema import MAX_ERRORES_DETALLE, errores_de_fila, validar_pedido
from shopify_pipeline.transform.siesa_lines import COLUMNS, order_to_lines, transform_orders
from tests.conftest import FIXTURES


@pytest.fixture
def pagado() -> dict:
    data = json.loads((FIXTURES / "order_1006.json").read_text(encoding="utf-8"))
    fos = json.loads((FIXTURES / "fulfillment_orders_1006.json").read_text(encoding="utf-8"))
    data[FULFILLMENT_KEY] = [_slim(fo) for fo in fos["fulfillment_orders"]]
    data["financial_status"] = "paid"
    return data


@pytest.fixture
def fila(pagado) -> dict:
    return order_to_lines(pagado).rows[0]


def test_filas_reales_cumplen_el_esquema(pagado):
    assert validar_pedido(order_to_lines(pagado).rows, COLUMNS) == []


@pytest.mark.parametrize(
    ("campo", "valor", "esperado"),
    [
        ("cantidad", 0, "cantidad: entero > 0"),
        ("cantidad", True, "cantidad: entero > 0"),  # bool no cuenta como entero
        ("precio_neto", Decimal("-1"), "precio_neto: Decimal ≥ 0"),
        ("valor_total_linea", 1500.0, "valor_total_linea: Decimal ≥ 0 (tipo float)"),
        ("documento_referencia", "  ", "documento_referencia: texto no vacío"),
        ("id_pedido_shopify", "18931A", "id_pedido_shopify: solo dígitos"),
        ("fecha_compra", "", "fecha_compra: AAAA-MM-DD HH:MM:SS"),
        ("tipo_linea", "DESCUENTO", "tipo_linea: PRODUCTO o ENVIO"),
        ("tasa_iva", Decimal("19"), "tasa_iva: Decimal entre 0 y 1"),
        ("email", None, "email: texto (tipo NoneType)"),  # columnas de texto: nunca None
    ],
)
def test_reglas(fila, campo, valor, esperado):
    fila[campo] = valor
    assert any(e.startswith(esperado) for e in errores_de_fila(fila, COLUMNS)), errores_de_fila(fila, COLUMNS)


def test_columna_faltante_y_total_inconsistente(fila):
    sin_col = {k: v for k, v in fila.items() if k != "bodega_siesa"}
    assert errores_de_fila(sin_col, COLUMNS) == ["bodega_siesa: falta la columna"]
    fila["valor_total_linea"] += 1
    assert errores_de_fila(fila, COLUMNS) == ["valor_total_linea: distinto de precio_neto × cantidad"]


def test_detalle_se_resume(fila):
    filas = [dict(fila, cantidad=0, numero_linea=i) for i in range(1, 10)]
    errores = validar_pedido(filas, COLUMNS)
    assert len(errores) == MAX_ERRORES_DETALLE + 1
    assert errores[-1] == f"(+{9 - MAX_ERRORES_DETALLE} más)"


def test_pedido_invalido_se_excluye_completo_y_el_lote_sigue(pagado):
    malo = copy.deepcopy(pagado)
    malo |= {"id": 99, "name": "#9999", "order_number": 9999}
    # Descuento mayor que el precio → precio neto negativo en la línea de producto.
    malo["line_items"][0]["discount_allocations"] = [{"amount": "999999.00"}]

    result = transform_orders([malo, pagado])

    assert result.pedidos_procesados == 1
    assert {r["pedido_shopify"] for r in result.rows} == {"#1006"}  # ni una línea del #9999
    (evento,) = (e for e in result.eventos if e.codigo == "ESQUEMA_INVALIDO")
    assert evento.pedido_shopify == "#9999"
    assert evento.detalle.startswith("línea 1: precio_neto: Decimal ≥ 0")
    assert result.errores == 1
    # El detalle nunca trae datos del cliente.
    nombre = pagado["billing_address"]["first_name"]
    assert nombre not in evento.detalle
