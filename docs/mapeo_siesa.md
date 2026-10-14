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
| `tipo_documento` | Documento (CC o NIT) | `billing_address.company` | Ver *Reglas de documento* |
| `numero_documento` | Número de documento | `billing_address.company` → respaldo `shipping_address.company` | Solo dígitos (quita puntos, espacios y prefijos) |
| `digito_verificacion` | — | Calculado | Solo NIT: el escrito por el cliente o calculado con el algoritmo de la DIAN |
| `direccion` | Dirección | `address1` + `address2` | Unidos con espacio |
| `ciudad` | — | `city` | Texto (Siesa puede requerir código DANE: pendiente) |
| `departamento` | — | `province` | Texto |
| `codigo_postal` | Código postal | `zip` | |
| `pais` | — | `country_code` | `CO` |
| `telefono` | Teléfono | `billing.phone` → `shipping.phone` → `order.phone` → `customer.phone` | 10 dígitos, sin `+57` |
| `email` | Email | `order.email` → `contact_email` → `customer.email` | |
| `fecha_compra` | Fecha de compra | `processed_at` | Hora Colombia, `AAAA-MM-DD HH:MM:SS` |

### Reglas de documento (campo `company`)

| Lo que escribe el cliente | Resultado |
|---|---|
| `1152469156`, `1.152.469.156` | CC `1152469156` |
| `CC 43123456`, `C.C. 43.123.456` | CC `43123456` |
| `900123456-7`, `NIT 900.123.456` | NIT `900123456`, DV escrito o calculado |
| 9 dígitos que empiezan por 8 o 9 | NIT (rango de empresas de la DIAN), DV calculado, alerta `NIT_POR_VERIFICAR` |
| `CE 123456` | CE (cédula de extranjería) |
| Vacío | Alerta `SIN_DOCUMENTO` |
| Menos de 5 o más de 11 dígitos | Alerta `DOCUMENTO_INVALIDO` |
| DV escrito distinto al calculado | Alerta `DV_NIT_INVALIDO` |

⚠️ **Pendiente de definir.** El tipo de documento se **deduce** porque Shopify solo captura
el número. La regla anterior es provisional; está aislada en `parse_documento`
(`transform/normalize.py`) para cambiarla en un solo lugar cuando se defina.

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
| `referencia` | Referencia o código del producto | `line_items[].sku` | Código configurable (default `ENVIO`) |
| `descripcion` | — | `line_items[].name` | `shipping_lines[].title` |
| `bodega` / `id_bodega_shopify` | Bodega de salida | `fulfillment_orders[].assigned_location` (llamada extra por pedido) | Vacío |
| `cantidad` | Cantidad ordenada | `current_quantity` (o `quantity`) | `1` |
| `precio_unitario` | Precio unitario | `line_items[].price` | `shipping_lines[].discounted_price` |
| `descuento_linea` | — | Suma de `discount_allocations` | `0` |
| `valor_total_linea` | — | `precio × cantidad − descuento` | Igual al precio |
| `tasa_iva` | — | Suma de `tax_lines[].rate` | Ídem |
| `precio_incluye_iva` | — | `taxes_included` | Ídem |

**Regla del envío:** se agrega la línea solo si el valor cobrado (`discounted_price`) es mayor a
cero y la línea no fue eliminada (`is_removed`). Un envío gratis por descuento no genera línea.

**Precios con IVA incluido (definido 2026-10-14):** el precio del producto y el del envío
se envían tal como los cobra Shopify, con IVA incluido; no requieren transformación.
Ejemplo #1006: producto $89.999 (base $75.629,41 + IVA $14.369,59).

⚠️ En el #1006, Shopify **no calculó IVA sobre el envío**: `shipping_lines[].tax_lines` viene
vacío, `tasa_iva` sale en 0 y el IVA total del pedido ($14.369,59) corresponde solo al
producto. Si el envío debe llevar IVA, hay que revisar en Shopify la opción de cobrar
impuestos sobre las tarifas de envío. Si no, Siesa calculará un IVA distinto al de Shopify.

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
| `NIT_POR_VERIFICAR` | Pedido | Clasificado como NIT solo por formato (regla provisional) |
| `SIN_NOMBRE` / `SIN_APELLIDO` / `SIN_DIRECCION` / `SIN_TELEFONO` / `SIN_EMAIL` | Pedido | Dato del cliente faltante |
| `TOTAL_NO_CUADRA` | Pedido | La suma de las líneas no coincide con el total de Shopify |
| `PEDIDO_CANCELADO` | Pedido | Solo con `--incluir-cancelados` |
| `SIN_SKU` | Línea | Producto sin referencia: no se puede crear en Siesa |
| `SIN_BODEGA` | Línea | Shopify no tiene la línea asignada a ninguna bodega |
| `BODEGA_NO_CONSULTADA` | Línea | Se ejecutó con `--sin-bodega` o falta el permiso para consultar bodegas |
| `PAGO_NO_CONFIRMADO` / `CANCELADO` / `PRUEBA` | Exclusión | Ver *Exclusiones* |

Además, cada ejecución queda en la bitácora `data/logs/shopify_pipeline_AAAAMMDD.log`
(inicio, ventana consultada, conteos, resumen de alertas y errores).

## Decisiones tomadas (2026-10-14)

- [x] Precios con IVA incluido, sin transformación adicional.
- [x] Solo pedidos con pago confirmado pasan a Siesa.
- [x] Pedidos cancelados y de prueba excluidos.
- [x] Alertas en un log aparte, fuera del reporte.

## Pendiente de definir

- [ ] **Cómo identificar un NIT.** Regla provisional: prefijo `NIT`, guion con DV, o 9 dígitos
  que inician en 8 o 9 (este último caso queda como `NIT_POR_VERIFICAR`). Lo ideal es que
  Shopify capture el tipo de documento en un campo propio.
- [ ] Si el envío debe llevar IVA (hoy Shopify no lo calcula; ver arriba).
- [ ] Código Siesa de cada bodega de Shopify (tabla de equivalencias por `id_bodega_shopify`).
- [ ] Código del ítem de envío en Siesa (`SIESA_CODIGO_ENVIO`).
- [ ] Códigos de tipo de documento en Siesa (CC, NIT, CE).
- [ ] Si la ciudad debe ir como código DANE.
- [ ] Si `documento_referencia` va como `1006` o con prefijo (p. ej. `SHOP-1006`).
