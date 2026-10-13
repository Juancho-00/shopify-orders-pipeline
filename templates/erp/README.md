# Plantillas del ERP (fase 3)

Aquí van las plantillas de carga del ERP para **clientes** y **pedidos**.

Los archivos de esta carpeta (excepto este README) están en `.gitignore` porque
pueden contener datos reales. La especificación de cada plantilla se documenta en
`docs/` y se valida en código, así que no hace falta versionar los archivos originales.

Por cada columna de cada plantilla se necesita:

| Dato | Ejemplo |
|---|---|
| Nombre de la columna | `NIT_CLIENTE` |
| Tipo de dato | texto, entero, decimal, fecha (formato) |
| Longitud máxima / precisión | 20 caracteres; 2 decimales |
| ¿Obligatoria? | sí / no |
| Origen en Shopify o valor fijo | `order.customer.email`, constante `"001"` |
| Reglas | mayúsculas, sin tildes, catálogo de valores permitidos |
