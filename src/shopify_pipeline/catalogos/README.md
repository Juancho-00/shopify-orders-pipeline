# Catálogos de equivalencias Shopify → Siesa

Tablas que traducen datos de Shopify a los códigos que exige Siesa. Se editan a mano
cuando cambia algo en Shopify o en Siesa; el pipeline las lee en cada corrida.

| Archivo | Columnas | Qué traduce | Regla |
|---|---|---|---|
| `bodegas_siesa.csv` | `bodega_shopify`, `codigo_siesa`, `descripcion_siesa` | Nombre de la ubicación en Shopify → código de bodega Siesa | R-09 |
| `ciudades_siesa.csv` | `codigo`, `descripcion` | Departamento + ciudad del cliente → código Siesa (`169` + DANE) | R-11 |

**Bodegas:** el nombre debe coincidir con el de Shopify (no importan mayúsculas, tildes
ni espacios de más). Si Shopify crea una ubicación nueva, hay que agregar aquí su fila; mientras
no exista, los pedidos de esa bodega quedan con la alerta `BODEGA_SIN_EQUIVALENCIA`.

**Ciudades:** copia de la tabla oficial de Siesa. Códigos de 3 dígitos = país, de 5 =
departamento, de 8 = ciudad.

Para cambiar la carpeta de catálogos sin tocar el código: variable de entorno
`SIESA_CATALOGOS_DIR`.
