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

COSTO DE LA CONSULTA (dos límites distintos)
    1. Costo *solicitado* (``requestedQueryCost``): Shopify lo calcula ANTES de ejecutar,
       multiplicando los ``first:`` anidados, y una petición no puede pasar de 1.000 puntos.
       Por eso las conexiones anidadas piden pocos elementos (``LINEAS_POR_PAGINA``,
       ``BODEGAS_POR_PEDIDO``, ``LINEAS_POR_BODEGA``): casi todos los pedidos tienen 1-3
       líneas y una bodega, y lo que desborde se trae con consultas aparte. Con nodos
       pequeños caben más pedidos por página → menos peticiones (menos latencia).
    2. Costo *real* (``actualQueryCost``): lo que se descuenta del balde (≈40 puntos por
       pedido; el balde se recupera a ~100 puntos/s en planes estándar). Ese costo fija el
       ritmo máximo sostenido, sin importar el tamaño de página. El cliente HTTP frena antes
       de agotar el balde (``client._frenar_por_costo``).

    El tamaño de página se ajusta solo (``siguiente_tamano``) con el costo solicitado de la
    página anterior; si aun así Shopify responde ``MAX_COST_EXCEEDED``, se achica a la mitad.

PEDIDOS CON DATOS INESPERADOS
    Si un pedido llega con una estructura que no se puede convertir, se descarta ESE pedido
    (queda en ``EstadisticasGraphQL.rechazados``) y la extracción sigue. Como lo extraído ya
    no cuadra con el conteo de Shopify, el watermark no avanza y la próxima corrida lo
    vuelve a intentar: no se pierde en silencio.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from shopify_pipeline.exceptions import ShopifyCostoExcedidoError
from shopify_pipeline.shopify.client import ShopifyClient
from shopify_pipeline.shopify.fulfillment import FULFILLMENT_KEY
from shopify_pipeline.shopify.orders import OrderFilter

logger = logging.getLogger(__name__)

PEDIDOS_POR_PAGINA = 8  # Tamaño inicial; después se ajusta con el costo real de Shopify.
MAX_PEDIDOS_POR_PAGINA = 50
COSTO_OBJETIVO = 900  # Costo solicitado al que se apunta por página (tope de Shopify: 1.000).
LINEAS_POR_PAGINA = 5  # Un pedido con más líneas trae el resto aparte (MAS_LINEAS_QUERY).
BODEGAS_POR_PEDIDO = 2  # Grupos de despacho por pedido; normalmente 1. El resto: MAS_BODEGAS_QUERY.
LINEAS_POR_BODEGA = 5  # Líneas por grupo de despacho. El resto: MAS_LINEAS_BODEGA_QUERY.
MAS_POR_PAGINA = 50  # Tamaño de página de las consultas de desborde.

_DINERO = "shopMoney { amount }"
_DIRECCION = "firstName lastName company address1 address2 city province provinceCode zip countryCodeV2 phone"
_LINEA = f"""
    id sku name title quantity currentQuantity
    originalUnitPriceSet {{ {_DINERO} }}
    totalDiscountSet {{ {_DINERO} }}
    discountAllocations {{ allocatedAmountSet {{ {_DINERO} }} }}
    taxLines {{ rate }}
"""
_LINEA_BODEGA = "totalQuantity lineItem { id }"


def _bodega_campos(lineas: int) -> str:
    return f"""
        id status
        assignedLocation {{ name location {{ legacyResourceId }} }}
        lineItems(first: {lineas}) {{
          pageInfo {{ hasNextPage endCursor }}
          nodes {{ {_LINEA_BODEGA} }}
        }}
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
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {_bodega_campos(LINEAS_POR_BODEGA)} }}
      }}
    }}
  }}
}}
"""

MAS_LINEAS_QUERY = f"""
query MasLineas($id: ID!, $after: String) {{
  order(id: $id) {{
    lineItems(first: {MAS_POR_PAGINA}, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ {_LINEA} }}
    }}
  }}
}}
"""

MAS_BODEGAS_QUERY = f"""
query MasBodegas($id: ID!, $after: String) {{
  order(id: $id) {{
    fulfillmentOrders(first: 10, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ {_bodega_campos(MAS_POR_PAGINA)} }}
    }}
  }}
}}
"""

MAS_LINEAS_BODEGA_QUERY = f"""
query MasLineasBodega($id: ID!, $after: String) {{
  fulfillmentOrder(id: $id) {{
    lineItems(first: {MAS_POR_PAGINA}, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ {_LINEA_BODEGA} }}
    }}
  }}
}}
"""

COUNT_QUERY = """
query Conteo($query: String) {
  ordersCount(query: $query, limit: null) { count precision }
}
"""


@dataclass
class EstadisticasGraphQL:
    """Lo que pasó en la extracción, para el manifiesto y las métricas de la bitácora."""

    paginas: int = 0
    costo_solicitado: float = 0.0
    costo_real: float = 0.0
    segundos_api: float = 0.0
    # Pedidos descartados por payload inesperado: identificador y error, nunca datos del cliente.
    rechazados: list[dict[str, Any]] = field(default_factory=list)


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


def siguiente_tamano(actual: int, costo_solicitado: Any) -> int:
    """
    Pedidos por página para que la próxima consulta cueste ~``COSTO_OBJETIVO`` puntos.

    El costo solicitado crece en proporción a ``first``; con el de la página anterior se
    estima el costo por pedido. Sube o baja según lo que reporta Shopify.
    """
    try:
        costo = float(costo_solicitado)
    except (TypeError, ValueError):
        return actual
    if costo <= 0:
        return actual
    por_pedido = costo / max(actual, 1)
    return max(1, min(MAX_PEDIDOS_POR_PAGINA, int(COSTO_OBJETIVO // por_pedido)))


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


def a_formato_rest(
    nodo: dict[str, Any],
    lineas: list[dict[str, Any]] | None = None,
    bodegas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Pedido de GraphQL → diccionario con los nombres de la REST API que usa la transformación.

    ``lineas`` y ``bodegas`` permiten pasar las listas completas cuando el pedido tenía más
    de una página de líneas o de grupos de despacho.
    """
    customer = nodo.get("customer") or None
    nodos_lineas = lineas if lineas is not None else ((nodo.get("lineItems") or {}).get("nodes") or [])
    nodos_bodegas = (
        bodegas if bodegas is not None else ((nodo.get("fulfillmentOrders") or {}).get("nodes") or [])
    )
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
        FULFILLMENT_KEY: [_bodega(fo) for fo in nodos_bodegas],
        "_api": "graphql",
    }


# --------------------------------------------------------------- desbordes
def _paginar_conexion(
    client: ShopifyClient,
    conexion: dict[str, Any] | None,
    query: str,
    raiz: str,
    campo: str,
    gid: str,
) -> list[dict[str, Any]]:
    """
    Nodos de una conexión anidada; si traía más páginas, pide las que faltan.

    ``raiz``/``campo`` indican dónde viene la conexión en la respuesta de ``query``
    (p. ej. ``order`` → ``lineItems``).
    """
    conexion = conexion or {}
    nodos = list(conexion.get("nodes") or [])
    pagina = conexion.get("pageInfo") or {}
    while pagina.get("hasNextPage"):
        data = client.graphql(query, {"id": gid, "after": pagina.get("endCursor")})
        conexion = (data.get(raiz) or {}).get(campo) or {}
        nodos.extend(conexion.get("nodes") or [])
        pagina = conexion.get("pageInfo") or {}
    return nodos


def _todas_las_lineas(client: ShopifyClient, nodo: dict[str, Any]) -> list[dict[str, Any]]:
    """Las líneas del pedido; si tenía más de una página, pide las que faltan."""
    return _paginar_conexion(
        client, nodo.get("lineItems"), MAS_LINEAS_QUERY, "order", "lineItems", nodo["id"]
    )


def _todas_las_bodegas(client: ShopifyClient, nodo: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Los grupos de despacho del pedido, cada uno con TODAS sus líneas. Antes, si un pedido
    tenía más grupos o líneas de las que traía la consulta, esas líneas salían sin bodega.
    """
    grupos = _paginar_conexion(
        client, nodo.get("fulfillmentOrders"), MAS_BODEGAS_QUERY, "order", "fulfillmentOrders", nodo["id"]
    )
    return [
        grupo
        | {
            "lineItems": {
                "nodes": _paginar_conexion(
                    client,
                    grupo.get("lineItems"),
                    MAS_LINEAS_BODEGA_QUERY,
                    "fulfillmentOrder",
                    "lineItems",
                    grupo["id"],
                )
            }
        }
        for grupo in grupos
    ]


# --------------------------------------------------------------- extracción
# Errores de datos al convertir un pedido. Los de red o de Shopify NO están aquí: esos los
# reintenta el cliente HTTP y, si persisten, deben detener la corrida.
_ERRORES_DE_PAYLOAD = (KeyError, TypeError, ValueError, AttributeError, IndexError)


def _convertir(client: ShopifyClient, nodo: Any, stats: EstadisticasGraphQL) -> dict[str, Any] | None:
    """Convierte un pedido aislado: si su estructura es inesperada, lo descarta y lo anota."""
    try:
        return a_formato_rest(nodo, _todas_las_lineas(client, nodo), _todas_las_bodegas(client, nodo))
    except _ERRORES_DE_PAYLOAD as exc:
        es_dict = isinstance(nodo, dict)
        rechazado = {
            "pedido": nodo.get("name") if es_dict else None,
            "gid": nodo.get("id") if es_dict else None,
            "error": f"{type(exc).__name__}: {exc}"[:300],
        }
        stats.rechazados.append(rechazado)
        logger.error(
            "Pedido %s descartado: payload inesperado (%s).", rechazado["pedido"], rechazado["error"]
        )
        return None


def extract_orders_graphql(
    client: ShopifyClient,
    flt: OrderFilter,
    por_pagina: int = PEDIDOS_POR_PAGINA,
    stats: EstadisticasGraphQL | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Generador de pedidos en formato REST (memoria constante: una página a la vez).
    Deduplica por ``id`` como salvaguarda. ``stats`` acumula páginas, costo y rechazados.
    """
    stats = stats if stats is not None else EstadisticasGraphQL()
    variables: dict[str, Any] = {"first": por_pagina, "after": None, "query": search_query(flt)}
    vistos: set[int] = set()
    while True:
        t0 = time.perf_counter()
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
        segundos = time.perf_counter() - t0
        # Se copia ya: las consultas de desborde (líneas, bodegas) lo sobrescriben.
        costo = dict(client.ultimo_costo)
        conexion = data.get("orders") or {}
        nodos = conexion.get("nodes") or []

        stats.paginas += 1
        stats.segundos_api += segundos
        stats.costo_solicitado += float(costo.get("requestedQueryCost") or 0)
        stats.costo_real += float(costo.get("actualQueryCost") or 0)
        disponible = (costo.get("throttleStatus") or {}).get("currentlyAvailable")
        logger.debug(
            "lote=%d pedidos=%d first=%d costo_solicitado=%s costo_real=%s disponibles=%s seg=%.2f",
            stats.paginas,
            len(nodos),
            variables["first"],
            costo.get("requestedQueryCost"),
            costo.get("actualQueryCost"),
            disponible,
            segundos,
        )

        for nodo in nodos:
            pedido = _convertir(client, nodo, stats)
            if pedido is None or pedido["id"] in vistos:
                continue
            vistos.add(pedido["id"])
            yield pedido
        pagina = conexion.get("pageInfo") or {}
        if not pagina.get("hasNextPage"):
            return
        variables["after"] = pagina.get("endCursor")
        variables["first"] = siguiente_tamano(variables["first"], costo.get("requestedQueryCost"))
