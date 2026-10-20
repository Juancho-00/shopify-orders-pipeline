# Ejemplos de las plantillas de Siesa (solo en local)

Esta carpeta guarda, **solo en el equipo**, los archivos de ejemplo de las plantillas de
carga de Siesa que sirvieron de referencia (por ejemplo `terceros_vtex.xlsx` y
`pedidos_conector_*.xlsx`). Tienen datos reales de clientes, así que todo lo que hay aquí,
excepto este README, está en `.gitignore` y nunca se sube al repositorio.

La especificación de cada columna (origen, valor fijo y regla) ya no está aquí sino en
[`docs/plantillas_siesa.md`](../../docs/plantillas_siesa.md), y la generan
`src/shopify_pipeline/erp/` y el comando `shopify-pipeline plantillas`.

Si Siesa cambia la plantilla, guarde aquí el nuevo ejemplo y actualice
`docs/plantillas_siesa.md` y el código de `erp/`.
