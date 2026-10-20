"""
Extracción de pedidos con la GraphQL Admin API (la API recomendada por Shopify).

POR QUÉ GRAPHQL
    La REST Admin API es *legacy* desde octubre de 2024. Además, con REST la bodega de cada
    producto exige una llamada extra por pedido (``fulfillment_orders.json``). Con GraphQL
    el pedido, sus líneas, su envío y sus bodegas llegan en la misma consulta.

CÓMO SE INTEGRA SIN TOCAR EL RESTO
    ``a_formato_rest`` convierte cada pedido de GraphQL al mismo diccionario que entregaba
    REST (``order_number``, ``line_items``, ``financial_status``, ``_fulfillment_orders``...).
    Así la transformación, el ledger, las plantillas y sus pruebas no cambian, y el JSONL
    crudo conserva el mismo formato. ``SHOPIFY_API=rest`` vuelve a la versión anterior.

COSTO DE LA CONSULTA
    GraphQL cobra por campos pedidos y una petición no puede pasar de 1.000 puntos. Se piden
    pocos pedidos por página (``PEDIDOS_POR_PAGINA``); si Shopify responde que la consulta
    cuesta demasiado, la página se achica a la mitad y se reintenta. Un pedido con más de
    ``LINEAS_POR_PAGINA`` líneas trae el resto con consultas adicionales.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Any

from shopify_pipeline.exceptions import ShopifyCostoExcedidoError
from shopify_pipeline.shopify.client import ShopifyClient
from shopify_pipeline.shopify.fulfillment import FULFILLMENT_KEY
from shopify_pipeline.shopify.orders import OrderFilter

logger = logging.getLogger(__name__)

# Costo estimado por pedido con estos tamaños: ~250 puntos (líneas ~160, bodegas ~75, envío ~15).
# Con 3 pedidos por página la consulta queda en ~780 de los 1.000 puntos permitidos.
PEDIDOS_POR_PAGINA = 3
LINEAS_POR_PAGINA = 20  # Un pedido con más líneas trae el resto aparte (MAS_LINEAS_QUERY).
BODEGAS_POR_PEDIDO = 3  # Grupos de despacho por pedido; normalmente 1.
MAS_LINEAS_POR_PAGINA = 50

_DINERO = "shopMoney { amount }"
_DIRECCION = "firstName lastName company address1 address2 city province provinceCode zip countryCodeV2 phone"
_LINEA = f"""
    id sku name title quantity currentQuantity
    originalUnitPriceSet {{ {_DINERO} }}
    totalDiscountSet {{ {_DINERO} }}
    discountAllocations {{ allocatedAmountSet {{ {_DINERO} }} }}
    taxLines {{ rate }}
"""

ORDERS_QUERY = f"""
query Pedidos($first: Int!, $after: String, $query: String) {{
  orders(first: $first, after: $after, query: $query, sortKey: UPDATED_AT) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{
      id legacyResourceId name createdAt updatedAt processedAt cancelledAt cancelReason
      displayFinancialStatus test taxesIncluded email phone note
      customAttributes {{ key value }}
      currentTotalPriceSet {{ {_DINERO} }}
      totalPriceSet {{ {_DINERO} }}
      billingAddress {{ {_DIRECCION} }}
      shippingAddress {{ {_DIRECCION} }}
      customer {{ legacyResourceId firstName lastName defaultAddress {{ {_DIRECCION} }} }}
      lineItems(first: {LINEAS_POR_PAGINA}) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {_LINEA} }}
      }}
      shippingLines(first: 3) {{
        nodes {{
          title code isRemoved
          originalPriceSet {{ {_DINERO} }}
          discountedPriceSet {{ {_DINERO} }}
          taxLines {{ rate }}
        }}
      }}
      fulfillmentOrders(first: {BODEGAS_POR_PEDIDO}) {{
        nodes {{
          id status
          assignedLocation {{ name location {{ legacyResourceId }} }}
          lineItems(first: {LINEAS_POR_PAGINA}) {{
            pageInfo {{ hasNextPage }}
            nodes {{ totalQuantity lineItem {{ id }} }}
          }}
        }}
      }}
    }}
  }}
}}
"""

MAS_LINEAS_QUERY = f"""
query MasLineas($id: ID!, $after: String) {{
  order(id: $id) {{
    lineItems(first: {MAS_LINEAS_POR_PAGINA}, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ {_LINEA} }}
    }}
  }}
}}
"""

COUNT_QUERY = """
query Conteo($query: String) {
  ordersCount(query: $query, limit: null) { count precision }
}
"""


# ------------------------------------------------------------------- filtro
def search_query(flt: OrderFilter) -> str:
    """
    Filtro de búsqueda de Shopify equivalente al de REST.

    ``updated_at:>='2026-10-19T11:00:00+00:00' AND updated_at:<='...'`` (+ ``status:open``
    si se pidió un estado; ``any`` = sin filtro de estado).
    """
    campo = flt.date_field  # created_at / updated_at: mismos nombres en la búsqueda de GraphQL
    partes = [
        f"{campo}:>='{flt.date_min.isoformat()}'",
        f"{campo}:<='{flt.date_max.isoformat()}'",
    ]
    if flt.status != "any":
        partes.append(f"status:{flt.status}")
    return " AND ".join(partes)


def count_orders_graphql(client: ShopifyClient, flt: OrderFilter) -> int:
    data = client.graphql(COUNT_QUERY, {"query": search_query(flt)})
    conteo = data.get("ordersCount") or {}
    if conteo.get("precision") not in (None, "EXACT"):
        logger.warning("Shopify devolvió un conteo aproximado (%s).", conteo.get("precision"))
    return int(conteo.get("count") or 0)


# --------------------------------------------------------------- conversión
def _legacy(gid: Any) -> int | None:
    """``"gid://shopify/LineItem/123"`` → ``123``."""
    if gid is None:
        return None
    match = re.search(r"(\d+)$", str(gid))
    return int(match.group(1)) if match else None


def _monto(money_bag: dict[str, Any] | None) -> str | None:
    return ((money_bag or {}).get("shopMoney") or {}).get("amount")


def _minuscula(valor: Any) -> str | None:
    return valor.lower() if isinstance(valor, str) else valor


def _direccion(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return None
    return {
        "first_name": d.get("firstName"),
        "last_name": d.get("lastName"),
        "company": d.get("company"),
        "address1": d.get("address1"),
        "address2": d.get("address2"),
        "city": d.get("city"),
        "province": d.get("province"),
        "province_code": d.get("provinceCode"),
        "zip": d.get("zip"),
        "country_code": d.get("countryCodeV2"),
        "phone": d.get("phone"),
    }


def _impuestos(tax_lines: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [{"rate": t.get("rate")} for t in tax_lines or []]


def _linea(li: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _legacy(li.get("id")),
        "sku": li.get("sku"),
        "name": li.get("name"),
        "title": li.get("title"),
        "quantity": li.get("quantity"),
        "current_quantity": li.get("currentQuantity"),
        "price": _monto(li.get("originalUnitPriceSet")),
        "total_discount": _monto(li.get("totalDiscountSet")),
        "discount_allocations": [
            {"amount": _monto(d.get("allocatedAmountSet"))} for d in li.get("discountAllocations") or []
        ],
        "tax_lines": _impuestos(li.get("taxLines")),
    }


def _envio(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": s.get("title"),
        "code": s.get("code"),
        "price": _monto(s.get("originalPriceSet")),
        "discounted_price": _monto(s.get("discountedPriceSet")),
        "is_removed": bool(s.get("isRemoved")),
        "tax_lines": _impuestos(s.get("taxLines")),
    }


def _bodega(fo: dict[str, Any]) -> dict[str, Any]:
    """Mismo formato que ``fulfillment._slim`` (REST)."""
    asignada = fo.get("assignedLocation") or {}
    location_id = _legacy((asignada.get("location") or {}).get("legacyResourceId"))
    return {
        "id": _legacy(fo.get("id")),
        "status": _minuscula(fo.get("status")),
        "assigned_location_id": location_id,
        "assigned_location": {"location_id": location_id, "name": asignada.get("name")},
        "line_items": [
            {
                "line_item_id": _legacy((li.get("lineItem") or {}).get("id")),
                "quantity": li.get("totalQuantity"),
            }
            for li in ((fo.get("lineItems") or {}).get("nodes") or [])
        ],
    }


def _numero_pedido(name: str | None, legacy_id: Any) -> int | None:
    """``"#1006"`` → ``1006`` (el consecutivo que ve el cliente; R-12)."""
    digitos = re.sub(r"\D", "", name or "")
    return int(digitos) if digitos else _legacy(legacy_id)


def a_formato_rest(nodo: dict[str, Any], lineas: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """
    Pedido de GraphQL → diccionario con los nombres de la REST API que usa la transformación.

    ``lineas`` permite pasar las líneas completas cuando el pedido tenía más de una página.
    """
    customer = nodo.get("customer") or None
    nodos_lineas = lineas if lineas is not None else ((nodo.get("lineItems") or {}).get("nodes") or [])
    return {
        "id": _legacy(nodo.get("legacyResourceId") or nodo.get("id")),
        "admin_graphql_api_id": nodo.get("id"),
        "name": nodo.get("name"),
        "order_number": _numero_pedido(nodo.get("name"), nodo.get("legacyResourceId")),
        "created_at": nodo.get("createdAt"),
        "updated_at": nodo.get("updatedAt"),
        "processed_at": nodo.get("processedAt"),
        "cancelled_at": nodo.get("cancelledAt"),
        "cancel_reason": _minuscula(nodo.get("cancelReason")),
        "financial_status": _minuscula(nodo.get("displayFinancialStatus")),
        "test": bool(nodo.get("test")),
        "taxes_included": bool(nodo.get("taxesIncluded")),
        "current_total_price": _monto(nodo.get("currentTotalPriceSet")),
        "total_price": _monto(nodo.get("totalPriceSet")),
        "email": nodo.get("email"),
        "contact_email": nodo.get("email"),
        "phone": nodo.get("phone"),
        "note": nodo.get("note"),
        "note_attributes": [
            {"name": a.get("key"), "value": a.get("value")} for a in nodo.get("customAttributes") or []
        ],
        "billing_address": _direccion(nodo.get("billingAddress")),
        "shipping_address": _direccion(nodo.get("shippingAddress")),
        "customer": (
            {
                "id": _legacy(customer.get("legacyResourceId")),
                "first_name": customer.get("firstName"),
                "last_name": customer.get("lastName"),
                "default_address": _direccion(customer.get("defaultAddress")),
            }
            if customer
            else None
        ),
        "line_items": [_linea(li) for li in nodos_lineas],
        "shipping_lines": [_envio(s) for s in ((nodo.get("shippingLines") or {}).get("nodes") or [])],
        FULFILLMENT_KEY: [_bodega(fo) for fo in ((nodo.get("fulfillmentOrders") or {}).get("nodes") or [])],
        "_api": "graphql",
    }


# --------------------------------------------------------------- extracción
def _todas_las_lineas(client: ShopifyClient, nodo: dict[str, Any]) -> list[dict[str, Any]]:
    """Las líneas del pedido; si tenía más de una página, pide las que faltan."""
    conexion = nodo.get("lineItems") or {}
    lineas = list(conexion.get("nodes") or [])
    pagina = conexion.get("pageInfo") or {}
    while pagina.get("hasNextPage"):
        data = client.graphql(MAS_LINEAS_QUERY, {"id": nodo["id"], "after": pagina.get("endCursor")})
        conexion = (data.get("order") or {}).get("lineItems") or {}
        lineas.extend(conexion.get("nodes") or [])
        pagina = conexion.get("pageInfo") or {}
    return lineas


def _avisar_bodegas_incompletas(nodo: dict[str, Any], nombre: str) -> None:
    """
    Si el pedido tiene más grupos de bodega (o más líneas por grupo) de los que trae la
    consulta, algunas líneas saldrían sin bodega (alerta ``SIN_BODEGA``). Se deja aviso.
    """
    grupos = (nodo.get("fulfillmentOrders") or {}).get("nodes") or []
    if len(grupos) >= BODEGAS_POR_PEDIDO or any(
        ((g.get("lineItems") or {}).get("pageInfo") or {}).get("hasNextPage") for g in grupos
    ):
        logger.warning("%s: demasiados grupos o líneas de bodega; revisar las alertas SIN_BODEGA.", nombre)


def extract_orders_graphql(
    client: ShopifyClient, flt: OrderFilter, por_pagina: int = PEDIDOS_POR_PAGINA
) -> Iterator[dict[str, Any]]:
    """Generador de pedidos en formato REST. Deduplica por ``id`` como salvaguarda."""
    variables: dict[str, Any] = {"first": por_pagina, "after": None, "query": search_query(flt)}
    vistos: set[int] = set()
    while True:
        try:
            data = client.graphql(ORDERS_QUERY, variables)
        except ShopifyCostoExcedidoError:
            if variables["first"] == 1:
                raise
            variables["first"] = max(1, variables["first"] // 2)
            logger.info(
                "Consulta GraphQL demasiado costosa: se baja a %d pedidos por página.", variables["first"]
            )
            continue
        conexion = data.get("orders") or {}
        for nodo in conexion.get("nodes") or []:
            pedido = a_formato_rest(nodo, _todas_las_lineas(client, nodo))
            if pedido["id"] in vistos:
                continue
            vistos.add(pedido["id"])
            _avisar_bodegas_incompletas(nodo, pedido["name"])
            yield pedido
        pagina = conexion.get("pageInfo") or {}
        if not pagina.get("hasNextPage"):
            return
        variables["after"] = pagina.get("endCursor")
