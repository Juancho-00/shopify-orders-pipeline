"""Pruebas de la transformación con el pedido #1006 (anonimizado) que compartió el equipo de Shopify."""

import copy
import json
from decimal import Decimal

import pytest

from shopify_pipeline.shopify.fulfillment import FULFILLMENT_KEY, _slim
from shopify_pipeline.transform.siesa_lines import (
    COLUMNS,
    DESCRIPCIONES,
    EVENT_COLUMNS,
    SiesaLinesOptions,
    order_to_lines,
    transform_orders,
)
from tests.conftest import FIXTURES


@pytest.fixture
def order() -> dict:
    data = json.loads((FIXTURES / "order_1006.json").read_text(encoding="utf-8"))
    fos = json.loads((FIXTURES / "fulfillment_orders_1006.json").read_text(encoding="utf-8"))
    data[FULFILLMENT_KEY] = [_slim(fo) for fo in fos["fulfillment_orders"]]
    return data


@pytest.fixture
def paid_order(order) -> dict:
    """El #1006 es contraentrega (pending); aquí simulamos que el pago ya se confirmó."""
    order["financial_status"] = "paid"
    return order


def rows(order, **kwargs):
    return order_to_lines(order, SiesaLinesOptions(**kwargs)).rows


def codigos(order):
    return order_to_lines(order).codigos


# ------------------------------------------------------------------ estructura
def test_pedido_1006_genera_producto_y_envio(order):
    result = order_to_lines(order)
    assert [r["tipo_linea"] for r in result.rows] == ["PRODUCTO", "ENVIO"]
    assert all(set(r) == set(COLUMNS) for r in result.rows)
    assert result.eventos == []


def test_reporte_no_incluye_columna_de_alertas():
    assert "alertas" not in COLUMNS


# -------------------------------------------------------------------- cliente
def test_datos_cliente(order):
    row = rows(order)[0]
    assert row["primer_nombre"] == "Laura"
    assert row["segundo_nombre"] == "Sofía"
    assert row["primer_apellido"] == "Restrepo"
    assert row["segundo_apellido"] == "de la Torre"
    # Cédula desde billing_address.company, sin puntos
    assert row["tipo_documento"] == "CC"
    assert row["numero_documento"] == "1017000001"
    assert row["telefono"] == "3001112233"
    assert row["email"] == "cliente.prueba@example.com"
    assert row["direccion"] == "Calle 10 # 20-30"
    assert row["codigo_postal"] == "050021"
    assert row["ciudad"] == "Medellin"
    assert row["departamento"] == "Antioquia"


def test_cedula_desde_shipping_si_falta_en_billing(order):
    order["billing_address"]["company"] = None
    assert rows(order)[0]["numero_documento"] == "1017000001"


def test_sin_cedula_genera_alerta_una_vez_por_pedido(order):
    order["billing_address"]["company"] = None
    order["shipping_address"]["company"] = ""
    assert codigos(order) == ["SIN_DOCUMENTO"]  # Una sola vez, aunque el pedido tenga 2 líneas


def test_billing_null_usa_shipping(order):
    order["billing_address"] = None
    row = rows(order)[0]
    assert row["primer_nombre"] == "Laura"
    assert row["numero_documento"] == "1017000001"


def test_nit_con_dv(order):
    order["billing_address"]["company"] = "800.197.268-4"
    row = rows(order)[0]
    assert (row["tipo_documento"], row["numero_documento"], row["digito_verificacion"]) == (
        "NIT",
        "800197268",
        "4",
    )
    assert codigos(order) == []


def test_nit_inferido_queda_por_verificar(order):
    order["billing_address"]["company"] = "800197268"
    assert rows(order)[0]["tipo_documento"] == "NIT"
    assert codigos(order) == ["NIT_POR_VERIFICAR"]


# --------------------------------------------------------------------- pedido
def test_datos_pedido(order):
    row = rows(order)[0]
    assert row["documento_referencia"] == "1006"
    assert row["pedido_shopify"] == "#1006"
    assert row["fecha_compra"] == "2026-10-08 17:59:15"
    assert row["fecha_creacion"] == "2026-10-08 17:59:16"
    assert row["estado_pago"] == "pending"
    assert row["notas"] == ""


def test_notas_y_atributos(order):
    order["note"] = "Entregar\nen portería"
    order["note_attributes"] = [{"name": "Horario", "value": "Tarde"}]
    assert rows(order)[0]["notas"] == "Entregar en portería | Horario: Tarde"


# --------------------------------------------------------------------- líneas
def test_linea_producto(order):
    row = rows(order)[0]
    assert row["referencia"] == "KITK0108"
    assert row["bodega"] == "Bodega Principal Medellín"
    assert row["id_bodega_shopify"] == "80001"
    assert row["cantidad"] == 1
    assert row["precio_unitario"] == Decimal("89999.00")
    assert row["tasa_iva"] == Decimal("0.1900")
    assert row["precio_incluye_iva"] == "SI"


def test_linea_envio(order):
    row = rows(order)[1]
    assert row["referencia"] == "ENVIO"
    assert row["cantidad"] == 1
    assert row["precio_unitario"] == Decimal("12294.34")
    assert row["bodega"] == ""
    assert row["numero_linea"] == 2


def test_codigo_envio_configurable(order):
    assert rows(order, codigo_envio="FLETE01")[1]["referencia"] == "FLETE01"


@pytest.mark.parametrize(
    "cambio",
    [
        {"price": "0.00", "discounted_price": "0.00"},  # envío gratis
        {"discounted_price": "0.00"},  # envío gratis por descuento
        {"is_removed": True},  # envío eliminado del pedido
    ],
)
def test_envio_sin_costo_no_genera_linea(order, cambio):
    order["shipping_lines"][0].update(cambio)
    assert [r["tipo_linea"] for r in rows(order)] == ["PRODUCTO"]


def test_descuentos_y_multiples_unidades(order):
    item = order["line_items"][0]
    item["quantity"] = item["current_quantity"] = 2
    item["discount_allocations"] = [{"amount": "10000.00"}]
    row = rows(order)[0]
    assert row["cantidad"] == 2
    assert row["descuento_linea"] == Decimal("10000.00")
    assert row["valor_total_linea"] == Decimal("169998.00")


def test_linea_eliminada_se_omite(order):
    order["line_items"][0]["current_quantity"] = 0
    assert [r["tipo_linea"] for r in rows(order)] == ["ENVIO"]


# -------------------------------------------------------------------- alertas
def test_alertas_de_linea_traen_numero_y_referencia(order):
    order["line_items"][0]["sku"] = ""
    del order[FULFILLMENT_KEY]
    eventos = order_to_lines(order).eventos
    assert [(e.codigo, e.numero_linea) for e in eventos] == [("SIN_SKU", 1), ("BODEGA_NO_CONSULTADA", 1)]
    assert all(e.tipo == "ALERTA" and e.pedido_shopify == "#1006" for e in eventos)


def test_sin_bodega_asignada(order):
    order[FULFILLMENT_KEY] = []
    evento = order_to_lines(order).eventos[0]
    assert (evento.codigo, evento.referencia) == ("SIN_BODEGA", "KITK0108")


def test_total_de_lineas_cuadra_con_shopify(order):
    assert sum(r["valor_total_linea"] for r in rows(order)) == Decimal("102293.34")  # total del #1006
    assert "TOTAL_NO_CUADRA" not in codigos(order)


def test_total_no_cuadra_genera_alerta(order):
    order["current_total_price"] = "150000.00"  # p. ej. una propina o cargo no modelado
    (evento,) = order_to_lines(order).eventos
    assert evento.codigo == "TOTAL_NO_CUADRA"
    assert evento.detalle == "Shopify 150000.00 vs líneas 102293.34"


def test_eventos_no_contienen_datos_personales(order):
    order["billing_address"]["company"] = None
    order["shipping_address"]["company"] = None
    row = order_to_lines(order).eventos[0].as_row()
    assert list(row) == list(EVENT_COLUMNS)
    texto = json.dumps(row, ensure_ascii=False)
    for dato in ("Laura", "Restrepo", "cliente.prueba", "3001112233", "Calle 10"):
        assert dato not in texto


def test_todos_los_codigos_tienen_descripcion(order):
    order["billing_address"]["company"] = "800197268-9"
    order["line_items"][0]["sku"] = ""
    order[FULFILLMENT_KEY] = []
    order["current_total_price"] = "1.00"
    for codigo in codigos(order):
        assert codigo in DESCRIPCIONES


# ---------------------------------------------------------------- exclusiones
def test_solo_pasan_pedidos_con_pago_confirmado(order, paid_order):
    pendiente = copy.deepcopy(order)
    pendiente["financial_status"] = "pending"
    autorizado = copy.deepcopy(order)
    autorizado["financial_status"] = "authorized"
    reembolso_parcial = copy.deepcopy(paid_order)
    reembolso_parcial["financial_status"] = "partially_refunded"

    result = transform_orders([paid_order, pendiente, autorizado, reembolso_parcial])

    assert result.pedidos_procesados == 2
    assert result.pedidos_excluidos == {"PAGO_NO_CONFIRMADO": 2}
    excluidos = [e for e in result.eventos if e.tipo == "EXCLUIDO"]
    assert [e.detalle for e in excluidos] == ["estado_pago=pending", "estado_pago=authorized"]


def test_estados_pago_configurable(order):
    result = transform_orders([order], SiesaLinesOptions(estados_pago=None))  # 'todos'
    assert result.pedidos_procesados == 1


def test_exclusiones_cancelados_y_pruebas(paid_order):
    cancelado = copy.deepcopy(paid_order)
    cancelado["cancelled_at"] = "2026-10-09T10:00:00-05:00"
    cancelado["cancel_reason"] = "customer"
    prueba = copy.deepcopy(paid_order)
    prueba["test"] = True

    result = transform_orders([paid_order, cancelado, prueba])
    assert result.pedidos_procesados == 1
    assert result.pedidos_excluidos == {"CANCELADO": 1, "PRUEBA": 1}
    assert {(e.codigo, e.detalle) for e in result.eventos} == {("CANCELADO", "customer"), ("PRUEBA", "")}

    todo = transform_orders(
        [paid_order, cancelado, prueba], SiesaLinesOptions(incluir_cancelados=True, incluir_pruebas=True)
    )
    assert todo.pedidos_procesados == 3
    assert [e.codigo for e in todo.alertas] == ["PEDIDO_CANCELADO"]
    assert todo.pedidos_con_alertas == 1
