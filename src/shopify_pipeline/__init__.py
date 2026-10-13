"""
shopify_pipeline
================

Pipeline de integración Shopify → ERP.

Fases:
    1. Extracción de pedidos desde Shopify           (``shopify_pipeline.shopify``)  ✅
    2. Conciliación de pedidos Shopify vs. ERP        (``shopify_pipeline.reconciliation``)  ⏳
    3. Creación de clientes y pedidos en el ERP       (``shopify_pipeline.erp``)  ⏳
"""

__version__ = "0.1.0"
