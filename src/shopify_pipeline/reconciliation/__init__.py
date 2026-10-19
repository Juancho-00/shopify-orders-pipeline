"""
Fase 2: conciliación de pedidos Shopify vs. Siesa.

    siesa_export.py  lee el exporte de pedidos de Siesa (Excel/CSV) y saca las referencias
    run.py           cruza los reportes de la fase 1 contra el exporte y escribe el resultado

Llave del cruce: ``documento_referencia`` del reporte (número de pedido Shopify sin ``#``)
contra ``_num_docto_referencia`` de Siesa (reglas R-20 a R-22).
"""
