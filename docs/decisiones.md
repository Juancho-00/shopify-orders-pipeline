# Decisiones técnicas

Registro breve de decisiones de diseño y su motivo.

## 001 · REST Admin API para la fase 1 (2026-10-13)

- **Decisión:** usar la REST Admin API (`/admin/api/2026-10/orders.json`).
- **Motivo:** requisito inicial del proyecto; sigue funcionando para apps propias.
- **Consecuencia:** REST es *legacy* desde 2024-10. Se aisló en `shopify/client.py` y
  `shopify/orders.py` para poder migrar a GraphQL sin tocar el resto del pipeline.

## 002 · Autenticación con Client Credentials (2026-10-13)

- **Decisión:** soportar Client Credentials (Dev Dashboard) como modo principal y el
  token estático `shpat_` como alternativa.
- **Motivo:** desde el 1-ene-2026 Shopify no permite crear custom apps legacy. Los tokens
  de Client Credentials expiran en ~24 h, lo que reduce el impacto de una filtración.

## 003 · Zona raw en JSON Lines + manifiesto (2026-10-13)

- **Decisión:** guardar los pedidos sin transformar, uno por línea, con un manifiesto por corrida.
- **Motivo:** conservar la respuesta original permite reprocesar las fases 2 y 3 sin volver
  a llamar a Shopify. El manifiesto documenta la ventana y el conteo esperado.

## 004 · Bodega por pedido con fulfillment orders (2026-10-14)

- **Decisión:** obtener la bodega con `GET orders/{id}/fulfillment_orders.json`, una llamada
  por pedido, y guardarla en el JSONL crudo (`_fulfillment_orders`).
- **Motivo:** el pedido REST no trae la bodega por línea (`location_id` viene vacío).
- **Consecuencia:** con el límite estándar (2 llamadas/s), 200 pedidos tardan ~2 minutos.
  Es suficiente para el volumen actual. Si el volumen crece, la GraphQL Admin API trae
  pedidos y bodegas en una sola consulta paginada; es la ruta de migración recomendada.

## 005 · Cédula en el campo `company` (2026-10-14)

- **Decisión:** leer el documento de `billing_address.company` (respaldo
  `shipping_address.company`) y deducir el tipo (CC/NIT) por formato; para NIT, calcular el DV.
- **Motivo:** así lo configuró el equipo de Shopify (correo del 2026-10-14, pedido #1006).
- **Consecuencia:** el tipo de documento es una inferencia. Se recomienda capturarlo
  explícitamente en el checkout.
- **Actualización (2026-10-14):** la forma de identificar un NIT sigue **pendiente de
  definir**. Mientras tanto, los NIT deducidos solo por la regla de 9 dígitos se marcan
  `NIT_POR_VERIFICAR` en el log de alertas.

## 006 · Reporte Siesa: CSV + Excel, una fila por línea (2026-10-14)

- **Decisión:** generar el mismo reporte en CSV (cargas automáticas) y Excel (revisión).
- **Motivo:** Excel en español usa coma decimal y abre mal un CSV con punto decimal; en el
  .xlsx los montos son números reales.
- **Consecuencia:** se agrega la dependencia `openpyxl`.

## 007 · Alertas en un log aparte (2026-10-14)

- **Decisión:** sacar la columna `alertas` del reporte y registrar alertas y exclusiones
  en `data/logs/alertas_<run_id>.csv`, más una bitácora diaria `shopify_pipeline_AAAAMMDD.log`.
- **Motivo:** el reporte queda limpio, con solo la información que necesita Siesa; el log
  permite auditar cada corrida y no contiene datos personales.

## 008 · Solo pedidos con pago confirmado (2026-10-14)

- **Decisión:** extraer todos los pedidos (zona raw), pero pasar al reporte Siesa solo los
  de `financial_status` `paid` o `partially_refunded`. Los demás quedan como
  `PAGO_NO_CONFIRMADO` en el log. Configurable con `--estados-pago`.
- **Motivo:** definición de negocio: la integración con Siesa solo maneja pedidos con pago
  confirmado. Los pendientes se pueden leer, pero no se integran.
- **Consecuencia:** un pedido contraentrega pagado días después de creado no entra si la
  ventana se aplica sobre la fecha de creación. Se agregó `--filtrar-por actualizacion`
  (ventana sobre `updated_at`) para la ejecución programada.

## 009 · Precios con IVA incluido (2026-10-14)

- **Decisión:** enviar los precios de producto y envío tal como los cobra Shopify, con IVA
  incluido, sin transformación.
- **Observación:** en el pedido #1006 Shopify no calculó IVA sobre el envío
  (`tax_lines` vacío). Pendiente confirmar si el envío debe llevar IVA.

## 010 · Código más simple de leer (2026-10-14)

- **Decisión:** reemplazar la librería `tenacity` por un ciclo `for` explícito de reintentos
  (`client.py: _pedir_con_reintentos`), sacar la configuración de logs a `logs.py`, separar
  el catálogo de alertas en `transform/alertas.py` y eliminar código sin uso
  (`sinks/base.py`, `JsonlSink`, re-exportaciones en los `__init__.py`).
- **Motivo:** facilitar la lectura y el mantenimiento. El comportamiento no cambió: las
  mismas pruebas siguen pasando.
- **Consecuencia:** una dependencia menos (`tenacity`). La guía `docs/guia_codigo.md`
  explica cada archivo.

## 011 · Modo incremental con watermark y registro de reportados (2026-10-16)

- **Decisión:** agregar `extract --incremental`: la ventana va desde el fin de la última
  extracción completa (`data/state/watermark.json`) menos 30 min, sobre `updated_at`.
  Un registro de pedidos reportados (`data/state/reportados.json`) evita repetirlos entre
  reportes (`YA_REPORTADO`) y detecta los que cambiaron después (`CAMBIO_POST_REPORTE`).
- **Motivo:** con una ventana relativa (`--days 1`) una tarea que corre unos minutos tarde,
  o un día en que no corre, deja pedidos sin extraer; y las ventanas sobre `updated_at`
  repiten pedidos en varios reportes.
- **Consecuencia:** el estado vive en JSON reemplazado de forma atómica, no en SQLite,
  porque `data/` se mantiene en Google Drive (decisión del equipo). Una sola máquina debe
  ejecutar la tarea programada. El watermark solo avanza si la extracción cuadró.

## 012 · Errores tipados, aislamiento por pedido y nuevos códigos de salida (2026-10-16)

- **Decisión:** `ConfigError` (código 2) y `DataError` (código 4) reemplazan al `ValueError`
  genérico; un error no previsto devuelve `5` y uno de archivo (Excel abierto, Drive
  sincronizando) devuelve `1`. Cada pedido se transforma aislado: si falla, queda como
  `ERROR_TRANSFORMACION` y los demás siguen. Con `--strict`, esos errores devuelven `4`.
- **Motivo:** un solo pedido con un monto mal formado tumbaba el reporte completo y la
  tarea programada lo reportaba como "error de configuración"; cualquier excepción no
  prevista salía con `1` ("reintentar"), igual que un error de red.

## 013 · Manifiesto como contrato y zona raw inmutable (2026-10-16)

- **Decisión:** el manifiesto registra `fields`, `incremental` y `schema_version`, y se
  escribe de forma atómica. `transform` lo valida: se detiene si la extracción se hizo con
  `--fields` sin los campos críticos y avisa si el conteo no cuadró. Con `--fields`, la CLI
  agrega siempre los campos que necesita el reporte (salvo `--solo-raw`). Una extracción
  nunca sobrescribe otra con el mismo `run_id`.
- **Motivo:** sin `test` ni `cancelled_at` (proyectados fuera con `--fields`), los pedidos
  de prueba y cancelados pasaban al reporte en silencio.

## 014 · CI y hooks de pre-commit (2026-10-16)

- **Decisión:** agregar `.github/workflows/ci.yml` (ruff, pruebas en Windows y Linux con
  Python 3.10 y 3.12, gitleaks sobre el historial) y `.pre-commit-config.yaml` (ruff,
  gitleaks, llaves privadas, archivos de más de 500 KB).
- **Motivo:** el README los mencionaba como controles de seguridad, pero no existían en el repo.

## 015 · Descuento prorrateado en reembolsos parciales (2026-10-16)

- **Decisión:** si `current_quantity` es menor que `quantity`, el descuento de la línea se
  prorratea: `descuento × current_quantity / quantity`.
- **Motivo:** Shopify calcula `discount_allocations` sobre la cantidad original. Restar el
  descuento completo a menos unidades dejaba la línea subvaluada.

## 016 · Bodega solo para pedidos que van al reporte (2026-10-16)

- **Decisión:** por defecto, `fulfillment_orders.json` se consulta solo para pedidos pagados,
  no cancelados ni de prueba y no reportados antes. `--bodega-todos` restaura el
  comportamiento anterior. El manifiesto registra `bodegas_omitidas`.
- **Motivo:** es la parte más lenta de la extracción (una llamada por pedido, ~2 por
  segundo). Los pedidos excluidos no necesitan bodega; un contraentrega pendiente se
  consultará en la corrida en que se confirme su pago.
- **Consecuencia:** un JSONL crudo no trae bodega para los pedidos omitidos. Regenerarlo con
  `transform --estados-pago todos` los mostrará con `BODEGA_NO_CONSULTADA`.

## 017 · Fechas de `--since` / `--until` en hora Colombia (2026-10-16)

- **Decisión:** una fecha sola (`2026-10-01`) es la medianoche en hora Colombia (UTC-5), no
  en UTC. Una fecha con zona horaria explícita se respeta.
- **Motivo:** "pedidos del 1 de octubre" debe ser el día de la tienda. En UTC la ventana
  empezaba a las 19:00 del día anterior.

## 018 · Segundo conteo antes de declarar un descuadre (2026-10-16)

- **Decisión:** si lo extraído no coincide con el conteo inicial, se cuenta de nuevo al
  final (`recount_count`). La extracción cuadra si el segundo conteo coincide con lo
  extraído.
- **Motivo:** con la ventana sobre `updated_at`, un pedido modificado durante la corrida
  sale de la ventana y `--strict` fallaba (código 3) sin que se hubiera perdido nada; en
  modo incremental eso además impedía avanzar el watermark. La ventana es fija, así que un
  pedido solo puede salir de ella, nunca entrar; ese pedido entra en la corrida siguiente.
