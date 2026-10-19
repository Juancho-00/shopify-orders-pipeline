# Reglas de negocio

Decisiones de negocio que gobiernan el pipeline en sus tres fases. Cada regla trae lo que se
decidió y dónde está aplicada en el código. Las que siguen abiertas indican qué falta.

Las respuestas de R-06 a R-36 las entregó TI el **2026-10-19**.

| Estado | Significado |
|---|---|
| ✅ Definida | Ya decidida e implementada |
| 🟡 Decidida, sin implementar | Decidida; se aplica cuando se construya la parte que la usa |
| ⏳ Pendiente | Hay que decidirla |

**Responsables:** **Negocio** = comercial / e-commerce · **Contab.** = contabilidad ·
**Siesa** = equipo de Siesa · **Shopify** = equipo de implementación de Shopify (José).

---

## Resumen

| ID | Regla | Fase | Estado |
|---|---|---|---|
| R-01 | Solo pedidos con pago confirmado | 1 | ✅ |
| R-02 | Excluir pedidos cancelados y de prueba | 1 | ✅ |
| R-03 | Precios con IVA incluido, sin transformación | 1 | ✅ |
| R-04 | Alertas en un log aparte | 1 | ✅ |
| R-05 | Cédula/NIT en el campo `company` | 1 | ✅ |
| R-06 | CC o NIT según el formato del número | 1 | ✅ |
| R-07 | El envío lleva IVA, ya incluido en el valor | 1 | ✅ |
| R-08 | Ítem de envío `SERV01` | 1 | ✅ |
| R-09 | Tabla de bodegas Shopify → Siesa | 1 | ✅ |
| R-10 | Tipo de documento: `C` = cédula, `N` = NIT | 1 | ✅ (falta CE y pasaporte) |
| R-11 | Ciudad como código Siesa (`169` + DANE) | 1 | ✅ |
| R-12 | Referencia = número del pedido sin `#` | 1 | ✅ |
| R-13 | Siesa no recibe descuentos: precio neto | 1 | ✅ |
| R-20 | Siesa se consulta con un exporte Excel en una carpeta | 2 | ✅ |
| R-21 | Llave de cruce: `_num_docto_referencia` | 2 | ✅ |
| R-22 | Solo se verifica que el pedido exista | 2 | ✅ |
| R-23 | Sin decimales: valores en pesos enteros | 1 y 2 | ✅ |
| R-24 | Tolerancia máxima de $50 | 1 | ✅ |
| R-30 | Dos plantillas Excel: primero clientes, luego pedidos | 3 | 🟡 |
| R-31 | El cliente se sube siempre con cada pedido | 3 | 🟡 |
| R-32 | Datos fijos del cliente | 3 | ⏳ (se valida al llenar la plantilla) |
| R-33 | Datos fijos del pedido = los de la plantilla | 3 | 🟡 |
| R-34 | Si falta un dato obligatorio, el pedido no se sube | 3 | 🟡 |
| R-35 | Siesa impide referencias duplicadas | 3 | ✅ |
| R-36 | Cambios después de cargado: log y gestión manual | 3 | ✅ |

---

## Fase 1 · Extracción

### R-06 · Cómo identificar si el documento es CC o NIT ✅

Si el cliente escribe el tipo (`CC`, `NIT`...) o el DV con guion, se respeta. Si solo escribe
el número:

| Número | Tipo |
|---|---|
| 9 dígitos que empiezan por `900`, `901` u `800` (≈95 % de los NIT) | NIT |
| 9 dígitos que empiezan por otro 8 o 9 | NIT, con alerta `NIT_POR_VERIFICAR` |
| 7 u 8 dígitos (cédulas antiguas) | CC |
| 10 dígitos (cédulas nuevas: `1000…`, `1100…`, `1152469156`...) | CC |
| 10 dígitos = NIT de `800`/`900`/`901` + su DV pegado (`9001234567`) | NIT |
| Otro formato | Sin tipo, alerta `TIPO_DOCUMENTO_NO_IDENTIFICADO` |

**Aclarado el 2026-10-19:** toda cédula nueva de 10 dígitos es CC, no solo las que empiezan
por 1000 o 1100. La única excepción es un NIT escrito con el DV sin guion: se reconoce
porque el último dígito coincide con el DV calculado.
**Código:** `tipo_por_formato` en `transform/normalize.py`.

### R-07 · El envío lleva IVA ✅

En Siesa el envío lleva IVA. El valor que cobra la web ya lo incluye: no se transforma. Como
Shopify no desglosa ese IVA, el reporte marca la línea de envío con `tasa_iva = 0.19`.

### R-08 · Código Siesa del ítem de envío ✅

`SERV01`. Es el valor por defecto de `SIESA_CODIGO_ENVIO`. El envío sale de la misma bodega
que los productos del pedido, como en la plantilla del conector VTEX.

### R-09 · Equivalencia de bodegas Shopify → Siesa ✅

La tabla entregada (23 ubicaciones) está en `src/shopify_pipeline/catalogos/bodegas_siesa.csv`.
Una ubicación nueva en Shopify sin fila en la tabla genera la alerta `BODEGA_SIN_EQUIVALENCIA`.
Para agregarla basta con añadir la fila al CSV.

### R-10 · Códigos de tipo de documento en Siesa ✅

| Tipo | Código en Siesa |
|---|---|
| Cédula de ciudadanía (CC) | `C` |
| NIT | `N` |
| Cédula de extranjería (CE) | ⏳ pendiente (alerta `TIPO_DOCUMENTO_SIN_CODIGO_SIESA`) |
| Pasaporte (PP) | ⏳ pendiente (ídem) |

### R-11 · Ciudad como código ✅

El pipeline convierte el texto de la ciudad al código de la tabla de ciudades de Siesa
(`catalogos/ciudades_siesa.csv`): `169` (Colombia) + departamento DANE + municipio DANE.
Ejemplo: Medellín = `16905001`. Busca la ciudad dentro del departamento del pedido, sin
importar tildes ni mayúsculas. Lo que no reconoce va al log como `CIUDAD_SIN_CODIGO`.

### R-12 · Formato del documento de referencia ✅

El número del pedido de Shopify sin caracteres especiales (`#1006` → `1006`), de cualquier
longitud. Columna `documento_referencia` del reporte.

### R-13 · Pedidos con descuento ✅

Siesa no recibe descuentos. El reporte trae dos precios por línea:

- `precio_unitario`: precio del ítem en Shopify.
- `precio_neto`: precio con el descuento aplicado, (precio × cantidad − descuento) ÷
  cantidad. **Es el que se sube a Siesa.**

`descuento_linea` queda como información. Todos en pesos enteros (R-23).

---

## Fase 2 · Conciliación (Shopify ↔ Siesa)

**Objetivo:** confirmar que cada pedido reportado exista en Siesa.
**Comando:** `shopify-pipeline conciliar` (ver README).

### R-20 · Cómo se consultan los pedidos en Siesa ✅

Opción **C**: alguien exporta el reporte de pedidos de Siesa a Excel y lo deja en
`data/siesa/exportes/`. El pipeline toma el más reciente.
Formato confirmado con el exporte real (2026-10-19): columnas `Nro documento` (tipo de
documento + consecutivo de Siesa, p. ej. `CPM-00003210`) y `_num_docto_referencia`.

### R-21 · Llave de cruce ✅

`_num_docto_referencia` de Siesa contra `documento_referencia` del reporte.

### R-22 · Qué se compara ✅

Solo que el número del pedido exista en Siesa. Resultado por pedido: `EN_SIESA` o
`FALTA_EN_SIESA`, en `data/reconciliation/conciliacion_<fecha>.xlsx`.

### R-23 · Valores sin decimales ✅

Ni Shopify ni Siesa deben manejar decimales en los valores: el reporte envía pesos enteros.
Shopify a veces entrega centavos (el envío del #1006 fue $12.294,34): se redondean al peso
más cercano (confirmado el 2026-10-19).

### R-24 · Tolerancia ✅

Diferencia máxima de **$50** entre la suma de las líneas y el total del pedido en Shopify.
Absorbe el redondeo a pesos enteros; una diferencia mayor genera `TOTAL_NO_CUADRA`.

**Revisión:** la conciliación es manual y diaria. Una persona exporta el Excel de Siesa y ejecuta `conciliar`; por ahora lo hace TI y después el asistente o un digitador. A futuro se evaluará un agente de IA para la exportación (ver `ejecucion_programada.md`).

---

## Fase 3 · Creación de clientes y pedidos en Siesa

**Objetivo:** generar las plantillas para crear en Siesa los clientes y pedidos reportados.
La estructura de cada columna está en [plantillas_siesa.md](plantillas_siesa.md).

> **Nota:** Siesa está desarrollando la integración oficial con Shopify. Conviene confirmar
> qué cubrirá y hasta cuándo se usará esta contingencia.

### R-30 · Cómo se cargan los datos a Siesa 🟡

Dos plantillas Excel, en este orden:

1. Clientes (`Terceros`, `Clientes`, `Imptos y Reten`, `Ent. Dinamica Cliente`).
2. Pedidos (`Pedidos`, `Movto Pedidos comercial`).

### R-31 · Clientes existentes 🟡

El cliente se sube **siempre** con cada pedido, aunque ya exista, porque sus datos
(dirección, teléfono) pueden haber cambiado.

### R-32 · Datos fijos del cliente ⏳

Se valida cuando se llene la plantilla. Las preguntas abiertas (NIT/razón social, condición
de pago de contraentrega, fecha de nacimiento, CE/pasaporte) están en
[plantillas_siesa.md](plantillas_siesa.md#preguntas-abiertas-resolver-con-r-32).

### R-33 · Datos fijos del pedido 🟡

Los valores fijos son los que trae la plantilla: centro de operación `001`, tipo de documento
`CPM`, condición de pago `03D`, lista de precios `03`, unidad `UND`, motivo `06`, etc.

### R-34 · Falta un dato obligatorio 🟡

El pedido **no se sube**. Queda en el log para corregirlo a mano.

### R-35 · Evitar pedidos duplicados ✅

- **Pipeline:** el registro `data/state/reportados.json` evita que un pedido salga en dos
  reportes (`YA_REPORTADO`).
- **Siesa:** el permiso del usuario impide crear dos pedidos con el mismo
  `_num_docto_referencia`.
- **Conciliación:** si el exporte trae una referencia repetida, se avisa en la bitácora.

### R-36 · Pedidos que cambian después de cargados ✅

Los cambios no deseados (cancelación, reembolso, edición de un pedido ya reportado) quedan en
el log como `CAMBIO_POST_REPORTE`. Si el pedido ya se cargó en Siesa, la persona responsable
gestiona con logística que no se despache.

---

## Registro de decisiones

| Fecha | ID | Decisión |
|---|---|---|
| 2026-10-14 | R-01 a R-05 | R-01 → decisión 008 · R-02 → acordado el 14-oct · R-03 → 009 · R-04 → 007 · R-05 → 005 (ver `docs/decisiones.md`) |
| 2026-10-19 | R-06 a R-36 | Respuestas de TI; aplicadas en decisiones 020 a 023 de `docs/decisiones.md` |
