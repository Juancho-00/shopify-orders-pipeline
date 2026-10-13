# shopify-orders-pipeline

Pipeline de integración **Shopify → ERP** para Luisa Chimá S.A.S.

| Fase             | Descripción                                                      | Estado       |
| ---------------- | ----------------------------------------------------------------- | ------------ |
| 1. Extracción   | Descarga los pedidos de Shopify (REST Admin API) a la zona`raw` | ✅ Lista     |
| 2. Conciliación | Verifica que los pedidos extraídos de Shopify existan en el ERP  | ⏳ Pendiente |
| 3. Carga al ERP  | Crea clientes y pedidos faltantes en el ERP según sus plantillas | ⏳ Pendiente |

```
Shopify ──(1) extract──► data/raw/shopify/orders/*.jsonl ──(2) reconcile──► faltantes ──(3) load──► ERP
                                     + manifest.json                              │
                                                                       data/reconciliation/
```

---

## Estructura del repositorio

```
shopify-orders-pipeline/
├── src/shopify_pipeline/
│   ├── config.py            # Configuración desde variables de entorno / .env
│   ├── exceptions.py        # Jerarquía de errores (auth, permisos, transitorios...)
│   ├── shopify/
│   │   ├── auth.py          # Token estático (legacy) o Client Credentials (Dev Dashboard)
│   │   ├── client.py        # HTTP: reintentos, rate limiting, paginación por Link header
│   │   └── orders.py        # Filtros de pedidos y extracción
│   ├── sinks/
│   │   ├── base.py          # Contrato Sink
│   │   └── jsonl.py         # Escritura atómica a JSON Lines
│   ├── extract.py           # Orquestación de la fase 1 + manifiesto de la corrida
│   ├── reconciliation/      # Fase 2 (pendiente)
│   ├── erp/                 # Fase 3 (pendiente)
│   └── cli.py               # Comando `shopify-pipeline`
├── tests/                   # Pruebas sin red (Shopify simulado con `responses`)
│   └── fixtures/            # Respuestas de ejemplo de Shopify (anonimizadas)
├── templates/erp/           # Plantillas de carga del ERP (fase 3; no se versionan)
├── data/                    # Salidas locales (no se versionan: datos personales)
├── docs/
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

| Modo                                       | Cuándo                                                                                                                                          | Variables                                        |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------ |
| **Client Credentials** (recomendado) | Apps creadas en el**Dev Dashboard** (obligatorio para apps nuevas desde el 1-ene-2026). El token dura ~24 h y el pipeline lo renueva solo. | `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` |
| **Token estático**                  | Custom app*legacy* creada en el admin de Shopify antes de 2026. Token permanente `shpat_...`.                                                | `SHOPIFY_ACCESS_TOKEN`                         |

### Crear la app en el Dev Dashboard

1. Shopify admin → **Settings → Apps → Develop apps → Build apps in Dev Dashboard**.
2. Crear la app → **Versions** → asignar el scope `read_orders` → **Release**.
   Si se necesitan pedidos de hace más de 60 días, agregar también `read_all_orders`.
3. Instalar la app en la tienda desde la pestaña **Home**.
4. Copiar **Client ID** y **Client secret** desde **Settings** al archivo `.env`.

**Principio de mínimo privilegio:** la fase 1 solo necesita permisos de lectura. No agregues scopes `write_*`.

---

## Fase 1: extracción de pedidos

```powershell
# Últimos 7 días, todos los estados (default)
shopify-pipeline extract

# Ventana explícita (fechas en UTC, o ISO con zona horaria)
shopify-pipeline extract --since 2026-10-01 --until "2026-10-08T00:00:00-05:00"

# Solo algunos campos (reduce el tamaño de la respuesta)
shopify-pipeline extract --days 3 --fields name,created_at,financial_status,total_price,customer,line_items

# Fallar (código 3) si el conteo no cuadra contra Shopify; útil en tareas programadas
shopify-pipeline extract --days 1 --strict

# Más detalle en el log
shopify-pipeline --log-level DEBUG extract --days 1
```

También funciona `python -m shopify_pipeline extract ...`.

### Salida

Cada corrida genera dos archivos con el mismo identificador (`run_id`, en UTC):

```
data/raw/shopify/orders/20261013T161500Z.jsonl           # un pedido por línea, tal cual lo entrega Shopify
data/raw/shopify/orders/20261013T161500Z.manifest.json   # metadatos de la corrida
```

```json
{
  "run_id": "20261013T161500Z",
  "shop_domain": "tienda.myshopify.com",
  "api_version": "2026-10",
  "status_filter": "any",
  "created_at_min": "2026-10-06T16:15:00+00:00",
  "created_at_max": "2026-10-13T16:15:00+00:00",
  "expected_count": 128,
  "written_count": 128,
  "duration_seconds": 3.4,
  "output_file": "20261013T161500Z.jsonl",
  "reconciled": true
}
```

El manifiesto es el contrato con la fase 2: indica qué ventana se extrajo y si el
conteo cuadró contra `orders/count.json` de Shopify.

### Códigos de salida

| Código | Significado                                                       | Acción                                      |
| ------- | ----------------------------------------------------------------- | -------------------------------------------- |
| `0`   | Éxito                                                            | —                                           |
| `1`   | Error transitorio (red, 5xx, 429) tras agotar reintentos          | Reintentar más tarde                        |
| `2`   | Configuración o credenciales (401, 403, 404,`.env` incompleto) | Corregir configuración; reintentar no sirve |
| `3`   | Extracción completa, pero el conteo no cuadra (`--strict`)     | Revisar antes de conciliar                   |

### Cómo funciona

- **Endpoint:** `GET https://{tienda}.myshopify.com/admin/api/2026-10/orders.json`
- **Paginación:** se sigue la URL `rel="next"` de la cabecera `Link`. Los filtros **no**
  se reenvían en las páginas siguientes: quedan dentro del cursor `page_info` y Shopify
  los rechaza si se repiten.
- **Rate limiting (leaky bucket):**
  - *Proactivo:* lee `X-Shopify-Shop-Api-Call-Limit` (p. ej. `36/40`); si el bucket pasa del 80 %, pausa hasta que drene al 50 %.
  - *Reactivo:* ante `429`, espera lo que indique `Retry-After` y reintenta.
- **Reintentos:** 5xx, timeouts y errores de red, con backoff exponencial y jitter (máx. 6 intentos).
- **Sin reintento:** 401 (salvo una renovación de token en modo Client Credentials), 403, 404 y demás 4xx.
- **Filtros:** `status=any` (Shopify usa `open` por defecto y omitiría cerrados y cancelados),
  ventana cerrada `created_at_min`/`created_at_max` fijada al iniciar la corrida, `limit=250`
  (el máximo) y proyección opcional con `fields`.
- **Escritura atómica:** se escribe a un temporal y se renombra al final; si algo falla,
  no queda un archivo a medias.

> **Nota sobre la API:** la REST Admin API es *legacy* desde octubre de 2024 (solo recibe
> correcciones de seguridad). Funciona para apps propias como esta, pero la evolución
> natural es migrar a la GraphQL Admin API. El cliente HTTP (`shopify/client.py`) y la
> lógica de pedidos (`shopify/orders.py`) están separados para que la migración solo
> toque esos dos módulos.

---

## Fase 2: conciliación con el ERP (pendiente)

Objetivo: comprobar que cada pedido extraído de Shopify exista en el ERP.

Diseño previsto (`src/shopify_pipeline/reconciliation/`):

1. Leer la última extracción de `data/raw/shopify/orders/` usando su manifiesto.
2. Consultar en el ERP los pedidos de la misma ventana de fechas.
3. Cruzar por la llave acordada (p. ej. `order.name` `#1001` o `order.id` de Shopify
   contra el campo de referencia externa del ERP).
4. Clasificar cada pedido:
   - **En ambos:** conciliado.
   - **Solo en Shopify:** faltante en el ERP → entrada de la fase 3.
   - **Solo en el ERP:** revisar (pedido manual o error de referencia).
   - **Con diferencias:** total, estado o cliente distintos.
5. Generar el reporte en `data/reconciliation/<run_id>/`.

**Información pendiente:**

- [ ] Nombre del ERP y forma de acceso (API, consulta a base de datos, exportación de archivo).
- [ ] Campo del ERP que guarda la referencia del pedido de Shopify.
- [ ] Reglas de comparación: qué diferencias en totales o estados se toleran.

---

## Fase 3: creación de clientes y pedidos en el ERP (pendiente)

Objetivo: crear en el ERP los clientes y pedidos que la fase 2 marque como faltantes,
usando las plantillas de carga del ERP.

Diseño previsto (`src/shopify_pipeline/erp/`):

1. Tomar los pedidos "solo en Shopify" de la fase 2.
2. Crear primero los clientes que no existan; después, los pedidos.
3. Mapear cada campo de Shopify a la columna de la plantilla, validando tipo, longitud
   y obligatoriedad antes de generar la carga.
4. Generar los archivos de carga (o llamar la API del ERP) de forma idempotente: volver
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
paginación, 429, 5xx, 401/403/404 y renovación de token.

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
