"""
Transformación: pedidos crudos de Shopify → reporte para Siesa.

    normalize.py    funciones pequeñas de limpieza (nombres, cédula/NIT, teléfono, fechas, montos)
    siesa_lines.py  convierte un pedido en filas (productos + envío) y decide exclusiones
    alertas.py      catálogo de alertas/exclusiones que van al log
    run.py          lee el JSONL crudo y escribe CSV, Excel y log de alertas
"""
