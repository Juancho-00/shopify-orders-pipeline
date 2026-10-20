# Catálogos de equivalencias Shopify → Siesa

Tablas que traducen datos de Shopify a los códigos que exige Siesa. Se editan a mano
cuando cambia algo en Shopify o en Siesa; el pipeline las lee en cada corrida.

| Archivo | Columnas | Qué traduce | Regla |
|---|---|---|---|
| `bodegas_siesa.csv` | `bodega_shopify`, `codigo_siesa`, `descripcion_siesa`, `tipo_docto_siesa` | Nombre de la ubicación en Shopify → código de bodega Siesa y tipo de documento del pedido (`CPW`, `CPT`, `CPM`) | R-09 |
| `ciudades_siesa.csv` | `codigo`, `descripcion` | Departamento + ciudad del cliente → código Siesa (`169` + DANE) | R-11 |

**Bodegas:** el nombre debe coincidir con el de Shopify (no importan mayúsculas, tildes
ni espacios de más). Si Shopify crea una ubicación nueva, hay que agregar aquí su fila; mientras
no exista, los pedidos de esa bodega quedan con la alerta `BODEGA_SIN_EQUIVALENCIA`.
`tipo_docto_siesa` = `NO_CARGA` marca las bodegas cuyos pedidos **no van a Siesa** (las 4 de
vending): quedan fuera de las plantillas y de la conciliación. Si una bodega nueva queda con
`tipo_docto_siesa` vacío, sus pedidos no entran en la plantilla (`TIPO_DOCTO_SIN_EQUIVALENCIA`)
hasta que se le asigne `CPW`, `CPT`, `CPM` o `NO_CARGA`.

**Ciudades:** copia de la tabla oficial de Siesa. Códigos de 3 dígitos = país, de 5 =
departamento, de 8 = ciudad.

Para cambiar la carpeta de catálogos sin tocar el código: variable de entorno
`SIESA_CATALOGOS_DIR`.
