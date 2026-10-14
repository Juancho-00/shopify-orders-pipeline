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
