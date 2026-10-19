# Mapeo Shopify → Siesa (fase 1)

Origen de cada columna del reporte `pedidos_siesa_<run_id>.csv / .xlsx`.
Validado contra el pedido de prueba **#1006** (8-oct-2026).

**Formato:** una fila por producto, más una fila de envío cuando el envío cobrado es mayor a
cero. Los datos del cliente y del pedido se repiten en cada fila.

**Qué pedidos entran:** solo los de pago confirmado, sin cancelar y que no sean de prueba
(ver *Exclusiones*). Las alertas y exclusiones quedan en el log, no en el reporte.

**Orden de búsqueda de la dirección:** se toma `billing_address` (facturación). Si viene
vacía, `shipping_address` (envío). Si también falta, `customer.default_address`. Se usa
una sola dirección completa; no se mezclan campos de varias.

## Datos del cliente

| Columna | Requerimiento | Campo en Shopify | Regla |
|---|---|---|---|
| `primer_nombre` | Nombre (primer) | `billing_address.first_name` | Primera palabra |
| `segundo_nombre` | Nombre (segundo) | `billing_address.first_name` | Resto de palabras (`"Juan Pablo"` → `Pablo`) |
| `primer_apellido` | Apellido uno | `billing_address.last_name` | Primer apellido; respeta partículas (`"De la Torre"`) |
| `segundo_apellido` | Apellido dos | `billing_address.last_name` | Resto (`"Lozano Gutierrez"` → `Gutierrez`) |
| `tipo_documento` | Documento (CC o NIT) | `billing_address.company` | Código Siesa: `C` = cédula, `N` = NIT (R-10). Ver *Reglas de documento* |
| `numero_documento` | Número de documento | `billing_address.company` → respaldo `shipping_address.company` | Solo dígitos (quita puntos, espacios y prefijos) |
| `digito_verificacion` | — | Calculado | Solo NIT: el escrito por el cliente o calculado con el algoritmo de la DIAN |
| `direccion` | Dirección | `address1` | |
| `direccion_complemento` | — | `address2` | Apto, torre, referencias (campo aparte en la plantilla de Siesa) |
| `ciudad` | — | `city` | Texto, como lo escribió el cliente |
| `departamento` | — | `province` | Texto |
| `codigo_ciudad_siesa` | Ciudad | `city` + `province_code` | `169` + DANE (`16905001` = Medellín), con `catalogos/ciudades_siesa.csv` (R-11). Si no se encuentra: alerta `CIUDAD_SIN_CODIGO` |
| `codigo_postal` | Código postal | `zip` | |
| `pais` | — | `country_code` | `CO` |
| `telefono` | Teléfono | `billing.phone` → `shipping.phone` → `order.phone` → `customer.phone` | 10 dígitos, sin `+57` |
| `email` | Email | `order.email` → `contact_email` → `customer.email` | |
| `fecha_compra` | Fecha de compra | `processed_at` | Hora Colombia, `AAAA-MM-DD HH:MM:SS` |

### Reglas de documento (campo `company`) — R-06

Si el cliente escribe el tipo (`CC`, `NIT`, `CE`...) o el guion del DV, se respeta. Si solo
escribe el número, el tipo se deduce por el formato:

| Número | Resultado |
|---|---|
| 9 dígitos que empiezan por `800`, `900` o `901` | NIT, DV calculado (≈95 % de los NIT) |
| 9 dígitos que empiezan por otro 8 o 9 | NIT, DV calculado, alerta `NIT_POR_VERIFICAR` |
| 7 u 8 dígitos | CC (cédulas antiguas) |
| 10 dígitos | CC (cédulas nuevas, p. ej. `1152469156`) |
| 10 dígitos = NIT con prefijo `800`/`900`/`901` + DV válido pegado | NIT (`9001234567` → `900123456`, DV `7`) |
| Cualquier otro largo o prefijo | Sin tipo, alerta `TIPO_DOCUMENTO_NO_IDENTIFICADO` |

| Lo que escribe el cliente | Resultado |
|---|---|
| `1.152.469.156` | CC `1152469156` |
| `CC 43123456`, `C.C. 43.123.456` | CC `43123456` |
| `900123456-7`, `NIT 900.123.456` | NIT `900123456`, DV escrito o calculado |
| `CE 123456` | CE, alerta `TIPO_DOCUMENTO_SIN_CODIGO_SIESA` (código Siesa pendiente) |
| Vacío | Alerta `SIN_DOCUMENTO` |
| Menos de 5 o más de 11 dígitos | Alerta `DOCUMENTO_INVALIDO` |
| DV escrito distinto al calculado | Alerta `DV_NIT_INVALIDO` |

La regla está aislada en `parse_documento` / `tipo_por_formato` (`transform/normalize.py`).

## Datos del pedido

| Columna | Requerimiento | Campo en Shopify | Regla |
|---|---|---|---|
| `documento_referencia` | Documento de referencia (enlace Siesa ↔ Shopify) | `order_number` | Consecutivo numérico: `1006` |
| `pedido_shopify` | — | `name` | `#1006`, como se ve en el admin de Shopify |
| `id_pedido_shopify` | — | `id` | ID interno; llave técnica para la conciliación (fase 2) |
| `fecha_creacion` | Fecha de creación | `created_at` | Hora Colombia |
| `estado_pago` | — | `financial_status` | `pending` (contraentrega), `paid`, `refunded`... |
| `notas` | Notas adicionales | `note` + `note_attributes` | Unidos con ` \| `, sin saltos de línea |

## Datos de cada línea

| Columna | Requerimiento | Producto | Envío |
|---|---|---|---|
| `tipo_linea` | — | `PRODUCTO` | `ENVIO` |
| `referencia` | Referencia o código del producto | `line_items[].sku` | `SERV01` (R-08; configurable con `SIESA_CODIGO_ENVIO`) |
| `descripcion` | — | `line_items[].name` | `shipping_lines[].title` |
| `bodega` / `id_bodega_shopify` | Bodega de salida | `fulfillment_orders[].assigned_location` (llamada extra por pedido) | La del primer producto |
| `bodega_siesa` | Bodega Siesa | `bodega` traducida con `catalogos/bodegas_siesa.csv` (R-09). Sin equivalencia: alerta `BODEGA_SIN_EQUIVALENCIA` | La del primer producto |
| `cantidad` | Cantidad ordenada | `current_quantity` (o `quantity`) | `1` |
| `precio_unitario` | Precio unitario del ítem | `line_items[].price` | `shipping_lines[].price` |
| `descuento_linea` | — | Suma de `discount_allocations`; con reembolso parcial, prorrateada: `descuento × current_quantity / quantity` (informativo) | `price − discounted_price` |
| `precio_neto` | **Precio que se sube a Siesa** | `(precio_unitario × cantidad − descuento) / cantidad` (R-13) | `discounted_price` |
| `valor_total_linea` | — | `precio_neto × cantidad` | Igual a `precio_neto` |

Todos los valores de dinero van en **pesos enteros**, redondeados al peso más cercano (R-23).
| `tasa_iva` | — | Suma de `tax_lines[].rate` | `tax_lines`; si viene vacío, `0.19` (R-07) |
| `precio_incluye_iva` | — | `taxes_included` | Ídem |

**Regla del envío:** se agrega la línea solo si el valor cobrado (`discounted_price`) es mayor a
cero y la línea no fue eliminada (`is_removed`). Un envío gratis por descuento no genera línea.

**Precios con IVA incluido (R-07):** el precio del producto y el del envío se envían tal
como los cobra Shopify, con IVA incluido. Ejemplo #1006: producto $89.999 (base $75.629,41 +
IVA $14.369,59). En Siesa el envío (`SERV01`) lleva IVA; como el valor web ya lo incluye, no
se transforma. Shopify no desglosa ese IVA (`tax_lines` vacío), por eso el reporte pone `0.19`.

**Sin descuentos ni decimales (R-13, R-23):** Siesa no recibe descuentos, así que se sube
`precio_neto`: lo que pagó el cliente por unidad, redondeado a pesos. El total del
pedido se valida contra Shopify con una tolerancia de **$50** (R-24) para absorber ese
redondeo; una diferencia mayor genera `TOTAL_NO_CUADRA`.

## Exclusiones

Los pedidos excluidos no aparecen en el reporte, pero quedan registrados en el log de
alertas (`tipo = EXCLUIDO`) con su motivo.

| Caso | Código en el log | Por defecto | Para incluirlo |
|---|---|---|---|
| Pago no confirmado (`financial_status` distinto de `paid` o `partially_refunded`) | `PAGO_NO_CONFIRMADO` | Excluido | `--estados-pago todos` o lista propia |
| Pedido cancelado (`cancelled_at`) | `CANCELADO` | Excluido | `--incluir-cancelados` |
| Pedido de prueba (`test = true`) | `PRUEBA` | Excluido | `--incluir-pruebas` |
| Línea con cantidad actual 0 (eliminada o reembolsada) | — | Omitida | — |

**Pago confirmado (definido 2026-10-14):** se extraen todos los pedidos, pero al reporte
para Siesa solo pasan los de estado `paid` (pagado) y `partially_refunded` (pagado con
reembolso parcial). Un pedido contraentrega queda en `pending` hasta que se registra el cobro.

**Pedidos que se pagan días después:** si la extracción filtra por fecha de creación, un
pedido creado el lunes y pagado el jueves solo se lee el lunes (cuando aún está pendiente)
y no vuelve a entrar. Para capturarlo, la extracción programada debe usar
`--filtrar-por actualizacion`: marcar el pago actualiza el pedido y lo trae en la ventana
del día del pago. La fase 2 (conciliación) evitará cargar dos veces un pedido que ya
exista en Siesa.

## Log de alertas

Las alertas no van en el reporte: cada corrida escribe `data/logs/alertas_<run_id>.csv`, con
una fila por evento. El log no incluye datos personales del cliente.

| Columna | Contenido |
|---|---|
| `tipo` | `ALERTA` (el pedido pasa, pero con un dato a revisar) o `EXCLUIDO` (el pedido no pasa) |
| `codigo` / `descripcion` | Código y explicación (tabla siguiente) |
| `pedido_shopify` / `documento_referencia` | `#1006` / `1006` |
| `numero_linea` / `referencia` | Solo en alertas de una línea específica |
| `detalle` | Dato de apoyo: estado de pago, diferencia de totales, motivo de cancelación |

| Código | Nivel | Significado |
|---|---|---|
| `SIN_DOCUMENTO` | Pedido | El cliente no registró cédula/NIT en `company` |
| `DOCUMENTO_INVALIDO` | Pedido | El documento no tiene entre 5 y 11 dígitos |
| `DV_NIT_INVALIDO` | Pedido | El dígito de verificación escrito no coincide con el calculado |
| `NIT_POR_VERIFICAR` | Pedido | 9 dígitos que empiezan por 8 o 9, pero no por 800/900/901 |
| `TIPO_DOCUMENTO_NO_IDENTIFICADO` | Pedido | El número no tiene formato de CC ni de NIT (R-06) |
| `TIPO_DOCUMENTO_SIN_CODIGO_SIESA` | Pedido | CE o pasaporte: Siesa aún no tiene código definido |
| `CIUDAD_SIN_CODIGO` | Pedido | La ciudad no se encontró en la tabla de Siesa; el detalle muestra ciudad / departamento |
| `SIN_NOMBRE` / `SIN_APELLIDO` / `SIN_DIRECCION` / `SIN_TELEFONO` / `SIN_EMAIL` | Pedido | Dato del cliente faltante |
| `TOTAL_NO_CUADRA` | Pedido | La suma de las líneas difiere más de $50 del total de Shopify |
| `PEDIDO_CANCELADO` | Pedido | Solo con `--incluir-cancelados` |
| `SIN_SKU` | Línea | Producto sin referencia: no se puede crear en Siesa |
| `SIN_BODEGA` | Línea | Shopify no tiene la línea asignada a ninguna bodega |
| `BODEGA_SIN_EQUIVALENCIA` | Línea | La bodega de Shopify no está en `catalogos/bodegas_siesa.csv` |
| `BODEGA_NO_CONSULTADA` | Línea | Se ejecutó con `--sin-bodega` o falta el permiso para consultar bodegas |
| `PAGO_NO_CONFIRMADO` / `CANCELADO` / `PRUEBA` | Exclusión | Ver *Exclusiones* |
| `YA_REPORTADO` | Exclusión | El pedido ya salió en el reporte de otra corrida (ventanas solapadas); no se repite |
| `CAMBIO_POST_REPORTE` | Exclusión | Ya se reportó, pero su total cambió después (p. ej. un reembolso): revisar a mano en Siesa |
| `DATOS_INCOMPLETOS` | Exclusión | Al pedido le faltan campos críticos (extracción con `--fields`) |
| `ERROR_TRANSFORMACION` | Exclusión | Un dato del pedido no se pudo procesar; la traza queda en la bitácora. Los demás pedidos siguen |

Además, cada ejecución queda en la bitácora `data/logs/shopify_pipeline_AAAAMMDD.log`
(inicio, ventana consultada, conteos, resumen de alertas y errores).

## Decisiones tomadas

- [x] Precios con IVA incluido, sin transformación adicional (2026-10-14).
- [x] Solo pedidos con pago confirmado pasan a Siesa (2026-10-14).
- [x] Pedidos cancelados y de prueba excluidos (2026-10-14).
- [x] Alertas en un log aparte, fuera del reporte (2026-10-14).
- [x] Reglas R-06 a R-13 (2026-10-19): tipo de documento por formato, envío `SERV01` con
  IVA, bodegas y ciudades con código Siesa, `C`/`N`, referencia = número sin `#`, precio
  neto sin descuento. Detalle en [reglas_negocio.md](reglas_negocio.md).

## Pendiente de definir

- [ ] Código Siesa de cédula de extranjería y pasaporte (pregunta P-5 de
  [plantillas_siesa.md](plantillas_siesa.md)).
