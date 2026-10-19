# Plantillas de carga a Siesa (fase 3)

Estructura de las dos plantillas Excel que se suben a Siesa, analizada a partir de los
ejemplos del conector VTEX (`terceros_vtex.xlsx` y `pedidos_conector_*.xlsx`).

> **Estado:** la **plantilla de clientes** (4 hojas) está definida e implementada (comando
> `shopify-pipeline plantillas`). La plantilla de pedidos sigue como análisis de la
> plantilla de ejemplo; sus preguntas están al final (regla **R-32**).
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

✅ **Definida por TI el 2026-10-19** e implementada en `src/shopify_pipeline/erp/terceros.py`
(`fila_tercero`). Una fila por cliente: si el mismo cliente compró varias veces en la
corrida, va una sola vez con los datos de su pedido más reciente.

| Columna | Origen | Valor / regla |
|---|---|---|
| `F200_ID` | Reporte | ✅ Número de documento del cliente (`numero_documento`, sin DV) |
| `F200_NIT` | Reporte | ✅ Igual a `F200_ID` |
| `F200_ID_TIPO_IDENT` | Reporte | ✅ `C` = cédula, `N` = NIT (R-10) |
| `F200_IND_TIPO_TERCERO` | Fijo | ✅ Siempre `1` |
| `F200_RAZON_SOCIAL` | Reporte | ✅ Si es `N`: nombre de la empresa, en MAYÚSCULAS. Si es `C`: vacío. *Origen del nombre: P-1b* |
| `F200_APELLIDO1` | Reporte | ✅ `primer_apellido` en MAYÚSCULAS. Vacío si es `N` *(P-1c)* |
| `F200_APELLIDO2` | Reporte | ✅ `segundo_apellido` en MAYÚSCULAS (puede ir vacío) |
| `F200_NOMBRES` | Reporte | ✅ `primer_nombre` + `segundo_nombre` en MAYÚSCULAS |
| `F015_CONTACTO` | Derivado | ✅ Nombre completo (`NOMBRES APELLIDO1 APELLIDO2`) o la razón social si es `N` *(orden: P-1d)* |
| `F015_DIRECCION1` | Reporte | ✅ `direccion` (máx. 40 caracteres). Lo que no cabe sigue en la 2, sin partir palabras |
| `F015_DIRECCION2` | Reporte | ✅ Continuación de la dirección (máx. 40). Si queda libre y el complemento es largo, lo usa el complemento |
| `F015_DIRECCION3` | Reporte | ✅ `direccion_complemento` (apto, torre, referencias; máx. 40) |

Si la dirección y el complemento no caben en los 3 campos (120 caracteres), se corta y el
pedido queda con la alerta `DIRECCION_TRUNCADA` para revisarlo.

| Columna | Origen | Valor / regla |
|---|---|---|
| `F015_ID_PAIS` | Fijo | ✅ Siempre `169` (Colombia) |
| `F015_ID_DEPTO` | Derivado | ✅ Código del departamento, 2 dígitos (`05`): dígitos 4-5 de `codigo_ciudad_siesa` |
| `F015_ID_CIUDAD` | Derivado | ✅ Código de la ciudad, 3 dígitos (`001`): dígitos 6-8 de `codigo_ciudad_siesa` |
| `F015_ID_BARRIO` | — | ✅ Vacío |
| `F015_TELEFONO` | Reporte | ✅ Teléfono/celular **sin** `57` ni `+57` al inicio (`3001112233`) |
| `F015_EMAIL` | Reporte | ✅ `email` |
| `F200_FECHA_NACIMIENTO` | Derivado | ✅ Shopify no la tiene: va la **fecha de la carga** en formato `AAAAMMDD` (`20261019`), como texto, igual que la plantilla de ejemplo |
| `F015_CELULAR` | Reporte | ✅ Igual a `F015_TELEFONO` |

`F200_ID` y `F200_NIT` se escriben como número, igual que en la plantilla de ejemplo; las
demás columnas como texto, para no perder ceros a la izquierda.

Datos obligatorios para generar el tercero (R-34): documento, tipo, nombre (o razón social),
primer apellido (solo cédula), dirección y ciudad con código Siesa. Si falta alguno, el
pedido queda en `data/logs/plantillas_<run_id>.csv` con `TERCERO_INCOMPLETO` y no se carga.

### Hoja `Clientes`: el tercero como cliente (tabla F201)

✅ **Definida por TI el 2026-10-19** e implementada en `src/shopify_pipeline/erp/clientes.py`
(`fila_cliente`). Sale de la fila ya calculada de `Terceros`, así nombre, dirección, ciudad
y teléfono son idénticos en las dos hojas.

| Columna | Origen | Valor / regla |
|---|---|---|
| `F201_ID_TERCERO` | Terceros | Número de identificación (`F200_ID`), como número |
| `F201_ID_SUCURSAL` | Fijo | `001` |
| `F201_DESCRIPCION_SUCURSAL` | Terceros | `F015_CONTACTO`: nombre completo o razón social |
| `F201_ID_VENDEDOR` | Fijo | `W001` |
| `F201_ID_COND_PAGO` | Fijo | `03D` |
| `F201_ID_TIPO_CLI` | Fijo | `C001` |
| `F201_PORC_MIN_MARGEN` | Fijo | `1` |
| `F201_PORC_MAX_MARGEN` | Fijo | `500` |
| `F015_CONTACTO` | Terceros | `F015_CONTACTO` |
| `F015_DIRECCION1` | Terceros | `F015_DIRECCION1` |
| `F015_DIRECCION2` | Terceros | Continuación de la dirección y, si queda espacio, el complemento (máx. 40). Ver nota |
| `F015_ID_PAIS` | Fijo | `169` |
| `F015_ID_DEPTO` / `F015_ID_CIUDAD` | Terceros | Departamento (2 dígitos) y ciudad (3 dígitos) |
| `F015_ID_BARRIO` | — | Vacío |
| `F015_TELEFONO` / `f015_celular` | Terceros | Teléfono/celular sin `57` |
| `F015_EMAIL` | Terceros | Correo del cliente |
| `F201_FECHA_INGRESO` | Derivado | Fecha de la carga `AAAAMMDD`, como texto (igual que la fecha de nacimiento) |
| `f201_id_cobrador` | Fijo | `W001` |

> **Nota sobre la dirección:** `Clientes` tiene 2 campos de dirección y `Terceros` tiene 3.
> El segundo campo de `Clientes` lleva lo que en `Terceros` está en los campos 2 y 3 (casi
> siempre solo el complemento, como en el ejemplo de VTEX). Si los dos juntos pasan de 40
> caracteres, se corta entre palabras y el pedido queda con `DIRECCION_TRUNCADA`
> (detalle `hoja Clientes`).

### Hoja `Imptos y Reten`: clases de impuesto del cliente

✅ **Definida por TI el 2026-10-19** (`filas_impuestos`). Cada cliente aparece **3 veces**: es
responsable de IVA, no se le retiene en la fuente y es autorretenedor.

| `F_TIPO_REG` | `F_ID_TERCERO` | `F_ID_SUCURSAL` | `F_ID_CLASE` | `F_ID_VALOR_TERCERO` | Significado |
|---|---|---|---|---|---|
| `46` | documento | `001` | `1` | `1` | Responsable de IVA |
| `47` | documento | `001` | `1` | `0` | No se le retiene en la fuente |
| `47` | documento | `001` | `41` | `1` | Autorretenedor |

**Orden de las filas:** por bloques, como en la plantilla de ejemplo. Primero el `46` de
todos los clientes, luego el `47 / 1 / 0` de todos y al final el `47 / 41 / 1` de todos.
Con dos clientes A y B: `46-A, 46-B, 47(1)-A, 47(1)-B, 47(41)-A, 47(41)-B`.

### Hoja `Ent. Dinamica Cliente`: dato adicional (entidad dinámica)

✅ **Definida por TI el 2026-10-19** (`fila_entidad`).

| Columna | Origen | Valor / regla |
|---|---|---|
| `f201_id_tercero` | Terceros | Número de identificación, como número |
| `f201_id_sucursal` | Fijo | `001` |
| `f753_dato_texto` | Terceros | Correo del cliente |

### Verificación contra la plantilla de ejemplo

El archivo generado tiene las mismas 4 hojas, en el mismo orden, con los mismos
encabezados y el mismo tipo de dato por columna (número o texto) que `terceros_vtex.xlsx`.
Las celdas vacías quedan vacías; el ejemplo guarda un texto vacío, que se ve igual.

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
| P-1 | ✅ `F200_IND_TIPO_TERCERO` siempre `1`; con NIT se llena `F200_RAZON_SOCIAL`. **Abiertas:** (b) de dónde sale el nombre de la empresa (ver nota); (c) si con NIT van vacíos apellidos y nombres; (d) orden del nombre en `F015_CONTACTO`; (e) si el NIT lleva las mismas clases de impuesto; (f) si el DV va en algún campo | Hojas `Terceros` e `Imptos y Reten` |
| P-2 | `_id_fecha`: ¿fecha de compra en Shopify o fecha de carga a Siesa? ¿`_fecha_entrega` es siempre la misma? | Hojas `Pedidos` y `Movto` |
| P-3 | `_id_cond_pago` = `03D` para todos los pedidos, ¿o los de contraentrega usan otra condición? | Hojas `Pedidos` y `Clientes` |
| P-4 | ✅ Fecha de la carga `AAAAMMDD` (como texto) | Hojas `Terceros` y `Clientes` |
| P-5 | Cédula de extranjería y pasaporte: ¿qué código de `F200_ID_TIPO_IDENT` usan? Hoy salen con la alerta `TIPO_DOCUMENTO_SIN_CODIGO_SIESA`. | Hoja `Terceros` |
| P-6 | ¿Un archivo por corrida con todos los pedidos, o un archivo por pedido? ¿En qué carpeta los deja el pipeline para que alguien los suba? | Generador |

> **Nota sobre P-1b:** en Shopify el campo `company` ya se usa para el número de documento,
> así que no hay un campo propio para el nombre de la empresa. Hoy el pipeline usa el
> nombre y apellido que el cliente escribió en facturación (p. ej. `COMERCIAL ANDINA S.A.S.`).
> Si la empresa escribe ahí el nombre de una persona, la razón social saldrá con ese nombre.
