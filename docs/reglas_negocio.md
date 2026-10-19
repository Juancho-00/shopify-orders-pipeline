# Reglas de negocio · cuestionario para definir

Lista de las decisiones de negocio que necesita el pipeline para terminar la fase 1 y construir
las fases 2 y 3. Está pensada para resolverse en una reunión con el área comercial o de
e-commerce, contabilidad y el equipo de Siesa.

**Cómo usarla:** cada regla trae la pregunta, por qué importa, las opciones y una recomendación.
Basta con marcar la opción elegida y anotar quién la aprobó. Cada respuesta se aplica en un
solo lugar del código.

| Estado       | Significado                |
| ------------ | -------------------------- |
| ✅ Definida  | Ya decidida e implementada |
| ⏳ Pendiente | Hay que decidirla          |

**Responsables:** **Negocio** = comercial / e-commerce · **Contab.** = contabilidad ·
**Siesa** = equipo de Siesa · **Shopify** = equipo de implementación de Shopify (José).

---

## Resumen

| ID   | Regla                                                                        | Fase | Responsable       | Estado       |
| ---- | ---------------------------------------------------------------------------- | ---- | ----------------- | ------------ |
| R-01 | Solo pedidos con pago confirmado                                             | 1    | Negocio           | ✅           |
| R-02 | Excluir pedidos cancelados y de prueba                                       | 1    | Negocio           | ✅           |
| R-03 | Precios con IVA incluido, sin transformación                                | 1    | Contab.           | ✅           |
| R-04 | Alertas en un log aparte                                                     | 1    | —                | ✅           |
| R-05 | Cédula/NIT en el campo `company`                                          | 1    | Shopify           | ✅           |
| R-06 | Cómo identificar si el documento es CC o NIT                                | 1    | Negocio + Shopify | ⏳           |
| R-07 | ¿El envío lleva IVA?                                                       | 1    | Contab.           | ⏳           |
| R-08 | Código Siesa del ítem de envío                                            | 1    | Siesa             | ⏳           |
| R-09 | Equivalencia de bodegas Shopify → Siesa                                     | 1    | Siesa             | ⏳           |
| R-10 | Códigos de tipo de documento en Siesa                                       | 1    | Siesa             | ⏳           |
| R-11 | Ciudad: texto o código DANE                                                 | 1    | Siesa             | ⏳           |
| R-12 | Formato del documento de referencia                                          | 1    | Siesa             | ⏳           |
| R-13 | Pedidos con descuento: cómo se registran                                    | 1    | Contab.           | ⏳           |
| R-20 | Cómo se consultan los pedidos en Siesa                                      | 2    | Siesa             | ⏳           |
| R-21 | Llave de cruce Shopify ↔ Siesa                                              | 2    | Siesa             | ⏳           |
| R-22 | Qué se compara además de la existencia                                     | 2    | Negocio + Contab. | ⏳           |
| R-23 | Tolerancia en diferencias de valor                                           | 2    | Contab.           | ⏳           |
| R-24 | Qué hacer con cada resultado de la conciliación                            | 2    | Negocio           | ⏳           |
| R-30 | Cómo se cargan los datos a Siesa                                            | 3    | Siesa             | ⏳           |
| R-31 | Cómo saber si un cliente ya existe                                          | 3    | Siesa             | ⏳           |
| R-32 | Datos fijos del cliente (régimen, clase, sucursal)                          | 3    | Contab. + Siesa   | ⏳           |
| R-33 | Datos fijos del pedido (centro de operación, vendedor, lista de precios...) | 3    | Siesa             | ⏳           |
| R-34 | Qué hacer si falta un dato obligatorio                                      | 3    | Negocio           | ⏳           |
| R-35 | Evitar pedidos duplicados en Siesa                                           | 3    | Siesa             | ⏳ (parcial) |
| R-36 | Pedidos que cambian después de cargados (reembolso, cancelación)           | 3    | Negocio + Contab. | ⏳           |

---

## Fase 1 · Extracción (pendientes)

### R-06 · Cómo identificar si el documento es CC o NIT ⏳

**Contexto:** Shopify solo captura el número en `company`. Hoy el tipo se deduce por formato:
prefijo `NIT`, guion con dígito de verificación, o 9 dígitos que empiezan por 8 o 9.
Los casos deducidos solo por formato quedan como `NIT_POR_VERIFICAR`.

**Opciones:**

- **A.** Agregar en el checkout de Shopify un campo "Tipo de documento" (lista: CC, NIT, CE, Pasaporte).
- **B.** Pedir que el NIT se escriba siempre con guion y dígito de verificación (`900123456-7`) y tratar todo lo demás como CC.
- **C.** Mantener la deducción por formato y revisar a mano los `NIT_POR_VERIFICAR`.

**Recomendación:** A. Elimina la ambigüedad desde el origen. B sirve como solución temporal mientras Shopify hace el cambio.

**Decisión:** ______ **Aprobó:** ______ **Fecha:** ______

### R-07 · ¿El envío lleva IVA? ⏳

**Contexto:** en el pedido #1006, Shopify cobró $12.294,34 de envío sin calcularle IVA. El IVA
del pedido ($14.369,59) corresponde solo al producto.

**Opciones:**

- **A.** El envío no lleva IVA: Siesa lo registra con tarifa 0 %.
- **B.** El envío lleva IVA del 19 % incluido en el valor: hay que activar en Shopify el cobro de impuestos sobre las tarifas de envío.

**Por qué importa:** si Siesa le calcula IVA al envío y Shopify no, el impuesto del pedido no cuadra entre los dos sistemas.

**Decisión:** ______

### R-08 · Código Siesa del ítem de envío ⏳

**Contexto:** el envío se reporta como una línea más, con la referencia `ENVIO`.
**Pregunta:** ¿qué código de ítem (servicio) existe o se debe crear en Siesa para el flete?
**Dónde se configura:** `SIESA_CODIGO_ENVIO` en el `.env`.

**Código:** ______

### R-09 · Equivalencia de bodegas Shopify → Siesa ⏳

**Contexto:** Shopify asigna cada producto a una *ubicación* (p. ej. "Bodega Principal Medellín").
Siesa necesita su propio código de bodega.

| Ubicación en Shopify | ID Shopify | Código bodega Siesa |
| --------------------- | ---------- | -------------------- |
|                       |            |                      |
|                       |            |                      |

**Pregunta adicional:** si Shopify no asigna bodega a un producto (`SIN_BODEGA`), ¿se usa una bodega por defecto? ¿Cuál?

### R-10 · Códigos de tipo de documento en Siesa ⏳

| Tipo                         | Código en Siesa |
| ---------------------------- | ---------------- |
| Cédula de ciudadanía (CC)  |                  |
| NIT                          |                  |
| Cédula de extranjería (CE) |                  |
| Pasaporte (PP)               |                  |

### R-11 · Ciudad: texto o código DANE ⏳

**Contexto:** Shopify entrega la ciudad como texto escrito por el cliente ("Medellin", "Medellín",
"MEDELLIN"). Siesa normalmente trabaja con el código DANE (Medellín = `05001`).

**Opciones:**

- **A.** Siesa recibe el texto y lo homologa.
- **B.** El pipeline convierte el texto a código DANE con una tabla de equivalencias; los casos que no reconozca van al log de alertas.

**Recomendación:** B, con la tabla oficial de municipios del DANE.

### R-12 · Formato del documento de referencia ⏳

**Contexto:** es el número que une el pedido de Siesa con el de Shopify (hoy `1006`).

**Opciones:** `1006` · `#1006` · `SHOP-1006` · otro: ______
**Pregunta adicional:** ¿qué campo de Siesa lo guarda y qué longitud máxima acepta?

### R-13 · Pedidos con descuento ⏳

**Contexto:** hoy cada línea trae `precio_unitario` (precio de lista) y `descuento_linea` (valor total descontado).

**Opciones:**

- **A.** Siesa recibe el precio de lista y el descuento por separado.
- **B.** Siesa recibe el precio neto (precio − descuento ÷ cantidad) sin descuento aparte.

**Por qué importa:** cambia cómo se ven los descuentos en los informes de ventas de Siesa.

---

## Fase 2 · Conciliación (Shopify ↔ Siesa)

**Objetivo:** confirmar que cada pedido con pago confirmado en Shopify exista en Siesa, y
detectar los que faltan o tienen diferencias.

### R-20 · Cómo se consultan los pedidos en Siesa ⏳

**Opciones (de más a menos automatizable):**

- **A.** API o web service de Siesa.
- **B.** Consulta de solo lectura a la base de datos de Siesa (vista o usuario de consulta).
- **C.** Reporte exportado de Siesa (Excel o CSV) que alguien descarga y deja en una carpeta.

**Recomendación:** empezar con **C**, porque no requiere permisos técnicos y se puede construir ya
con un archivo de ejemplo, y migrar a A o B después.
**Se necesita:** un archivo de ejemplo del reporte (con datos de prueba) y saber cómo se genera.

### R-21 · Llave de cruce ⏳

**Pregunta:** ¿en qué campo de Siesa queda el número de pedido de Shopify (`documento_referencia`)?
Depende de R-12.

### R-22 · Qué se compara además de la existencia ⏳

Marcar lo que se debe verificar:

- [ ] Existe el pedido en Siesa
- [ ] Valor total
- [ ] Cantidad de líneas o productos
- [ ] Cantidades por referencia
- [ ] Cliente (número de documento)
- [ ] Estado (anulado en Siesa vs. vigente en Shopify)

### R-23 · Tolerancia en diferencias de valor ⏳

**Contexto:** puede haber diferencias por redondeo del IVA entre los dos sistemas.
**Pregunta:** ¿qué diferencia en el total se acepta como "cuadrado"? Ejemplo: hasta $100 o hasta 0,1 %.

**Tolerancia:** ______

### R-24 · Qué hacer con cada resultado ⏳

| Resultado                        | Acción propuesta                                | ¿De acuerdo? |
| -------------------------------- | ------------------------------------------------ | ------------- |
| En ambos y cuadra                | Nada                                             |               |
| Solo en Shopify (falta en Siesa) | Pasa a la fase 3 para crearlo                    |               |
| Solo en Siesa                    | Alerta: pedido manual o referencia mal escrita   |               |
| En ambos con diferencias         | Alerta para revisión manual; no se corrige solo |               |

**Pregunta adicional:** ¿quién revisa el informe de conciliación y con qué frecuencia?

---

## Fase 3 · Creación de clientes y pedidos en Siesa

**Objetivo:** crear en Siesa los clientes nuevos y los pedidos que la fase 2 marque como faltantes.

> **Nota:** Siesa está desarrollando la integración oficial con Shopify. Conviene confirmar con
> Siesa qué cubrirá su integración y hasta cuándo se usará esta contingencia, para no construir
> algo que se reemplace pronto.

### R-30 · Cómo se cargan los datos a Siesa ⏳

**Opciones:**

- **A.** Archivo plano de importación con la plantilla de Siesa, que alguien carga manualmente.
- **B.** Conector o web service de Siesa (carga automática).

**Se necesita:** las plantillas de **cliente** y **pedido** y, por cada columna:

| Dato                 | Ejemplo                                   |
| -------------------- | ----------------------------------------- |
| Nombre de la columna | `NIT_CLIENTE`                           |
| Tipo y longitud      | texto 15 · número · fecha `AAAAMMDD` |
| ¿Obligatoria?       | sí / no                                  |
| De dónde sale       | campo de Shopify o valor fijo             |
| Valores permitidos   | catálogo, si aplica                      |

### R-31 · Cómo saber si un cliente ya existe ⏳

**Opciones:**

- **A.** Por número de documento (recomendado).
- **B.** Por documento + email.

**Pregunta adicional:** si el cliente ya existe con otra dirección o teléfono, ¿se actualiza en Siesa o se deja como está?

### R-32 · Datos fijos del cliente ⏳

Valores que Shopify no tiene y que Siesa exige al crear un tercero:

| Dato                                                | Valor para clientes de e-commerce |
| --------------------------------------------------- | --------------------------------- |
| Clase de tercero / tipo de cliente                  |                                   |
| Régimen o responsabilidad fiscal (persona natural) |                                   |
| Régimen o responsabilidad fiscal (empresa con NIT) |                                   |
| Sucursal                                            |                                   |
| Condición de pago                                  |                                   |
| Vendedor o asesor asignado                          |                                   |
| Otros campos obligatorios de la plantilla           |                                   |

### R-33 · Datos fijos del pedido ⏳

| Dato                                                  | Valor |
| ----------------------------------------------------- | ----- |
| Centro de operación                                  |       |
| Tipo de documento del pedido                          |       |
| Vendedor                                              |       |
| Lista de precios                                      |       |
| Condición de pago (pagado en línea / contraentrega) |       |
| Fecha de entrega (¿= fecha de compra + N días?)     |       |
| Unidad de medida                                      |       |
| Otros campos obligatorios de la plantilla             |       |

### R-34 · Qué hacer si falta un dato obligatorio ⏳

**Ejemplo:** pedido sin cédula, producto sin SKU o bodega sin equivalencia.

**Opciones:**

- **A.** No se carga ese pedido; queda en el log para corregirlo a mano (recomendado).
- **B.** Se carga con un valor por defecto (p. ej. cliente genérico "consumidor final").

### R-35 · Evitar pedidos duplicados ⏳

**Ya resuelto en el pipeline:** el registro de pedidos reportados (`data/state/reportados.json`)
evita que un pedido salga en dos reportes (`YA_REPORTADO`).
**Falta:** confirmar contra Siesa antes de cargar (fase 2), por si un pedido se creó a mano o
se cargó desde otro reporte.
**Pregunta:** ¿Siesa rechaza por sí mismo un documento de referencia repetido?

### R-36 · Pedidos que cambian después de cargados ⏳

| Caso en Shopify                           | ¿Qué debe pasar en Siesa? |
| ----------------------------------------- | --------------------------- |
| Se cancela un pedido ya cargado           |                             |
| Reembolso parcial (devuelven un producto) |                             |
| Reembolso total                           |                             |
| Se edita el pedido (cambian cantidades)   |                             |

**Hoy:** si el total de un pedido ya reportado cambia, queda en el log como
`CAMBIO_POST_REPORTE` y no se vuelve a reportar.
**Recomendación:** mantener ese aviso y que la corrección en Siesa la haga una persona, al
menos al inicio. Falta definir quién la hace y cómo (nota crédito, anulación, ajuste).

---

## Registro de decisiones

Cuando se tome una decisión, anótala aquí y en `docs/decisiones.md`.

| Fecha      | ID          | Decisión                                                                                                                     | Aprobó |
| ---------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------- | ------- |
| 2026-10-14 | R-01 a R-05 | R-01 → decisión 008 · R-02 → acordado el 14-oct · R-03 → 009 · R-04 → 007 · R-05 → 005 (ver `docs/decisiones.md`) |         |
|            |             |                                                                                                                               |         |
