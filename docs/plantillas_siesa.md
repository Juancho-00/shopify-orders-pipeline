# Plantillas de carga a Siesa (fase 3)

Estructura de las dos plantillas Excel que se suben a Siesa, analizada a partir de los
ejemplos del conector VTEX (`terceros_vtex.xlsx` y `pedidos_conector_*.xlsx`).

> **Estado:** las **dos plantillas** (clientes con 4 hojas y pedidos con 2) están definidas
> por TI e implementadas. Se generan juntas con `shopify-pipeline plantillas`.
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
| `F200_RAZON_SOCIAL` | Reporte | ✅ Si es `N`: nombre de la empresa, que viene en el campo `company` de Shopify junto al NIT (`billing_address.company`, respaldo `shipping_address.company`), en MAYÚSCULAS. Si es `C`: vacío |
| `F200_APELLIDO1` | Reporte | ✅ `primer_apellido` en MAYÚSCULAS. Si es `N`: vacío (igual apellido 2 y nombres) |
| `F200_APELLIDO2` | Reporte | ✅ `segundo_apellido` en MAYÚSCULAS (puede ir vacío) |
| `F200_NOMBRES` | Reporte | ✅ `primer_nombre` + `segundo_nombre` en MAYÚSCULAS |
| `F015_CONTACTO` | Derivado | ✅ Nombre completo en orden **APELLIDOS NOMBRES** (`RESTREPO GÓMEZ LAURA SOFÍA`) o la razón social si es `N` |
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

Datos obligatorios para generar el tercero (R-34): documento, tipo, razón social (NIT) o
primer nombre y primer apellido (cédula), dirección, ciudad con código Siesa, **email** y
**teléfono**. Email y teléfono son obligatorios porque se necesitan para la facturación
electrónica; se valida que el email tenga forma `algo@dominio.ext` y que el teléfono tenga
al menos 7 dígitos. Si falta alguno, el pedido queda en `data/logs/plantillas_<run_id>.csv`
con `TERCERO_INCOMPLETO` (el detalle dice qué campo) y no se carga.

> **Cómo escribe el cliente el NIT en Shopify:** número y nombre de la empresa en el mismo
> campo `company`, en cualquier orden: `NIT 900.123.456-7 Comercial Andina S.A.S.` o
> `Comercial Andina SAS - 900123456-7`. El pipeline separa el documento del nombre. Si un
> NIT llega sin nombre de empresa, se usa el nombre de facturación y el pedido queda con la
> alerta `RAZON_SOCIAL_DESDE_NOMBRE` para revisarlo antes de facturar.

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

> **Nota sobre la dirección (✅ confirmada por TI el 2026-10-20):** `Clientes` tiene 2 campos
> de dirección y `Terceros` tiene 3.
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

✅ **Definida por TI el 2026-10-20** e implementada en `src/shopify_pipeline/erp/pedidos.py`.

`Pedidos` es el **encabezado** del documento (una fila por pedido de Shopify) y
`Movto Pedidos comercial` es el **detalle** (una fila por producto, más la del envío). Las
une el par `_id_tipo_docto` + `_consec_docto`.

**Tipo de documento según la bodega** (`catalogos/bodegas_siesa.csv`, columna
`tipo_docto_siesa`):

| Bodega | Tipo | Descripción Siesa |
|---|---|---|
| D'Luchi PT Guarne (`LCD01`) | `CPW` | Pedido de venta pág. web |
| Tiendas D'Luchi - Kaba (`LCM..`) | `CPT` | Pedido PV pág. web |
| Melonn (`LEC..`) | `CPM` | Pedidos de venta Melonn |
| Vending: Terminal del Sur, Terminal del Norte, Los Molinos, Estación Niquia | `NO_CARGA` | **No se cargan a Siesa.** El pedido queda en el log como `BODEGA_NO_SE_CARGA` (informativo, no es un error) |

**Consecutivo:** empieza en 1 y se reinicia por cada tipo de documento. Los pedidos van por
bloques: primero todos los `CPW`, luego los `CPT` y al final los `CPM`; dentro de cada
bloque, por fecha de compra. Ejemplo: `CPW-1, CPW-2, CPT-1, CPM-1, CPM-2`.

### Hoja `Pedidos`: encabezado, una fila por pedido

| Columna | Origen | Valor / regla |
|---|---|---|
| `_id_co` | Fijo | `001` |
| `_id_tipo_docto` | Derivado | `CPW`, `CPT` o `CPM` según la bodega de salida (tabla de arriba) |
| `_consec_docto` | Derivado | 1, 2, 3... por tipo de documento (número) |
| `_id_fecha(AAAAMMDD)` | Derivado | Fecha de la carga, `AAAAMMDD` (`20261020`) |
| `_ind_backorder` | Fijo | `4` |
| `_id_tercero_fact` | Terceros | Número de identificación del cliente (número) |
| `_id_sucursal_fact` | Fijo | `001` |
| `_id_tercero_rem` | Terceros | Número de identificación del cliente (número) |
| `_id_sucursal_rem` | Fijo | `001` |
| `_id_co_fact` | Fijo | `001` |
| `_fecha_entrega(AAAAMMDD)` | Derivado | Fecha de la carga, `AAAAMMDD` |
| `_num_docto_referencia` | Reporte | `documento_referencia`: número del pedido Shopify sin `#` (R-12, R-21) |
| `_id_cond_pago` | Fijo | `03D` |
| `_notas` | Reporte | `notas` del pedido de Shopify (vacío si no tiene). **Máximo 500 caracteres**: lo que sobre se corta y el pedido queda con `NOTAS_RECORTADAS` |
| `_id_punto_envio` | Fijo | `000` |
| `_id_tercero_vendedor` | Fijo | `900733097` |

### Hoja `Movto Pedidos comercial`: una fila por línea del pedido

| Columna | Origen | Valor / regla |
|---|---|---|
| `_id_co` | Fijo | `001` |
| `_id_tipo_docto` | Pedidos | El mismo del encabezado |
| `_consec_docto` | Pedidos | El mismo del encabezado, **como texto** |
| `_nro_registro` | Derivado | 1 hasta n: un registro por producto y uno más para el envío si su valor es mayor a cero (número) |
| `_referencia_item` | Reporte | SKU del producto (los mismos en Shopify y Siesa, sin equivalencias). El envío usa `SERV01` (R-08) |
| `_id_ext1_COLOR` / `_id_ext2_TALLA` | — | Vacíos |
| `_id_bodega` | Reporte | `bodega_siesa`: bodega de donde sale el producto (R-09). El envío usa la de los productos |
| `_id_motivo` | Fijo | `06` |
| `_ind_obsequio(0=No, 1=Si)` | Fijo | `0` |
| `_id_co_movto` | Fijo | `001` |
| `ccosto_movto` | — | Vacío |
| `_fecha_entrega(AAAAMMDD)` | Derivado | La misma del encabezado |
| `_id_lista_precio` | Fijo | `03` |
| `_id_unidad_medida` | Fijo | `UND` |
| `_cant_pedida_base` | Reporte | `cantidad` que pidió el cliente, como texto |
| `_precio_unitario` | Reporte | `precio_neto`: lo que pagó el cliente por unidad, con el descuento aplicado, en pesos enteros e IVA incluido (R-07, R-13), como texto |
| `_ind_impto_asumido...` | Fijo | `0` (no liquida) |
| `ind_precio (...)` | Fijo | `2` (liquida con el precio del registro) |

Con `ind_precio = 2`, Siesa usa el precio que enviamos y no el de su lista de precios.
Por eso se manda el precio neto, con el descuento ya aplicado (R-13).

### Cuándo un pedido no se carga (R-34)

Un pedido que no se puede cargar no va en **ninguna** de las dos plantillas: ni su
encabezado, ni sus líneas, ni su cliente. Así nunca queda un cliente cargado sin su pedido
o un pedido sin su cliente. Queda en `data/logs/plantillas_<run_id>.csv` con el motivo:

| Código | Cuándo |
|---|---|
| `TERCERO_INCOMPLETO` | Falta un dato obligatorio del cliente (ver hoja `Terceros`) |
| `PEDIDO_INCOMPLETO` | Una línea sin SKU, bodega, cantidad o precio; el detalle dice cuál |
| `BODEGA_NO_SE_CARGA` | Pedido de una bodega de vending: no va a Siesa por definición. No cuenta como error (`--strict` no falla) |
| `TIPO_DOCTO_SIN_EQUIVALENCIA` | La bodega no tiene tipo de documento configurado (p. ej. una bodega nueva en Shopify): agregarlo en `bodegas_siesa.csv` |
| `PEDIDO_BODEGAS_MIXTAS` | Control: productos de bodegas con tipos distintos. Según TI no ocurre; si aparece, revisar |

### Verificación contra la plantilla de ejemplo

Con el pedido de prueba #1006, el archivo generado tiene las mismas 2 hojas, los mismos
encabezados y el mismo tipo de dato por columna que `pedidos_conector_*.xlsx`; las celdas
vacías quedan vacías.

---

## Preguntas (R-32)

| # | Pregunta | Afecta |
|---|---|---|
| P-1 | ✅ `F200_IND_TIPO_TERCERO` siempre `1`; razón social desde `company`; con NIT apellidos y nombres vacíos; contacto APELLIDOS NOMBRES; el NIT lleva las mismas 3 filas de impuestos; el DV no va en la plantilla (es un cálculo, el NIT son 9 dígitos) | Hojas `Terceros` e `Imptos y Reten` |
| P-2 | ✅ `_id_fecha` y `_fecha_entrega` = fecha de la carga (`20261020`) | Hojas `Pedidos` y `Movto` |
| P-3 | ✅ Siempre `03D` | Hojas `Pedidos` y `Clientes` |
| P-4 | ✅ Fecha de la carga `AAAAMMDD` (como texto) | Hojas `Terceros` y `Clientes` |
| P-5 | Cédula de extranjería y pasaporte: ¿qué código de `F200_ID_TIPO_IDENT` usan? Hoy salen con la alerta `TIPO_DOCUMENTO_SIN_CODIGO_SIESA`. | Hoja `Terceros` |
| P-6 | ✅ Un archivo por plantilla y por corrida (`terceros_<run_id>.xlsx`, `pedidos_<run_id>.xlsx`) en `data/siesa/cargas/` | Generador |
| P-7 | ✅ Las bodegas de vending no se cargan a Siesa; no hay pedidos con bodegas de tipos distintos; `_notas` admite 500 caracteres (2026-10-20) | Hoja `Pedidos` |


