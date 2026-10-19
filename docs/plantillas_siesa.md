# Plantillas de carga a Siesa (fase 3)

Estructura de las dos plantillas Excel que se suben a Siesa, analizada a partir de los
ejemplos del conector VTEX (`terceros_vtex.xlsx` y `pedidos_conector_*.xlsx`).

> **Estado:** solo análisis. El generador todavía no está implementado. Las preguntas
> de la sección final se resuelven con la regla **R-32**, cuando lleguemos a llenar
> las plantillas.
>
> Los ejemplos originales tienen datos reales de clientes y **no se guardan en el
> repositorio**. Los valores de este documento son fijos de la plantilla o ficticios.

## Orden de carga (R-30, R-31)

1. **Plantilla de clientes** (`terceros_*.xlsx`): con 4 hojas. Se sube **siempre** con
   cada pedido, aunque el cliente ya exista, porque sus datos pueden cambiar (R-31).
2. **Plantilla de pedidos** (`pedidos_*.xlsx`): con 2 hojas (encabezado y movimientos).

Si al pedido le falta un dato obligatorio, ese pedido **no se sube** (R-34). Queda en
el log de alertas.

Convenciones para todas las hojas:

- **Formato de celda texto (`@`).** Muchas columnas lo tienen. El generador debe escribir
  esos valores como texto para conservar los ceros a la izquierda (`001`, `03D`, `06`).
- **Fechas** en formato `AAAAMMDD`, escritas como texto.
- **Valores de dinero** en pesos enteros, sin decimales ni separadores (R-23).
- **Columna `Origen`** de las tablas: de dónde sale cada dato.
  - **Fijo:** valor constante de la plantilla (R-33).
  - **Reporte:** columna del reporte `pedidos_siesa_*.csv` de la fase 1.
  - **Derivado:** se calcula a partir del reporte.

---

## Plantilla 1: clientes (`terceros_*.xlsx`)

### Hoja `Terceros`: datos maestros del tercero (tabla F200 + contacto F015)

| Columna | Origen | Valor / regla |
|---|---|---|
| `F200_ID` | Reporte | `numero_documento` (sin DV) |
| `F200_NIT` | Reporte | `numero_documento` (igual a `F200_ID`) |
| `F200_ID_TIPO_IDENT` | Reporte | `tipo_documento`: `C` = cédula, `N` = NIT (R-10) |
| `F200_IND_TIPO_TERCERO` | Fijo* | `1` = persona natural. *¿Qué valor lleva un NIT? (P-1)* |
| `F200_RAZON_SOCIAL` | — | Vacío para personas. *¿Qué lleva para un NIT? (P-1)* |
| `F200_APELLIDO1` | Reporte | `primer_apellido` en MAYÚSCULAS |
| `F200_APELLIDO2` | Reporte | `segundo_apellido` en MAYÚSCULAS (puede ir vacío) |
| `F200_NOMBRES` | Reporte | `primer_nombre` + `segundo_nombre` en MAYÚSCULAS |
| `F015_CONTACTO` | Derivado | `APELLIDO1 NOMBRES` (p. ej. `PEREZ ANA`) |
| `F015_DIRECCION1` | Reporte | `direccion` (línea 1 de Shopify) |
| `F015_DIRECCION2` | — | Vacío en el ejemplo |
| `F015_DIRECCION3` | Reporte | Complemento de dirección (`address2` de Shopify) |
| `F015_ID_PAIS` | Derivado | `169` (Colombia): primeros 3 dígitos de `codigo_ciudad_siesa` |
| `F015_ID_DEPTO` | Derivado | Dígitos 4-5 de `codigo_ciudad_siesa` (p. ej. `05`) |
| `F015_ID_CIUDAD` | Derivado | Dígitos 6-8 de `codigo_ciudad_siesa` (p. ej. `001`) |
| `F015_ID_BARRIO` | — | Vacío |
| `F015_TELEFONO` | Derivado | `57` + celular de 10 dígitos (12 dígitos en total) |
| `F015_EMAIL` | Reporte | `email` |
| `F200_FECHA_NACIMIENTO` | Derivado* | El ejemplo trae la fecha de carga (Shopify no tiene el dato). *(P-4)* |
| `F015_CELULAR` | Derivado | Igual a `F015_TELEFONO` |

La función `catalogos.partes_ciudad()` hace la división país/depto/ciudad.

### Hoja `Clientes`: el tercero como cliente (tabla F201)

| Columna | Origen | Valor / regla |
|---|---|---|
| `F201_ID_TERCERO` | Reporte | `numero_documento` |
| `F201_ID_SUCURSAL` | Fijo | `001` |
| `F201_DESCRIPCION_SUCURSAL` | Derivado | Igual a `F015_CONTACTO` |
| `F201_ID_VENDEDOR` | Fijo | `W001` |
| `F201_ID_COND_PAGO` | Fijo* | `03D`. *¿Cambia para contraentrega? (P-3)* |
| `F201_ID_TIPO_CLI` | Fijo | `C001` |
| `F201_PORC_MIN_MARGEN` | Fijo | `1` |
| `F201_PORC_MAX_MARGEN` | Fijo | `500` |
| `F015_CONTACTO` | Derivado | `APELLIDO1 NOMBRES` |
| `F015_DIRECCION1` | Reporte | `direccion` |
| `F015_DIRECCION2` | Reporte | Complemento de dirección. Equivale a `F015_DIRECCION3` de la hoja `Terceros` |
| `F015_ID_PAIS` / `F015_ID_DEPTO` / `F015_ID_CIUDAD` | Derivado | Igual que en `Terceros` |
| `F015_ID_BARRIO` | — | Vacío |
| `F015_TELEFONO` | Derivado | `57` + celular |
| `F015_EMAIL` | Reporte | `email` |
| `F201_FECHA_INGRESO` | Derivado | Fecha de la carga, `AAAAMMDD` |
| `f201_id_cobrador` | Fijo | `W001` |
| `f015_celular` | Derivado | `57` + celular |

### Hoja `Imptos y Reten`: clases de impuesto del cliente

Cada cliente lleva **3 filas** fijas:

| `F_TIPO_REG` | `F_ID_TERCERO` | `F_ID_SUCURSAL` | `F_ID_CLASE` | `F_ID_VALOR_TERCERO` |
|---|---|---|---|---|
| `46` | documento | `001` | `1` | `1` |
| `47` | documento | `001` | `1` | `0` |
| `47` | documento | `001` | `41` | `1` |

*Por confirmar si un NIT lleva las mismas clases (P-1).*

### Hoja `Ent. Dinamica Cliente`: dato adicional (entidad dinámica)

| Columna | Origen | Valor / regla |
|---|---|---|
| `f201_id_tercero` | Reporte | `numero_documento` |
| `f201_id_sucursal` | Fijo | `001` |
| `f753_dato_texto` | Reporte | `email` |

---

## Plantilla 2: pedidos (`pedidos_*.xlsx`)

`_consec_docto` une el encabezado con sus movimientos. Es un consecutivo **dentro del
archivo**: 1, 2, 3... Siesa asigna el número real del pedido al cargarlo.

### Hoja `Pedidos`: encabezado, una fila por pedido

| Columna | Origen | Valor / regla |
|---|---|---|
| `_id_co` | Fijo | `001` (centro de operación) |
| `_id_tipo_docto` | Fijo | `CPM` |
| `_consec_docto` | Derivado | 1, 2, 3... por pedido dentro del archivo (número) |
| `_id_fecha(AAAAMMDD)` | Derivado* | El ejemplo trae la fecha de carga. *¿Fecha de compra o de carga? (P-2)* |
| `_ind_backorder` | Fijo | `4` |
| `_id_tercero_fact` | Reporte | `numero_documento` |
| `_id_sucursal_fact` | Fijo | `001` |
| `_id_tercero_rem` | Reporte | `numero_documento` |
| `_id_sucursal_rem` | Fijo | `001` |
| `_id_co_fact` | Fijo | `001` |
| `_fecha_entrega(AAAAMMDD)` | Derivado | Igual a `_id_fecha` en el ejemplo |
| `_num_docto_referencia` | Reporte | `documento_referencia`: número Shopify sin `#` (R-12, R-21) |
| `_id_cond_pago` | Fijo* | `03D` *(P-3)* |
| `_notas` | Reporte | `notas` |
| `_id_punto_envio` | Fijo | `000` |
| `_id_tercero_vendedor` | Fijo | NIT del vendedor de la plantilla (ver archivo de ejemplo) |

### Hoja `Movto Pedidos comercial`: una fila por línea del pedido

| Columna | Origen | Valor / regla |
|---|---|---|
| `_id_co` | Fijo | `001` |
| `_id_tipo_docto` | Fijo | `CPM` |
| `_consec_docto` | Derivado | El mismo del encabezado, **como texto** |
| `_nro_registro` | Reporte | `numero_linea` (1, 2...) |
| `_referencia_item` | Reporte | `referencia` (SKU). El envío usa `SERV01` (R-08) |
| `_id_ext1_COLOR` / `_id_ext2_TALLA` | — | Vacíos |
| `_id_bodega` | Reporte | `bodega_siesa` (R-09). El envío usa la misma bodega que los productos |
| `_id_motivo` | Fijo | `06` |
| `_ind_obsequio` | Fijo | `0` |
| `_id_co_movto` | Fijo | `001` |
| `ccosto_movto` | — | Vacío |
| `_fecha_entrega(AAAAMMDD)` | Derivado | La misma del encabezado |
| `_id_lista_precio` | Fijo | `03` |
| `_id_unidad_medida` | Fijo | `UND` |
| `_cant_pedida_base` | Reporte | `cantidad`, como texto |
| `_precio_unitario` | Reporte | `precio_neto` (con descuento aplicado, pesos enteros, IVA incluido; R-07, R-13), como texto |
| `_ind_impto_asumido` | Fijo | `0` (no liquida) |
| `ind_precio` | Fijo | `2` (liquida con el precio del registro) |

Con `ind_precio = 2`, Siesa usa el precio que enviamos y no el de su lista de precios.
Por eso el reporte manda el precio neto, con el descuento ya aplicado (R-13).

---

## Preguntas abiertas (resolver con R-32)

| # | Pregunta | Afecta |
|---|---|---|
| P-1 | Cliente con **NIT** (empresa): ¿qué valor lleva `F200_IND_TIPO_TERCERO`? ¿Se llena `F200_RAZON_SOCIAL` (con el nombre de la empresa) en lugar de apellidos y nombres? ¿Lleva las mismas clases de impuesto? ¿El DV va en algún campo? | Hojas `Terceros` e `Imptos y Reten` |
| P-2 | `_id_fecha`: ¿fecha de compra en Shopify o fecha de carga a Siesa? ¿`_fecha_entrega` es siempre la misma? | Hojas `Pedidos` y `Movto` |
| P-3 | `_id_cond_pago` = `03D` para todos los pedidos, ¿o los de contraentrega usan otra condición? | Hojas `Pedidos` y `Clientes` |
| P-4 | `F200_FECHA_NACIMIENTO`: ¿se deja la fecha de carga, como el conector VTEX, o se deja vacía? | Hoja `Terceros` |
| P-5 | Cédula de extranjería y pasaporte: ¿qué código de `F200_ID_TIPO_IDENT` usan? Hoy salen con la alerta `TIPO_DOCUMENTO_SIN_CODIGO_SIESA`. | Hoja `Terceros` |
| P-6 | ¿Un archivo por corrida con todos los pedidos, o un archivo por pedido? ¿En qué carpeta los deja el pipeline para que alguien los suba? | Generador |
