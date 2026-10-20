# Guía del código · Fase 1 (extracción)

Esta guía explica para qué existe cada archivo `.py`, qué hace y por qué está separado de
los demás. Se puede leer de corrido o saltar al archivo que interese.

---

## 1. La idea en 30 segundos

La fase 1 funciona como una cadena de tres estaciones:

```
 ┌─────────────┐      ┌──────────────────┐      ┌────────────────────┐
 │  1. TRAER   │ ───► │  2. GUARDAR CRUDO│ ───► │  3. TRANSFORMAR    │
 │  de Shopify │      │  (sin tocar nada)│      │  al formato Siesa  │
 └─────────────┘      └──────────────────┘      └────────────────────┘
carpeta shopify/      	sinks/jsonl.py             carpeta transform/
                        data/raw/...jsonl        data/processed/...xlsx
                                                data/logs/alertas_...csv
```

**¿Por qué separar "traer" de "transformar"?** Porque Shopify cuesta llamadas (hay un límite)
y las reglas de transformación cambian (cómo identificar un NIT, el código del envío...).
Con el archivo crudo guardado, se puede rehacer el reporte las veces que haga falta con
`shopify-pipeline transform`, sin volver a llamar a Shopify.

---

## 2. Qué pasa al escribir `shopify-pipeline extract --days 1`

| Paso | Qué ocurre                                                      | Archivo → función                                                                   |
| ---- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 1    | Python busca el comando`shopify-pipeline` y llama a `main()` | `pyproject.toml` → `cli.py: main`                                                |
| 2    | Carga el`.env` (credenciales)                                  | `config.py: load_env_file`                                                          |
| 3    | Lee los argumentos (`--days 1`)                                | `cli.py: build_parser`                                                              |
| 4    | Prepara la bitácora en`data/logs/`                            | `logs.py: setup_logging`                                                            |
| 5    | Arma la ventana de fechas (ayer → ahora)                        | `cli.py: build_filter` → `shopify/orders.py: OrderFilter`                        |
| 6    | Arma la configuración y valida el dominio y las credenciales    | `config.py: ShopifyConfig.from_env`                                                 |
| 7    | Crea el cliente que hablará con Shopify                         | `shopify/client.py: ShopifyClient`                                                  |
| 8    | Pregunta cuántos pedidos hay (para comparar al final)           | `shopify/orders.py: count_orders`                                                   |
| 9    | Descarga los pedidos, página por página                        | `shopify/orders.py: extract_orders` → `client.py: paginate`                      |
| 10   | Por cada pedido, consulta la bodega de cada producto             | `shopify/fulfillment.py: BodegaEnricher`                                            |
| 11   | Guarda todo en`data/raw/.../<run_id>.jsonl`                    | `sinks/jsonl.py: write_jsonl`                                                       |
| 12   | Guarda el resumen de la corrida (`.manifest.json`)             | `extract.py: _write_manifest`                                                       |
| 13   | Relee el JSONL y convierte cada pedido en filas                  | `transform/run.py: run_transform` → `transform/siesa_lines.py: transform_orders` |
| 14   | Limpia nombres, cédula, teléfono, fechas, montos               | `transform/normalize.py`                                                            |
| 15   | Escribe el reporte (CSV y Excel) y el log de alertas             | `sinks/tabular.py: write_csv / write_xlsx`                                          |
| 16   | Devuelve un código de salida (0 = todo bien)                    | `cli.py: main`                                                                      |

Los pasos 8, 9 y 10 pasan por `client.py`, que se encarga de los errores, los reintentos y
el límite de llamadas. Los pasos 13 a 15 no llaman a Shopify.

---

## 3. Mapa de archivos

```
src/shopify_pipeline/
├── __init__.py          Marca la carpeta como paquete y define la versión
├── __main__.py          Permite ejecutar "python -m shopify_pipeline"
├── cli.py               Comandos de terminal (extract, transform, conciliar, plantillas) → códigos de salida
├── logs.py              Bitácora: consola + archivo diario
├── config.py            Lee el .env y valida dominio y credenciales
├── exceptions.py        Los tipos de error con nombre propio
├── extract.py           Orquesta la extracción: contar → descargar → guardar → manifiesto
├── state.py             Memoria entre corridas: watermark y pedidos ya reportados
├── shopify/             TODO lo que habla con Shopify
│   ├── auth.py          De dónde sale el token
│   ├── client.py        Peticiones HTTP: errores, reintentos, límite, páginas
│   ├── orders.py        Filtros de pedidos y descarga
│   └── fulfillment.py   Bodega de salida de cada producto
├── catalogos/           Tablas de Siesa en CSV: bodegas y ciudades (datos, no código)
├── transform/           De pedido crudo a reporte Siesa (no llama a Shopify)
│   ├── normalize.py     Funciones de limpieza (nombres, cédula/NIT, teléfono...)
│   ├── catalogos.py     Traduce bodega y ciudad a los códigos de Siesa
│   ├── siesa_lines.py   Pedido → filas; decide qué pedidos se excluyen
│   ├── alertas.py       Catálogo de alertas y exclusiones del log
│   └── run.py           Orquesta la transformación: leer JSONL → escribir reporte
├── sinks/               Escritura de archivos
│   ├── atomic.py        Escritura atómica compartida (temporal + renombrar)
│   ├── jsonl.py         JSON Lines (zona cruda)
│   └── tabular.py       CSV y Excel
├── reconciliation/      Fase 2: ¿los pedidos reportados están en Siesa?
│   ├── siesa_export.py  Lee el exporte de Siesa y saca los números de pedido
│   └── run.py           Cruza y escribe el reporte de conciliación
└── erp/                 Fase 3: plantillas de carga a Siesa
    ├── terceros.py      Pedido del reporte → fila de la hoja Terceros
    ├── clientes.py      Hojas Clientes, Imptos y Reten y Ent. Dinamica Cliente
    ├── pedidos.py       Plantilla de pedidos: tipo de documento, consecutivo, encabezado y detalle
    └── run.py           Orquesta la fase 3: reporte → terceros_<run>.xlsx + pedidos_<run>.xlsx
```

**Regla para orientarse:** los archivos de `shopify/` saben de Shopify pero no de Siesa. Los
de `transform/` saben de Siesa pero no llaman a Shopify. `extract.py` y `transform/run.py`
coordinan, y `cli.py` solo traduce lo que escribe el usuario. `reconciliation/` y `erp/`
no llaman a Shopify: trabajan sobre el reporte que dejó la fase 1.

---

## 4. Archivo por archivo

### `__init__.py` y `__main__.py`

- **`__init__.py`**: Python necesita este archivo en una carpeta para tratarla como
  *paquete* (algo que se puede importar). El de la raíz guarda la versión (`__version__`).
  Los de las subcarpetas solo traen un comentario con el índice de su contenido.
- **`__main__.py`**: permite ejecutar `python -m shopify_pipeline extract`. Hace lo mismo
  que `shopify-pipeline extract`.

### `cli.py` — la puerta de entrada

**Para qué:** convertir lo que escribes en la terminal en llamadas al código.
No contiene reglas de negocio.

| Función           | Qué hace                                                                                                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `build_parser`   | Define los comandos (`extract`, `transform`) y sus opciones (`--days`, `--since`, `--codigo-envio`...). La librería `argparse` genera la ayuda de `--help` |
| `build_filter`   | Convierte`--days`, `--since`/`--until`, `--incremental` y `--filtrar-por` en un `OrderFilter`                                                                   |
| `_parse_fields`  | Lee`--fields` y, si se va a generar el reporte, agrega los campos que este necesita (`CAMPOS_REQUERIDOS`)                                                      |
| `_parse_date`    | Acepta`2026-10-01` (medianoche en hora Colombia) o `2026-10-01T08:00:00-05:00` y lo convierte en fecha                                                               |
| `_filtro_bodega` | Decide qué pedidos merecen la llamada de bodega: solo los que van al reporte (`va_al_reporte`), salvo `--bodega-todos` o `--solo-raw`                           |
| `_parse_estados` | Convierte`"paid,partially_refunded"` en un conjunto; `"todos"` = sin filtro                                                                                           |
| `_siesa_options` | Agrupa las opciones del reporte Siesa en un`SiesaLinesOptions`                                                                                                          |
| `_cmd_extract`   | Ejecuta la extracción, la transformación (salvo`--solo-raw`) y, en modo incremental, avanza el watermark si la extracción cuadró                                 |
| `_codigo_strict` | Con`--strict`: `3` si el conteo no cuadró, `4` si hubo pedidos que no se pudieron transformar                                                                       |
| `_cmd_transform` | Rehace el reporte desde un JSONL ya guardado                                                                                                                              |
| `main`           | Carga el`.env`, lee argumentos, configura logs, ejecuta el comando y traduce errores a códigos                                                                         |

**Códigos de salida:** `0` bien · `1` error temporal (red, Shopify caído, archivo bloqueado) ·
`2` error de configuración (token, permisos, `.env`, argumentos) · `3` el conteo no cuadró
(solo con `--strict`) · `4` error de datos (archivo dañado, campos faltantes, pedidos que no
se pudieron transformar con `--strict`) · `5` error inesperado (bug). Sirven para que una
tarea programada sepa si debe reintentar (`1`) o avisar a una persona (los demás).

### `logs.py` — la bitácora

**Para qué:** que cada mensaje salga en pantalla y en `data/logs/shopify_pipeline_AAAAMMDD.log`.

Cada archivo crea su propio `logger = logging.getLogger(__name__)`. Como todos se llaman
`shopify_pipeline.algo`, basta configurar el logger `shopify_pipeline` una vez y todos
heredan esa configuración.

### `config.py` — la configuración

**Para qué:** juntar en un solo objeto todo lo necesario para conectarse, y validarlo
**antes** de hacer cualquier llamada.

- `load_env_file`: carga el `.env` en las variables de entorno.
- `ShopifyConfig`: guarda dominio, versión de API, credenciales, tiempos de espera y número de
  intentos. Al crearse (`__post_init__`) verifica que el dominio sea `*.myshopify.com` y que
  haya credenciales. Si algo falta, falla de inmediato con un mensaje claro.
- `ShopifyConfig.from_env`: lo construye leyendo las variables `SHOPIFY_*`.
- `field(repr=False)`: hace que el token y el secreto **no** aparezcan si alguien imprime la
  configuración en un log.

### `exceptions.py` — los errores con nombre

**Para qué:** que el resto del código sepa **qué tipo** de error ocurrió y reaccione distinto.

```
PipelineError
├── ConfigError                 .env, argumentos o carpeta vacía → código 2
├── DataError                   archivo dañado o datos insuficientes → código 4
└── ShopifyError
    ├── ShopifyAuthError        401  token malo o vencido      → intentar renovar el token
    ├── ShopifyPermissionError  403  falta un permiso (scope)  → no reintentar
    ├── ShopifyNotFoundError    404  dominio o versión mal     → no reintentar
    ├── ShopifyClientError      otros 4xx                      → no reintentar
    └── ShopifyRetryableError   429 o 5xx                      → esperar y reintentar
```

`CONFIGURATION_ERRORS` agrupa los que significan "corrige la configuración"; `cli.py` los usa
para devolver el código `2`. Un `ValueError` cualquiera **no** cuenta como error de
configuración: casi siempre es un dato malo o un bug, y confundirlos hacía que la tarea
programada diera una instrucción equivocada.

### `extract.py` — el coordinador de la extracción

**Para qué:** ejecutar en orden los pasos 8 a 12 de la tabla del inicio.

| Elemento             | Qué hace                                                                                                                        |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `run_extraction`   | Cuenta los pedidos → descarga → agrega bodegas → guarda JSONL → si no cuadra, cuenta otra vez (`recount_count`) → escribe manifiesto |
| `ExtractionResult` | El resumen de la corrida (ventana, conteos, duración).`reconciled` dice si lo descargado coincide con lo que reportó Shopify |
| `new_run_id`       | Crea el identificador de la corrida a partir de la hora UTC:`20261014T150000Z`. Así los archivos quedan ordenados por fecha   |

**La zona raw es inmutable:** si ya existe un JSONL con el mismo `run_id`, la extracción se
niega a sobrescribirlo. El manifiesto registra además `fields` (si se pidieron solo algunos
campos), `incremental` y `schema_version`: es el contrato que `transform` valida.

**Dato clave:** la descarga y la escritura van "encadenadas". Un pedido sale de Shopify, se le
agrega la bodega y se escribe al archivo antes de pedir el siguiente. Por eso la memoria no
crece aunque sean miles de pedidos (ver *generadores* en la sección 5).

### `shopify/auth.py` — el token

**Para qué:** entregar el token que va en cada petición.

- `StaticTokenProvider`: para apps *legacy* con token permanente `shpat_...`. Lo devuelve tal cual.
- `ClientCredentialsTokenProvider`: para apps del Dev Dashboard. Pide el token a Shopify con
  `client_id` + `client_secret`, lo guarda y pide uno nuevo 5 minutos antes de que venza (dura ~24 h).
- `build_token_provider`: elige la clase según lo que haya en el `.env`.
- `TokenProvider`: el "contrato". Cualquier clase con `get_token()` e `invalidate()` sirve.
  Gracias a eso el cliente HTTP no necesita saber cuál de las dos está usando.

### `shopify/client.py` — el que habla con Shopify

**Para qué:** es el único lugar que hace peticiones HTTP. Si mañana Shopify cambia algo de
conexión, solo se toca este archivo.

| Función                           | Qué hace                                                                                                                                 |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `_pedir_una_vez`                 | Hace**una** petición. Si la respuesta es 200, la devuelve; si no, lanza el error con nombre que corresponde                        |
| `_pedir_con_reintentos`          | Repite`_pedir_una_vez` hasta 6 veces, **solo** si el error es temporal. Entre intentos espera                                     |
| `segundos_de_espera`             | Cuánto esperar: lo que diga Shopify (`Retry-After`) o un tiempo al azar que crece en cada intento (hasta 2, 4, 8, 16... s; máximo 60) |
| `_frenar_si_el_balde_esta_lleno` | Lee`36/40` en la cabecera y, si pasa del 80 %, pausa antes de que Shopify responda 429                                                  |
| `get`                            | Punto de entrada: arma la URL, llama con reintentos y, ante un 401, renueva el token una vez                                              |
| `paginate`                       | Sigue la cabecera`Link: rel="next"` hasta que no haya más páginas. Entrega una página a la vez                                       |

**El balde con fuga (leaky bucket):** Shopify da 40 "gotas" por tienda. Cada llamada echa una
y se vacían 2 por segundo. Si el balde se llena, responde 429. Este archivo frena antes de que
pase y, si igual pasa, espera y reintenta.

> **Simplificado en esta revisión:** antes los reintentos usaban la librería `tenacity`,
> difícil de leer. Ahora son un `for` normal en `_pedir_con_reintentos`, con el mismo
> comportamiento.

### `shopify/orders.py` — qué pedidos pedir

**Para qué:** definir el filtro y descargar los pedidos.

- `OrderFilter`: la "orden de compra" de la consulta:
  - `date_min` / `date_max`: la ventana de fechas.
  - `date_field`: si la ventana aplica a la creación (`created_at`) o a la última modificación (`updated_at`).
  - `status="any"`: incluye abiertos, cerrados y cancelados (Shopify, por defecto, solo da los abiertos).
  - `fields`: opcional, para pedir menos columnas.
  - `page_size=250`: el máximo por página.
- `last_n_days(7)`: atajo para "los últimos 7 días".
- `filter_params` / `list_params`: convierten el filtro en los parámetros de la URL.
- `count_orders`: pregunta a Shopify cuántos pedidos cumplen el filtro.
- `extract_orders`: recorre las páginas y entrega los pedidos uno por uno, sin repetir ninguno.

### `shopify/fulfillment.py` — la bodega

**Para qué:** el pedido no trae de qué bodega sale cada producto. Shopify guarda esa
información en las *fulfillment orders* (grupos de productos asignados a una ubicación).

| Elemento                     | Qué hace                                                                                                                                              |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `fetch_fulfillment_orders` | Consulta`orders/{id}/fulfillment_orders.json` (una llamada por pedido)                                                                               |
| `_slim`                    | Se queda solo con lo útil: bodega, líneas y cantidades                                                                                               |
| `BodegaEnricher`           | Agrega la bodega a cada pedido con la clave`_fulfillment_orders`. Con `debe_consultar` se salta los pedidos que no van al reporte (`omitidos`). Si falta el permiso (403), avisa una vez y sigue sin bodega; si un pedido da 404, sigue con el siguiente |
| `location_by_line_item`    | Arma el diccionario`{línea del pedido: (id_bodega, nombre_bodega)}` que usa la transformación                                                      |

### `transform/normalize.py` — las funciones de limpieza

**Para qué:** pequeñas funciones que reciben un dato "sucio" y devuelven uno limpio. No
saben nada de Shopify ni de Siesa, por eso son fáciles de probar y de reutilizar.

| Función            | Entrada → salida                                                       |
| ------------------- | ----------------------------------------------------------------------- |
| `clean_text`      | `"  Entregar\nen portería "` → `"Entregar en portería"`          |
| `split_nombres`   | `"Juan Pablo"` → `("Juan", "Pablo")`                               |
| `split_apellidos` | `"De la Torre Gómez"` → `("De la Torre", "Gómez")`               |
| `parse_documento` | `"1.152.469.156"` → CC `1152469156`; `"900123456-7"` → NIT + DV |
| `tipo_por_formato` | `"900123456"` → NIT; `"70123456"` → CC; `"123456"` → sin tipo (R-06) |
| `calcular_dv_nit` | `"800197268"` → `"4"` (algoritmo de la DIAN)                       |
| `normalize_phone` | `"+57 323 501 6059"` → `"3235016059"`                              |
| `to_decimal`      | `"12294.34"` → `Decimal("12294.34")` (sin errores de redondeo)     |
| `to_bogota`       | `"2026-10-08T22:59:15Z"` → `"2026-10-08 17:59:15"` (hora Colombia) |

`tipo_por_formato` contiene la regla R-06 para saber si un número sin prefijo es CC o NIT.
Si la regla cambia, se cambia solo esa función.

### `transform/catalogos.py` — bodegas y ciudades de Siesa

**Para qué:** traducir lo que dice Shopify a los códigos que entiende Siesa, usando las
tablas de `catalogos/` (R-09, R-11).

| Función | Entrada → salida |
|---|---|
| `codigo_bodega` | `"D’Luchi PT Guarne"` → `"LCD01"`; bodega desconocida → `""` |
| `codigo_ciudad` | `("Medellin", "Antioquia", "ANT")` → `"16905001"`; ambigua o desconocida → `""` |
| `partes_ciudad` | `"16905001"` → `("169", "05", "001")` (país, depto, ciudad para la plantilla) |
| `normalizar` | Quita tildes, mayúsculas, apóstrofos y signos para comparar textos |

Una ciudad con nombre repetido (hay 63, como "La Unión") se busca **dentro del departamento**
del pedido. Si aun así no se puede decidir, devuelve vacío y el pedido sale con alerta: es
mejor revisar a mano que mandar a Siesa la ciudad equivocada.

### `transform/siesa_lines.py` — el corazón del reporte

**Para qué:** convertir **un pedido** de Shopify en **varias filas** para Siesa (una por
producto, más una de envío) y decidir qué pedidos no pasan.

| Elemento                                          | Qué hace                                                                                           |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `COLUMNS`                                       | Lista y orden de las columnas del reporte                                                           |
| `DEFAULT_ESTADOS_PAGO`                          | Qué cuenta como pago confirmado:`paid`, `partially_refunded`                                   |
| `SiesaLinesOptions`                             | Opciones: código del envío, estados de pago, incluir cancelados o de prueba                       |
| `CAMPOS_REQUERIDOS` / `CLAVES_CRITICAS`       | Campos que necesita la transformación / los que, si faltan, harían fallar los filtros en silencio |
| `transform_orders`                              | Recorre todos los pedidos **aislando cada uno**: si uno falla, queda como `ERROR_TRANSFORMACION` y los demás siguen |
| `validar_contrato`                              | ¿Trae el pedido las claves críticas (`test`, `cancelled_at`, `financial_status`...)? Si no, `DATOS_INCOMPLETOS` |
| `_motivo_exclusion`                             | ¿Es de prueba? ¿Está cancelado? ¿El pago no está confirmado?                                   |
| `_motivo_ledger`                                | ¿Ya salió en el reporte de otra corrida? (`YA_REPORTADO` o, si su total cambió, `CAMBIO_POST_REPORTE`) |
| `order_to_lines`                                | Convierte un pedido: datos del cliente + una fila por producto + fila de envío si cuesta más de 0 |
| `_cliente`                                      | Arma los datos del cliente (nombre, cédula, dirección, teléfono, email) y sus alertas            |
| `_diferencia_total`                             | Control: ¿la suma de las filas = total del pedido en Shopify? (tolerancia $50, R-24)               |
| `TIPO_DOC_SIESA` / `IVA_ENVIO`                  | `CC` → `C`, `NIT` → `N` (R-10) / IVA del envío cuando Shopify no lo desglosa (R-07)                 |
| `_descuento`, `_tasa`, `_notas`, `_first` | Ayudantes pequeños (descuento de la línea, tasa de IVA, notas, primer valor no vacío)            |
| `PedidoTransformado` / `TransformResult`      | "Cajas" con el resultado: filas + alertas (de un pedido / de todos)                                 |

### `transform/alertas.py` — el catálogo de alertas

**Para qué:** definir qué es una alerta y qué significa cada código (`SIN_DOCUMENTO`,
`NIT_POR_VERIFICAR`, `PAGO_NO_CONFIRMADO`...).

- `Evento`: una alerta o exclusión: tipo, código, pedido, línea, referencia y detalle.
  **Nunca** guarda datos personales.
- `DESCRIPCIONES`: código → explicación en español.
- `EVENT_COLUMNS`: columnas del archivo `alertas_<run_id>.csv`.

> **Separado en esta revisión:** antes vivía dentro de `siesa_lines.py`. Ahora para agregar
> una alerta nueva se edita la descripción aquí y se dispara desde `siesa_lines.py`.

### `transform/run.py` — el coordinador de la transformación

**Para qué:** ejecutar los pasos 13 a 15: leer el JSONL, transformar y escribir el reporte y
el log de alertas.

- `read_jsonl`: lee el archivo crudo línea por línea. Si una línea está dañada, indica cuál.
- `latest_raw_file`: busca la extracción más reciente (por eso el `run_id` es ordenable).
- `read_manifest`: lee el manifiesto de la extracción; se detiene si se extrajo con `--fields`
  sin los campos críticos y avisa si el conteo no cuadró.
- `run_transform`: valida el manifiesto → transforma → escribe CSV, Excel y
  `alertas_<run_id>.csv` → **después** registra los pedidos reportados en el ledger → resume
  en la bitácora.

### `sinks/atomic.py`, `sinks/jsonl.py` y `sinks/tabular.py` — escribir archivos

- `atomic_target` / `write_json_atomic` (`atomic.py`): la escritura atómica, en un solo lugar.
  La usan todos los demás (JSONL, CSV, Excel, manifiesto y estado).
- `write_jsonl`: un pedido por línea. Formato ideal para guardar datos tal cual llegan.
- `write_csv`: para sistemas (separador `,`, punto decimal, UTF-8).
- `write_xlsx`: para personas. Los montos quedan como números reales y se ven bien en Excel en español.

Todos escriben de forma **atómica**: primero a un archivo temporal y, solo si todo salió
bien, lo renombran al nombre final. Si algo falla a mitad de camino, no queda un archivo incompleto.

> **Simplificado en esta revisión:** se eliminaron `sinks/base.py` y la clase `JsonlSink`,
> que nadie usaba.

### `state.py` — la memoria entre corridas

**Para qué:** que una corrida sepa qué hizo la anterior. Vive en `data/state/`.

| Elemento              | Qué hace                                                                                                   |
| --------------------- | ---------------------------------------------------------------------------------------------------------- |
| `incremental_window` | Ventana de `--incremental`: desde el watermark menos 30 min (`OVERLAP`) hasta ahora; sin watermark, 7 días |
| `load_watermark` / `save_watermark` | Leen y guardan `watermark.json`: hasta dónde llegó la última extracción **completa**       |
| `Ledger`              | `reportados.json`: id del pedido → total y corrida en que se reportó. Evita duplicados entre reportes     |

**Por qué JSON y no una base de datos:** `data/` vive en Google Drive. Un archivo que se
reemplaza completo (escritura atómica) es lo más seguro frente a la sincronización; una
base SQLite a medio escribir podría subirse corrupta. Una sola máquina debe ejecutar la
tarea programada.

### `reconciliation/siesa_export.py` — leer el exporte de Siesa

**Para qué:** sacar de un Excel o CSV exportado de Siesa la lista de números de pedido
(`_num_docto_referencia`). Es tolerante a cómo venga el archivo: busca la fila de
encabezados en las primeras 20 filas, acepta el nombre de la columna con o sin `_` o en
mayúsculas, y convierte `#1006` o `1006.0` en `1006`.

### `reconciliation/run.py` — el cruce

**Para qué:** juntar los pedidos de los reportes oficiales de la fase 1 y marcar cada uno
como `EN_SIESA` o `FALTA_EN_SIESA`. Escribe `data/reconciliation/conciliacion_<fecha>.xlsx`
con los faltantes primero.

### `erp/`

Fase 3: generar las plantillas de Siesa. La estructura de las plantillas está en
`docs/plantillas_siesa.md`.

- `erp/terceros.py` → `fila_tercero`: toma una fila del reporte y arma la fila de la hoja
  `Terceros` (nombres en mayúsculas, razón social si es NIT, teléfono sin `57`, país `169`
  y ciudad partida en depto/ciudad, fecha de carga como fecha de nacimiento). `repartir_direccion` acomoda la dirección en los 3
  campos de 40 caracteres sin partir palabras. Si falta un dato obligatorio, el tercero
  sale como no cargable con la lista de lo que falta.
- `erp/clientes.py` → hojas `Clientes` (`fila_cliente`: valores fijos `001`, `W001`, `03D`,
  `C001`, `1`, `500` y los datos del tercero), `Imptos y Reten` (`filas_impuestos`: 3 filas
  por cliente, agrupadas por clase de impuesto) y `Ent. Dinamica Cliente` (`fila_entidad`:
  el correo).
- `erp/pedidos.py` → plantilla de pedidos. `validar_pedido` revisa cada línea (SKU, bodega,
  cantidad, precio) y saca el tipo de documento de la bodega (`CPW`, `CPT`, `CPM`);
  `numerar` asigna el consecutivo por bloques; `fila_pedido` arma el encabezado y
  `filas_movimiento` el detalle.
- `erp/run.py` → `generar_plantillas`: lee el reporte de la fase 1, deja una fila por
  cliente (la del pedido más reciente), escribe `terceros_<run_id>.xlsx` con las 4 hojas y el log
  `plantillas_<run_id>.csv`. `pedidos_cargables` dirá qué pedidos pueden ir en la
  plantilla de pedidos.

---

## 5. Conceptos de Python que aparecen en el código

| Concepto                                 | Ejemplo                                       | En palabras simples                                                                                                                     |
| ---------------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Anotaciones de tipo                      | `def to_decimal(value: object) -> Decimal:` | Indican qué recibe y qué devuelve la función. No cambian lo que hace; ayudan a leer y al editor a avisar errores                     |
| `from __future__ import annotations`   | Primera línea de casi todos los archivos     | Hace que Python no evalúe las anotaciones de tipo al ejecutar. Evita errores al usar tipos modernos o clases que se definen más abajo |
| `@dataclass`                           | `class ShopifyConfig:`                      | Clase para guardar datos: Python crea solo el constructor y la comparación                                                             |
| `frozen=True`                          | `@dataclass(frozen=True)`                   | El objeto no se puede modificar después de creado. Evita cambios accidentales                                                          |
| `__post_init__`                        | En`ShopifyConfig`, `OrderFilter`          | Código que corre justo después de crear el objeto. Aquí se usa para validar                                                          |
| `@property`                            | `result.reconciled`                         | Un cálculo que se lee como si fuera un dato, sin paréntesis                                                                           |
| `@classmethod`                         | `OrderFilter.last_n_days(7)`                | Una forma alternativa de crear el objeto                                                                                                |
| Generador (`yield`)                    | `extract_orders`, `paginate`              | En vez de devolver una lista completa, entrega un elemento a la vez. Ahorra memoria                                                     |
| `Protocol`                             | `TokenProvider`                             | Un "contrato": cualquier clase con esos métodos sirve                                                                                  |
| `Decimal`                              | `to_decimal("0.10")`                        | Números exactos para dinero (`0.1 + 0.2` con `float` da `0.30000000000000004`)                                                   |
| `with open(...) as fh:`                | En los sinks                                  | Abre el archivo y lo cierra solo, aunque haya un error                                                                                  |
| `try / except / raise`                 | En`client.py`                               | `try`: intenta. `except`: atrapa un tipo de error. `raise`: lanza (o relanza) el error                                            |
| `logger = logging.getLogger(__name__)` | Al inicio de cada archivo                     | Cada archivo firma sus mensajes con su nombre:`shopify_pipeline.shopify.client`                                                       |
| Nombres con`_`                         | `_cliente`, `_slim`                       | Convención: "uso interno de este archivo; desde fuera, no la llames"                                                                   |
| `a \| b` con diccionarios               | `base \| {"tipo_linea": "ENVIO"}`            | Une dos diccionarios en uno nuevo                                                                                                       |
| `Path`                                 | `Path("data/logs")`                         | Rutas de archivos que funcionan igual en Windows y Linux                                                                                |

---

## 6. Las pruebas (`tests/`)

Las pruebas **no** llaman a Shopify: la librería `responses` simula sus respuestas. Así se
puede probar un 429, un 500 o un token vencido sin depender de la tienda real.

| Archivo                   | Qué comprueba                                                                                                       |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `conftest.py`           | No es una prueba: prepara datos comunes (*fixtures*): un cliente falso, un filtro, la carga de archivos de ejemplo |
| `fixtures/`             | JSON de ejemplo: el pedido#1006 **anonimizado**, sus bodegas y una página de pedidos                          |
| `test_config.py`        | Validación del dominio, credenciales faltantes, secretos ocultos en logs                                            |
| `test_auth.py`          | Que el token se guarde, se renueve al vencer y ante un 401                                                           |
| `test_client.py`        | Paginación, 429, 5xx, errores de red, 403/404 y la pausa por el límite de llamadas                                 |
| `test_orders.py`        | Que el filtro arme bien los parámetros y que no se repitan pedidos                                                  |
| `test_fulfillment.py`   | La bodega por línea y qué pasa si falta el permiso                                                                 |
| `test_extract.py`       | El JSONL y el manifiesto de una corrida, el aviso cuando el conteo no cuadra y que no se sobrescriba una extracción |
| `test_state.py`         | Watermark, ventana incremental y registro de pedidos reportados                                                      |
| `test_erp_terceros.py` | Fase 3, hoja Terceros: cédula vs. NIT, datos obligatorios y reparto de la dirección en 3 campos de 40 |
| `test_erp_clientes.py` | Fase 3: valores fijos de `Clientes`, dirección en 2 campos, orden por bloques de `Imptos y Reten` y el correo en `Ent. Dinamica Cliente` |
| `test_erp_run.py` (pedidos) | Tipo de documento por bodega, consecutivo por bloques CPW → CPT → CPM, envío como línea más, y que un pedido no cargable no quede en ninguna plantilla |
| `test_erp_run.py` | Fase 3: el Excel de terceros (una fila por cliente, números y textos), el log de pedidos no cargables y el comando `plantillas` |
| `test_catalogos.py`     | Bodegas y ciudades de Siesa: tildes, apóstrofos, nombres repetidos y casos que no se adivinan                      |
| `test_reconciliation.py` | Fase 2 con exportes sintéticos: filas de título, CSV con `;`, referencias `1006.0`, faltantes y `--strict`       |
| `test_normalize.py`     | Cada función de limpieza con muchos casos (cédulas, NIT, teléfonos, apellidos)                                    |
| `test_siesa_lines.py`   | El pedido#1006 de punta a punta: filas, envío, cédula, exclusiones, alertas, aislamiento de errores y ledger    |
| `test_transform_run.py` | Que se escriban el CSV, el Excel y el log de alertas, y la validación del manifiesto                               |
| `test_sinks.py`         | La escritura atómica (que no quede un archivo a medias)                                                             |
| `test_cli.py`           | Los comandos completos, sus opciones, el modo incremental y los códigos de salida                                 |

**Cómo leer una prueba:** cada `test_...` arma una situación, ejecuta el código y verifica
el resultado con `assert`. Ejemplo:

```python
def test_split_apellidos():
    assert split_apellidos("De la Torre Gómez") == ("De la Torre", "Gómez")
```

**En GitHub:** cada push a `main` y cada pull request corre lint + pruebas en Windows y Linux
(`.github/workflows/ci.yml`).

**Correrlas:** `pytest` (todas) o `pytest tests/test_normalize.py -v` (un archivo, con detalle).
Conviene correrlas después de cada cambio: si algo se rompe, la prueba lo indica.

---

## 7. "Quiero cambiar X, ¿qué archivo toco?"

| Quiero...                                  | Archivo                                                                                 |
| ------------------------------------------ | --------------------------------------------------------------------------------------- |
| Cambiar la regla para identificar un NIT   | `transform/normalize.py` → `tipo_por_formato`                                      |
| Agregar una bodega nueva de Shopify        | `catalogos/bodegas_siesa.csv` (una fila; sin tocar código)                          |
| Corregir el código de una ciudad           | `catalogos/ciudades_siesa.csv`                                                      |
| Cambiar la tolerancia del total            | `transform/siesa_lines.py` → `TOLERANCIA_TOTAL`                                    |
| Agregar o quitar una columna del reporte   | `transform/siesa_lines.py` → `COLUMNS` y `order_to_lines`                        |
| Cambiar qué estados de pago pasan a Siesa | `transform/siesa_lines.py` → `DEFAULT_ESTADOS_PAGO` (o `--estados-pago`)         |
| Agregar una alerta nueva                   | `transform/alertas.py` (descripción) + `transform/siesa_lines.py` (cuándo ocurre) |
| Cambiar el código del ítem de envío     | `.env` → `SIESA_CODIGO_ENVIO` (sin tocar código)                                  |
| Cambiar la versión de la API de Shopify   | `.env` → `SHOPIFY_API_VERSION`                                                     |
| Cambiar cuántas veces se reintenta        | `config.py` → `max_attempts`                                                       |
| Agregar una opción de terminal            | `cli.py` → `build_parser`                                                          |
| Cambiar dónde se guardan los archivos     | Opciones`--output-dir`, `--processed-dir`, `--log-dir`, `--state-dir`             |
| Cambiar el solape del modo incremental     | `state.py` → `OVERLAP`                                                             |
| Volver a reportar un pedido ya reportado   | Quitar su id de `data/state/reportados.json`, o `transform --sin-ledger` para revisar |

Después de cualquier cambio: `pytest`. Si agregas una regla, agrega también una prueba en el
`test_...` del archivo que tocaste.
