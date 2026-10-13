"""
Fase 2 (pendiente): conciliación de pedidos Shopify vs. ERP.

Alcance previsto:
    * Leer la última extracción de ``data/raw/shopify/orders`` (usando su manifiesto).
    * Consultar en el ERP los pedidos de la misma ventana.
    * Cruzar por la llave acordada (p. ej. ``order.name`` / ``order.id`` de Shopify
      contra el campo de referencia externa del ERP).
    * Clasificar: en ambos / solo en Shopify (faltantes en ERP) / solo en ERP /
      con diferencias (totales, estado, cliente).
    * Generar el reporte de conciliación en ``data/reconciliation/``.

Información necesaria para implementarla: tipo de ERP y forma de acceso
(API, base de datos, archivo), y el campo del ERP que guarda la referencia de Shopify.
"""
