# shopify-orders-pipeline

Pipeline de integración **Shopify → Siesa** para Luisa Chimá S.A.S.

| Fase | Descripción | Estado |
|---|---|---|
| 1. Extracción | Descarga los pedidos de Shopify y genera el reporte línea por línea para Siesa | ✅ Lista |
| 2. Conciliación | Verifica que los pedidos extraídos de Shopify existan en Siesa | ⏳ Pendiente |
| 3. Carga a Siesa | Crea clientes y pedidos faltantes en Siesa según sus plantillas | ⏳ Pendiente |

```
                  (1) extract                                 (1) transform
Shopify ──────────────────────────► data/raw/...jsonl ─────────────────────► data/processed/siesa/
  pedidos + bodega por pedido        + manifest.json                         pedidos_siesa_<run>.csv / .xlsx
                                                                                      │
                                                    (2) reconcile ◄───────────────────┘
                                                          │
                                                    (3) load ──► Siesa
```

---

## Estructura del repositorio

> ¿Primera vez leyendo el código? Empieza por [`docs/guia_codigo.md`](docs/guia_codigo.md).

```
shopify-orders-pipeline/
├── src/shopify_pipeline/
│   ├── cli.py               # Comando `shopify-pipeline` (extract, transform) y códigos de salida
│   ├── logs.py              # Bitácora: consola + archivo diario
│   ├── config.py            # Configuración desde variables de entorno / .env
│   ├── exceptions.py        # Jerarquía de errores (auth, permisos, transitorios...)
│   ├── shopify/
│   │   ├── auth.py          # Token estático (legacy) o Client Credentials (Dev Dashboard)
│   │   ├── client.py        # HTTP: reintentos, rate limiting, paginación por Link header
│   │   ├── orders.py        # Filtros de pedidos y extracción
│   │   └── fulfillment.py   # Bodega de salida de cada línea (fulfillment orders)
│   ├── transform/
│   │   ├── normalize.py     # Nombres, apellidos, cédula/NIT, teléfono, fechas, montos
│   │   ├── siesa_lines.py   # Pedido → filas para Siesa (productos + envío) y exclusiones
│   │   ├── alertas.py       # Catálogo de alertas y exclusiones del log
│   │   └── run.py           # JSONL crudo → CSV + Excel + log de alertas
│   ├── sinks/
│   │   ├── jsonl.py         # Escritura atómica a JSON Lines
│   │   └── tabular.py       # CSV y Excel
│   ├── extract.py           # Orquestación de la extracción + manifiesto de la corrida
│   ├── reconciliation/      # Fase 2 (pendiente)
│   └── erp/                 # Fase 3 (pendiente)
├── tests/                   # Pruebas sin red (Shopify simulado con `responses`)
│   └── fixtures/            # Respuestas de ejemplo de Shopify (anonimizadas)
├── templates/erp/           # Plantillas de carga del ERP (fase 3; no se versionan)
├── data/                    # Salidas locales (no se versionan: datos personales)
├── docs/
│   ├── guia_codigo.md       # Para qué sirve cada archivo .py, explicado paso a paso
│   ├── mapeo_siesa.md       # Origen y regla de cada columna del reporte (para el ticket de Siesa)
│   └── decisiones.md        # Decisiones técnicas y su motivo
├── .github/workflows/ci.yml # Lint + pruebas en cada push / PR
├── .env.example             # Plantilla de credenciales (sin secretos)
├── .pre-commit-config.yaml  # ruff + gitleaks (bloquea tokens en commits)
└── pyproject.toml           # Dependencias, comando CLI, configuración de ruff/pytest
```

---

## Instalación

Requiere Python 3.10 o superior.

> ⚠️ **Crea el entorno virtual fuera de Google Drive.** Un `.venv` tiene miles de archivos
> y la sincronización de Drive lo vuelve lento o lo corrompe. Usa conda o un venv en una
> carpeta local (p. ej. `C:\venvs\shopify-pipeline`).

**Con conda (PowerShell):**

```powershell
conda create -n shopify-pipeline python=3.12 -y
conda activate shopify-pipeline
cd "G:\Unidades compartidas\TI\002 - Juan Pablo Quintero\Shopify\shopify-orders-pipeline"
pip install -e ".[dev]"
pre-commit install
```

**Con venv (PowerShell):**

```powershell
python -m venv C:\venvs\shopify-pipeline
C:\venvs\shopify-pipeline\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install
```

Verifica la instalación:

```powershell
shopify-pipeline --version
pytest
```

---

## Configuración de credenciales

1. Copia `.env.example` como `.env` y completa los valores. `.env` nunca se sube al repo.
2. Usa el **dominio interno** `tu-tienda.myshopify.com`, no el dominio público.
3. Elige **uno** de los dos modos de autenticación:

| Modo | Cuándo | Variables |
|---|---|---|
| **Client Credentials** (recomendado) | Apps creadas en el **Dev Dashboard** (obligatorio para apps nuevas desde el 1-ene-2026). El token dura ~24 h y el pipeline lo renueva solo. | `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` |
| **Token estático** | Custom app *legacy* creada en el admin de Shopify antes de 2026. Token permanente `shpat_...`. | `SHOPIFY_ACCESS_TOKEN` |

### Crear la app en el Dev Dashboard

1. Shopify admin → **Settings → Apps → Develop apps → Build apps in Dev Dashboard**.
2. Crear la app → **Versions** → asignar los scopes → **Release**:

   | Scope | Para qué |
   |---|---|
   | `read_orders` | Leer pedidos (últimos 60 días) |
   | `read_merchant_managed_fulfillment_orders` | Bodega de salida de cada producto |
   | `read_locations` | Listar bodegas para armar la tabla de equivalencias con Siesa |
   | `read_all_orders` *(opcional)* | Solo si se necesitan pedidos de hace más de 60 días |

   Los datos personales del cliente (nombre, dirección, teléfono, email) son *datos
   protegidos* en Shopify. Una app personalizada instalada en la propia tienda los recibe
   sin trámite adicional; si llegan vacíos (`null`), hay que revisar ese permiso en la app.
3. Instalar la app en la tienda desde la pestaña **Home**.
4. Copiar **Client ID** y **Client secret** desde **Settings** al archivo `.env`.

**Principio de mínimo privilegio:** la fase 1 solo necesita permisos de lectura. No agregues scopes `write_*`.

---

## Fase 1: extracción de pedidos y reporte para Siesa

```powershell
# Últimos 7 días: extrae, consulta bodegas y genera el reporte Siesa (default)
shopify-pipeline extract

# Pedidos de ayer en adelante, con el código real del ítem de envío en Siesa
shopify-pipeline extract --days 1 --codigo-envio FLETE01

# Rehacer el reporte de la última extracción sin llamar a Shopify (p. ej. tras cambiar una regla)
shopify-pipeline transform

# Ventana explícita (fechas en UTC, o ISO con zona horaria)
shopify-pipeline extract --since 2026-10-01 --until "2026-10-08T00:00:00-05:00"

# Solo algunos campos (reduce el tamaño de la respuesta)
shopify-pipeline extract --days 3 --fields name,created_at,financial_status,total_price,customer,line_items

# Sin consultar bodegas (una llamada menos por pedido)
shopify-pipeline extract --sin-bodega

# Ventana sobre la fecha de última actualización (recomendado para la tarea programada)
shopify-pipeline extract --days 2 --filtrar-por actualizacion

# Incluir pedidos cancelados o de prueba (se excluyen por defecto)
shopify-pipeline extract --incluir-cancelados --incluir-pruebas

# Incluir pedidos sin pago confirmado (solo para revisión; no para cargar a Siesa)
shopify-pipeline extract --estados-pago todos

# Fallar (código 3) si el conteo no cuadra contra Shopify; útil en tareas programadas
shopify-pipeline extract --days 1 --strict

# Más detalle en el log
shopify-pipeline --log-level DEBUG extract --days 1
```

También funciona `python -m shopify_pipeline extract ...`.

### Salida

Cada corrida genera estos archivos con el mismo identificador (`run_id`, en UTC):

```
data/raw/shopify/orders/20261013T161500Z.jsonl              # todos los pedidos de la ventana (Shopify + _fulfillment_orders)
data/raw/shopify/orders/20261013T161500Z.manifest.json      # metadatos de la corrida
data/processed/siesa/pedidos_siesa_20261013T161500Z.csv     # reporte para cargas automáticas
data/processed/siesa/pedidos_siesa_20261013T161500Z.xlsx    # el mismo reporte para revisar en Excel
data/logs/alertas_20261013T161500Z.csv                      # alertas y pedidos excluidos
data/logs/shopify_pipeline_20261013.log                     # bitácora de todas las ejecuciones del día
```

> Abre el **.xlsx** en Excel. El .csv usa punto decimal y Excel en español lo interpretaría mal.

Manifiesto de la corrida:

```json
{
  "run_id": "20261013T161500Z",
  "shop_domain": "tienda.myshopify.com",
  "api_version": "2026-10",
  "status_filter": "any",
  "date_field": "created_at",
  "date_min": "2026-10-06T16:15:00+00:00",
  "date_max": "2026-10-13T16:15:00+00:00",
  "expected_count": 128,
  "written_count": 128,
  "bodegas_consultadas": 128,
  "duration_seconds": 64.2,
  "output_file": "20261013T161500Z.jsonl",
  "reconciled": true
}
```

El manifiesto es el contrato con la fase 2: indica qué ventana se extrajo y si el
conteo cuadró contra `orders/count.json` de Shopify.

### Reporte para Siesa

Una fila por producto, más una fila de envío cuando el envío cobrado es mayor a cero.
El detalle de cada columna (origen en Shopify y regla) está en
[`docs/mapeo_siesa.md`](docs/mapeo_siesa.md).

Ejemplo con el pedido de prueba #1006 (datos del cliente anonimizados):

| documento_referencia | tipo_documento | numero_documento | primer_nombre | primer_apellido | tipo_linea | referencia | bodega | cantidad | precio_unitario |
|---|---|---|---|---|---|---|---|---|---|
| 1006 | CC | 1017000001 | Laura | Restrepo | PRODUCTO | KITK0108 | Bodega Principal Medellín | 1 | 89999.00 |
| 1006 | CC | 1017000001 | Laura | Restrepo | ENVIO | ENVIO | | 1 | 12294.34 |

Reglas clave:

- **Solo pago confirmado:** se extraen todos los pedidos, pero al reporte solo pasan los de
  estado `paid` o `partially_refunded`. Cancelados y de prueba también se excluyen.
- **Cédula / NIT:** se lee de `billing_address.company` (respaldo: `shipping_address.company`),
  se limpia (sin puntos ni espacios) y se deduce si es CC o NIT. La regla para identificar
  NIT es provisional: los NIT deducidos solo por formato quedan como `NIT_POR_VERIFICAR`.
- **Envío:** solo genera línea si el valor cobrado es mayor a cero.
- **Precios:** producto y envío van con IVA incluido, tal como los cobra Shopify.
- **Control de totales:** la suma de las líneas debe ser igual al total del pedido en Shopify.

### Log de alertas

Las alertas no van en el reporte. Cada corrida escribe `data/logs/alertas_<run_id>.csv`
con una fila por evento, sin datos personales del cliente:

| tipo | codigo | pedido_shopify | numero_linea | detalle |
|---|---|---|---|---|
| ALERTA | NIT_POR_VERIFICAR | #1010 | | |
| ALERTA | SIN_SKU | #1011 | 2 | |
| EXCLUIDO | PAGO_NO_CONFIRMADO | #1012 | | estado_pago=pending |

Revisa este archivo antes de cargar a Siesa. La lista completa de códigos está en
[`docs/mapeo_siesa.md`](docs/mapeo_siesa.md#log-de-alertas).

### Pedidos que se pagan días después (contraentrega)

Por defecto la ventana se aplica sobre la **fecha de creación**. Un pedido contraentrega
creado el lunes y pagado el jueves se lee el lunes como `pending` (queda excluido) y la
extracción del jueves ya no lo incluye. Para la ejecución programada usa:

```powershell
shopify-pipeline extract --days 2 --filtrar-por actualizacion
```

Así la ventana se aplica sobre la **última modificación**: cuando se registra el pago, el
pedido se actualiza y entra en la corrida de ese día. Un mismo pedido puede volver a
aparecer si se modifica después (por ejemplo, al despacharlo); la conciliación de la fase 2
evitará cargarlo dos veces en Siesa.

### Códigos de salida

| Código | Significado | Acción |
|---|---|---|
| `0` | Éxito | — |
| `1` | Error transitorio (red, 5xx, 429) tras agotar reintentos | Reintentar más tarde |
| `2` | Configuración o credenciales (401, 403, 404, `.env` incompleto) | Corregir configuración; reintentar no sirve |
| `3` | Extracción completa, pero el conteo no cuadra (`--strict`) | Revisar antes de conciliar |

### Cómo funciona

- **Endpoint:** `GET https://{tienda}.myshopify.com/admin/api/2026-10/orders.json`
- **Paginación:** se sigue la URL `rel="next"` de la cabecera `Link`. Los filtros **no**
  se reenvían en las páginas siguientes: quedan dentro del cursor `page_info` y Shopify
  los rechaza si se repiten.
- **Rate limiting (leaky bucket):**
  - *Proactivo:* lee `X-Shopify-Shop-Api-Call-Limit` (p. ej. `36/40`); si el bucket pasa del 80 %, pausa hasta que drene al 50 %.
  - *Reactivo:* ante `429`, espera lo que indique `Retry-After` y reintenta.
- **Reintentos:** 5xx, timeouts y errores de red, con espera creciente y aleatoria (máx. 6 intentos).
- **Sin reintento:** 401 (salvo una renovación de token en modo Client Credentials), 403, 404 y demás 4xx.
- **Filtros:** `status=any` (Shopify usa `open` por defecto y omitiría cerrados y cancelados),
  ventana cerrada fijada al iniciar la corrida sobre `created_at` o `updated_at`
  (`--filtrar-por`), `limit=250` (el máximo) y proyección opcional con `fields`.
- **Bodega:** el pedido no trae la bodega por línea; se consulta
  `orders/{id}/fulfillment_orders.json` (una llamada por pedido, con el mismo control de
  rate limit). Si falta el permiso, la extracción continúa y marca `BODEGA_NO_CONSULTADA`.
- **Escritura atómica:** se escribe a un temporal y se renombra al final; si algo falla,
  no queda un archivo a medias.

> **Nota sobre la API:** la REST Admin API es *legacy* desde octubre de 2024 (solo recibe
> correcciones de seguridad). Funciona para apps propias como esta, pero la evolución
> natural es migrar a la GraphQL Admin API. El cliente HTTP (`shopify/client.py`) y la
> lógica de pedidos (`shopify/orders.py`) están separados para que la migración solo
> toque esos dos módulos.

---

## Fase 2: conciliación con Siesa (pendiente)

Objetivo: comprobar que cada pedido extraído de Shopify exista en Siesa. La llave de cruce
es `documento_referencia` (consecutivo de Shopify, p. ej. `1006`).

Diseño previsto (`src/shopify_pipeline/reconciliation/`):

1. Leer la última extracción de `data/raw/shopify/orders/` usando su manifiesto.
2. Consultar en Siesa los pedidos de la misma ventana de fechas.
3. Cruzar por la llave acordada (p. ej. `order.name` `#1001` o `order.id` de Shopify
   contra el campo de referencia externa de Siesa).
4. Clasificar cada pedido:
   - **En ambos:** conciliado.
   - **Solo en Shopify:** faltante en Siesa → entrada de la fase 3.
   - **Solo en Siesa:** revisar (pedido manual o error de referencia).
   - **Con diferencias:** total, estado o cliente distintos.
5. Generar el reporte en `data/reconciliation/<run_id>/`.

**Información pendiente:**

- [ ] Forma de acceso a Siesa (API, consulta a base de datos, exportación de archivo).
- [ ] Campo de Siesa que guarda el documento de referencia de Shopify.
- [ ] Reglas de comparación: qué diferencias en totales o estados se toleran.

---

## Fase 3: creación de clientes y pedidos en Siesa (pendiente)

Objetivo: crear en Siesa los clientes y pedidos que la fase 2 marque como faltantes,
usando las plantillas de carga de Siesa.

Diseño previsto (`src/shopify_pipeline/erp/`):

1. Tomar los pedidos "solo en Shopify" de la fase 2.
2. Crear primero los clientes que no existan; después, los pedidos.
3. Mapear cada campo de Shopify a la columna de la plantilla, validando tipo, longitud
   y obligatoriedad antes de generar la carga.
4. Generar los archivos de carga (o llamar la API de Siesa) de forma idempotente: volver
   a ejecutar no debe duplicar clientes ni pedidos.

**Información pendiente:**

- [ ] Plantillas de cliente y de pedido (ver `templates/erp/README.md`).
- [ ] Por columna: tipo de dato, longitud, obligatoriedad, origen en Shopify o valor fijo.
- [ ] Llave para saber si un cliente ya existe (NIT / cédula / correo).

---

## Desarrollo

```powershell
pytest                       # pruebas
pytest --cov                 # pruebas con cobertura
ruff check . ; ruff format . # lint y formato
pre-commit run --all-files   # todos los hooks
```

Las pruebas no llaman a Shopify: la librería `responses` simula la API, incluyendo
paginación, 429, 5xx, 401/403/404, renovación de token y bodegas. La transformación se
prueba con el pedido real #1006 **anonimizado** (`tests/fixtures/order_1006.json`): nunca
guardes en el repo pedidos con datos reales de clientes.

## Seguridad

- Los secretos solo viven en `.env` (local) o en el gestor de secretos del entorno de ejecución.
- `.env`, `data/` y las plantillas reales del ERP están en `.gitignore`.
- `gitleaks` en pre-commit bloquea commits que contengan tokens.
- Los secretos nunca aparecen en logs ni en `repr()` de los objetos.
- Usa scopes de solo lectura y renueva credenciales si alguien que tuvo acceso deja el equipo.
- `data/` contiene datos personales de clientes (nombres, correos, direcciones). Esta carpeta
  está dentro de una unidad compartida: limita quién tiene acceso o apunta `--output-dir`
  a una ruta con acceso restringido.

## Git y Google Drive

Una carpeta `.git` dentro de Google Drive puede corromperse si dos equipos sincronizan al
mismo tiempo. Recomendado: usar un remoto (GitHub o Azure DevOps) como fuente de verdad y
hacer `git push` con frecuencia, o clonar el repo en una carpeta local para trabajar.
