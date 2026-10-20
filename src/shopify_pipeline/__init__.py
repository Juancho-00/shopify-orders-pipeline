"""
shopify_pipeline
================

Pipeline de integración Shopify → Siesa.

Fases:
    1. Extracción de pedidos desde Shopify y reporte   (``shopify``, ``transform``)
    2. Conciliación de pedidos contra Siesa            (``reconciliation``)
    3. Plantillas de clientes y pedidos para Siesa     (``erp``)
"""

__version__ = "0.3.0"  # Las 3 fases construidas; falta la primera corrida con Shopify real.
