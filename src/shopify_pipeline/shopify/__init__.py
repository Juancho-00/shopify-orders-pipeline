"""
Todo lo que habla con la API de Shopify.

    auth.py         de dónde sale el token (estático o Client Credentials)
    client.py       peticiones HTTP: errores, reintentos, límite de llamadas, paginación
    orders.py       filtros de pedidos (ventana de fechas, estado) y descarga de pedidos
    fulfillment.py  bodega de salida de cada producto (una consulta extra por pedido)
"""
