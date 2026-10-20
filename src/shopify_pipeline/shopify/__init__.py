"""
Todo lo que habla con la API de Shopify.

    auth.py         de dónde sale el token (estático o Client Credentials)
    client.py          peticiones HTTP (GraphQL y REST): errores, reintentos, límite de llamadas
    graphql_orders.py  pedidos con GraphQL: pedido + líneas + bodega en una consulta (por defecto)
    orders.py          filtro de pedidos (ventana de fechas, estado) y descarga REST (respaldo)
    fulfillment.py     bodega por pedido con REST (una consulta extra por pedido; respaldo)

``SHOPIFY_API=rest`` en el ``.env`` vuelve a la API REST.
"""
