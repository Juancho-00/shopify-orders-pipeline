"""Pruebas de la transformación con el pedido #1006 (anonimizado) que compartió el equipo de Shopify."""

import copy
import json
from decimal import Decimal

import pytest

from shopify_pipeline.shopify.fulfillment import FULFILLMENT_KEY, _slim
from shopify_pipeline.transform.alertas import DESCRIPCIONES, EVENT_COLUMNS
from shopify_pipeline.transform.siesa_lines import (
    COLUMNS,
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
    # Cédula desde billing_address.company, sin puntos; Siesa la identifica con "C" (R-10)
    assert row["tipo_documento"] == "C"
    assert row["numero_documento"] == "1017000001"
    assert row["telefono"] == "3001112233"
    assert row["email"] == "cliente.prueba@example.com"
    assert row["direccion"] == "Calle 10 # 20-30"
    assert row["direccion_complemento"] == ""


def test_direccion_y_complemento_separados(order):
    order["billing_address"]["address2"] = "Apto 301"
    row = rows(order)[0]
    assert (row["direccion"], row["direccion_complemento"]) == ("Calle 10 # 20-30", "Apto 301")
    assert row["codigo_postal"] == "050021"
    assert row["ciudad"] == "Medellin"
    assert row["departamento"] == "Antioquia"
    assert row["codigo_ciudad_siesa"] == "16905001"  # 169 + DANE de Medellín (R-11)


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
    order["billing_address"]["company"] = "800.197.268-4 Comercial Andina S.A.S."
    row = rows(order)[0]
    assert row["razon_social"] == "COMERCIAL ANDINA S.A.S."  # el nombre sale de company
    assert (row["tipo_documento"], row["numero_documento"], row["digito_verificacion"]) == (
        "N",
        "800197268",
        "4",
    )
    assert codigos(order) == []


def test_nit_inferido_queda_por_verificar(order):
    order["billing_address"]["company"] = "850197268 Empresa X"  # 9 dígitos, no inicia en 800/900/901
    assert rows(order)[0]["tipo_documento"] == "N"
    assert codigos(order) == ["NIT_POR_VERIFICAR"]


def test_nit_por_prefijo_sin_alerta(order):
    order["billing_address"]["company"] = "Comercial Andina SAS - 900197268"  # nombre antes del NIT
    row = rows(order)[0]
    assert (row["tipo_documento"], row["numero_documento"], row["razon_social"]) == (
        "N",
        "900197268",
        "COMERCIAL ANDINA SAS",
    )
    assert codigos(order) == []


def test_nit_sin_nombre_de_empresa_usa_el_de_facturacion(order):
    order["billing_address"]["company"] = "900197268"
    row = rows(order)[0]
    assert row["razon_social"] == "LAURA SOFÍA RESTREPO DE LA TORRE"
    assert codigos(order) == ["RAZON_SOCIAL_DESDE_NOMBRE"]


def test_cedula_no_lleva_razon_social(order):
    assert rows(order)[0]["razon_social"] == ""


def test_cedula_extranjeria_sin_codigo_siesa(order):
    order["billing_address"]["company"] = "CE 123456"
    assert rows(order)[0]["tipo_documento"] == ""
    assert codigos(order) == ["TIPO_DOCUMENTO_SIN_CODIGO_SIESA"]


def test_ciudad_desconocida_genera_alerta(order):
    for clave in ("billing_address", "shipping_address"):
        order[clave]["city"] = "Ciudad Inventada"
    (evento,) = order_to_lines(order).eventos
    assert evento.codigo == "CIUDAD_SIN_CODIGO"
    assert evento.detalle == "Ciudad Inventada / Antioquia"


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
    assert row["bodega"] == "D'Luchi PT Guarne"
    assert row["bodega_siesa"] == "LCD01"  # R-09
    assert row["id_bodega_shopify"] == "80001"
    assert row["cantidad"] == 1
    assert row["precio_unitario"] == Decimal("89999")
    assert row["precio_neto"] == Decimal("89999")  # sin descuento: igual al precio del ítem
    assert row["tasa_iva"] == Decimal("0.1900")
    assert row["precio_incluye_iva"] == "SI"


def test_linea_envio(order):
    row = rows(order)[1]
    assert row["referencia"] == "SERV01"  # R-08
    assert row["cantidad"] == 1
    assert row["precio_unitario"] == row["precio_neto"] == Decimal("12294")  # pesos enteros (R-23)
    assert row["tasa_iva"] == Decimal("0.1900")  # el envío lleva IVA incluido (R-07)
    assert (row["bodega"], row["bodega_siesa"]) == ("D'Luchi PT Guarne", "LCD01")  # misma de los productos
    assert row["numero_linea"] == 2


def test_envio_con_descuento(order):
    order["shipping_lines"][0].update({"price": "15000.00", "discounted_price": "7500.40"})
    row = rows(order)[1]
    assert (row["precio_unitario"], row["descuento_linea"], row["precio_neto"]) == (
        Decimal("15000"),
        Decimal("7500"),
        Decimal("7500"),
    )


def test_precios_con_decimales_se_redondean(order):
    order["line_items"][0]["price"] = "89999.50"
    row = rows(order)[0]
    assert row["precio_unitario"] == row["precio_neto"] == Decimal("90000")


def test_bodega_sin_equivalencia(order):
    order[FULFILLMENT_KEY][0]["assigned_location"]["name"] = "Bodega Nueva"
    (evento,) = order_to_lines(order).eventos
    assert (evento.codigo, evento.detalle) == ("BODEGA_SIN_EQUIVALENCIA", "Bodega Nueva")
    assert rows(order)[0]["bodega_siesa"] == ""


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
    assert row["descuento_linea"] == Decimal("10000")
    # Siesa no recibe descuentos (R-13): precio neto por unidad = (2*89999 - 10000) / 2
    assert row["precio_unitario"] == Decimal("89999")
    assert row["precio_neto"] == Decimal("84999")
    assert row["valor_total_linea"] == Decimal("169998")


def test_reembolso_parcial_prorratea_el_descuento(order):
    """2 unidades con $10.000 de descuento; se reembolsa 1 → queda $5.000 de descuento."""
    item = order["line_items"][0]
    item["quantity"], item["current_quantity"] = 2, 1
    item["discount_allocations"] = [{"amount": "10000.00"}]
    row = rows(order)[0]
    assert row["cantidad"] == 1
    assert row["descuento_linea"] == Decimal("5000")
    assert row["valor_total_linea"] == Decimal("84999")


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
    # Total del #1006 = 102293.34; las líneas van en pesos enteros y cuadran dentro de $50 (R-24)
    assert sum(r["valor_total_linea"] for r in rows(order)) == Decimal("102293")
    assert "TOTAL_NO_CUADRA" not in codigos(order)


def test_diferencia_menor_a_50_pesos_se_acepta(order):
    order["current_total_price"] = "102340.00"
    assert "TOTAL_NO_CUADRA" not in codigos(order)


def test_total_no_cuadra_genera_alerta(order):
    order["current_total_price"] = "150000.00"  # p. ej. una propina o cargo no modelado
    (evento,) = order_to_lines(order).eventos
    assert evento.codigo == "TOTAL_NO_CUADRA"
    assert evento.detalle == "Shopify 150000.00 vs líneas 102293.00"


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


# ------------------------------------------------- aislamiento y contrato
def test_pedido_con_dato_malo_no_detiene_el_lote(paid_order):
    malo = copy.deepcopy(paid_order)
    malo["id"], malo["name"] = 99, "#9999"
    malo["line_items"][0]["price"] = "no-es-un-monto"

    result = transform_orders([malo, paid_order])

    assert result.pedidos_procesados == 1
    assert result.errores == 1
    (error,) = [e for e in result.eventos if e.codigo == "ERROR_TRANSFORMACION"]
    assert error.pedido_shopify == "#9999"
    assert "Monto inválido" in error.detalle
    assert {r["pedido_shopify"] for r in result.rows} == {"#1006"}


def test_pedido_sin_campo_test_no_pasa_en_silencio(paid_order):
    """Sin la clave ``test`` (extracción con --fields) un pedido de prueba pasaría al reporte."""
    proyectado = copy.deepcopy(paid_order)
    del proyectado["test"]

    result = transform_orders([proyectado])

    assert result.rows == []
    assert result.pedidos_excluidos == {"DATOS_INCOMPLETOS": 1}
    assert "test" in result.eventos[0].detalle


# ------------------------------------------------------------------- ledger
def test_ledger_excluye_pedidos_ya_reportados(paid_order, tmp_path):
    from shopify_pipeline.state import Ledger

    ledger = Ledger(tmp_path / "reportados.json")
    primera = transform_orders([paid_order], ledger=ledger, run_id="RUN1")
    assert primera.reportados == [(paid_order["id"], "102293.34")]
    ledger.marcar(paid_order["id"], "102293.34", "RUN1")

    # La ventana siguiente se solapa: el mismo pedido llega otra vez.
    segunda = transform_orders([paid_order], ledger=ledger, run_id="RUN2")
    assert segunda.rows == []
    assert [(e.codigo, e.detalle) for e in segunda.eventos] == [("YA_REPORTADO", "run=RUN1")]

    # Regenerar el reporte de la misma corrida (comando transform) no lo excluye.
    regenerado = transform_orders([paid_order], ledger=ledger, run_id="RUN1")
    assert regenerado.pedidos_procesados == 1


def test_ledger_detecta_cambio_despues_de_reportado(paid_order, tmp_path):
    from shopify_pipeline.state import Ledger

    ledger = Ledger(tmp_path / "reportados.json")
    ledger.marcar(paid_order["id"], "102293.34", "RUN1")
    paid_order["current_total_price"] = "89999.00"  # p. ej. reembolso del envío

    result = transform_orders([paid_order], ledger=ledger, run_id="RUN2")

    assert result.rows == []
    (evento,) = result.eventos
    assert evento.codigo == "CAMBIO_POST_REPORTE"
    assert evento.detalle == "total 102293.34 → 89999.00 (run=RUN1)"


def test_va_al_reporte(paid_order, order, tmp_path):
    from shopify_pipeline.state import Ledger
    from shopify_pipeline.transform.siesa_lines import va_al_reporte

    opciones = SiesaLinesOptions()
    assert va_al_reporte(paid_order, opciones)
    assert not va_al_reporte(order | {"financial_status": "pending"}, opciones)
    ledger = Ledger(tmp_path / "r.json")
    ledger.marcar(paid_order["id"], "1.00", "RUN1")
    assert not va_al_reporte(paid_order, opciones, ledger)
    sin_test = {k: v for k, v in paid_order.items() if k != "test"}
    assert va_al_reporte(sin_test, opciones)  # Ante la duda, se consulta
