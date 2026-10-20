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

## 019 · Ejecución diaria con el Programador de tareas de Windows (2026-10-19)

- **Decisión:** la tarea programada corre `scripts/ejecutar_pipeline.ps1`, que ejecuta
  `extract --incremental --strict`; se registra con `scripts/registrar_tarea.ps1`. Un único
  reintento a los 10 minutos, solo ante código 1. Historial en `data/logs/ejecuciones.csv`.
- **Motivo:** el modo incremental (decisión 011) ya cubre corridas fallidas o atrasadas; el
  reintento cubre caídas breves sin esperar al día siguiente.
- **Consecuencia:** como `data/` vive en Google Drive, la tarea corre con el usuario que tiene
  Drive iniciado y solo con su sesión abierta; el script espera hasta 15 minutos a que G:
  esté disponible. Un solo equipo debe tener la tarea registrada.
- **Definido el 2026-10-19:** ver decisión 025.

## 020 · Catálogos de bodegas y ciudades de Siesa en el paquete (2026-10-19)

- **Decisión:** las tablas de equivalencia viajan con el código en
  `src/shopify_pipeline/catalogos/` (`bodegas_siesa.csv`, `ciudades_siesa.csv`) y se leen con
  `transform/catalogos.py`. La comparación ignora tildes, mayúsculas y apóstrofos (`D’Luchi` =
  `D'Luchi`). `SIESA_CATALOGOS_DIR` permite usar otra carpeta.
- **Motivo:** R-09 y R-11. Son datos de configuración, no de clientes. Así quedan versionados
  y probados, y un cambio de bodega se revisa como cualquier otro cambio.
- **Consecuencia:** el reporte trae `bodega_siesa` y `codigo_ciudad_siesa`. Lo que no
  tiene equivalencia genera `BODEGA_SIN_EQUIVALENCIA` o `CIUDAD_SIN_CODIGO`. Una ciudad con
  nombre repetido se busca dentro del departamento del pedido; si sigue siendo ambigua, no se
  adivina.

## 021 · Tipo de documento por formato del número (2026-10-19)

- **Decisión:** se aplica R-06 (NIT = 9 dígitos con prefijo 800/900/901; CC = 7–8 dígitos o
  10 dígitos). El reporte usa los códigos de Siesa `C` y `N` (R-10). *Ajustada por la 024.*
- **Consecuencia:** un número que no encaja ya no se asume como CC: queda sin tipo y con
  `TIPO_DOCUMENTO_NO_IDENTIFICADO`. CE y pasaporte quedan con `TIPO_DOCUMENTO_SIN_CODIGO_SIESA`
  hasta que Siesa defina su código.

## 022 · Precio neto en pesos enteros y tolerancia de $50 (2026-10-19)

- **Decisión** (*ajustada por la 024*): el precio que va a Siesa es el neto por unidad (sin descuento aparte, R-13),
  redondeado a pesos (R-23). El envío usa `SERV01` (R-08), IVA 19 % incluido (R-07) y la bodega
  de los productos. El total se valida con tolerancia de $50 (R-24).
- **Motivo:** Siesa no recibe descuentos ni decimales, y la plantilla usa `ind_precio = 2`
  (liquida con el precio enviado).
- **Consecuencia:** cambian las columnas del reporte: se agregan `precio_neto`,
  `bodega_siesa`, `codigo_ciudad_siesa` y `direccion_complemento` (la dirección ya no se une
  con el complemento, porque la plantilla los separa).

## 023 · Conciliación con el exporte de Siesa (2026-10-19)

- **Decisión:** fase 2 = comando `conciliar`. Lee el exporte más reciente de
  `data/siesa/exportes/` (xlsx/csv) y verifica que cada pedido de los reportes oficiales
  (no los `_revision`) de los últimos 30 días tenga su número en `_num_docto_referencia`
  (R-20 a R-22). Resultado en `data/reconciliation/`.
- **Motivo:** R-20 opción C, sin permisos técnicos sobre Siesa. El lector busca la fila de
  encabezados y normaliza `#1006` / `1006.0` para que el cruce no falle por formato.
- **Consecuencia:** `--strict` devuelve código 3 si falta algún pedido. Falta probarlo con un
  exporte real.

## 024 · Aclaraciones del 2026-10-19: Client Credentials, dos precios, CC de 10 dígitos

- **Autenticación:** la conexión con Shopify se hace con **Client Credentials** (app del Dev
  Dashboard). `SHOPIFY_ACCESS_TOKEN` queda solo como respaldo en el código y comentado en
  `.env.example`.
- **Precios:** el reporte trae `precio_unitario` (precio del ítem) y `precio_neto` (con el
  descuento aplicado). A Siesa se sube `precio_neto`. Todo en pesos enteros, redondeados al
  peso más cercano.
- **Cédulas:** cualquier número de 10 dígitos es CC, no solo los que empiezan por 10/11. Se
  exceptúa un NIT de 800/900/901 con su DV pegado (`9001234567`), que se detecta porque el
  último dígito coincide con el DV calculado.
- **Exporte de Siesa:** confirmado con el exporte real: `Nro documento` (`CPM-00003210`) y
  `_num_docto_referencia`. La conciliación muestra el `Nro documento` como `documento_siesa`.

## 025 · Equipo, usuario, hora y revisión de la tarea diaria (2026-10-19)

- **Decisión:** la tarea corre en el equipo de Juan Pablo Quintero, con su usuario de Windows,
  a las 6:30 a. m. El equipo se entrega con la tarea instalada. La revisión diaria la hace él
  por ahora y después el asistente o un digitador; se escala a TI o al encargado del
  e-commerce según el error. La exportación de Siesa para la conciliación la hace una persona;
  a futuro se evaluará un agente de IA.
- **Riesgo:** la tarea depende de que ese usuario de Windows y su cuenta de Google Drive sigan
  activos después de la entrega. Si se desactivan, la tarea deja de correr sin avisar.

## 026 · Hoja `Terceros` de la plantilla de clientes (2026-10-19)

- **Decisión:** columnas definidas por TI (ver `plantillas_siesa.md`). Teléfono y celular sin
  el indicativo `57`; país siempre `169`; fecha de nacimiento = fecha de la carga como número
  `AAAAMMDD`; direcciones de máximo 40 caracteres repartidas en 3 campos sin partir palabras.
  Comando `shopify-pipeline plantillas`, salida en `data/siesa/cargas/`.
- **Una fila por cliente:** si un cliente compró varias veces en la misma corrida, se envía
  una vez, con los datos del pedido más reciente (R-31 pide subirlo con cada compra; dentro de
  un mismo archivo, repetirlo no aporta nada).
- **Datos faltantes:** el tercero no se genera y el pedido queda con `TERCERO_INCOMPLETO`
  (R-34). El log solo dice qué campo falta, nunca el dato del cliente.

## 027 · Hojas `Clientes`, `Imptos y Reten` y `Ent. Dinamica Cliente` (2026-10-19)

- **Decisión:** columnas definidas por TI (ver `plantillas_siesa.md`). Las tres hojas se arman
  desde la fila de `Terceros`, para que los datos del cliente sean idénticos en las cuatro.
  `Imptos y Reten` lleva 3 filas por cliente (46/1/1, 47/1/0, 47/41/1), agrupadas por clase
  como en la plantilla de ejemplo.
- **Formato:** se replica el de `terceros_vtex.xlsx`. Los documentos van como número y todo lo
  demás como texto, incluidas las fechas `AAAAMMDD` (ajusta la 026, que guardaba la fecha de
  nacimiento como número).
- **Dirección en `Clientes`:** solo tiene 2 campos; el segundo une los campos 2 y 3 de
  `Terceros` (normalmente, el complemento). Si no cabe en 40 caracteres: `DIRECCION_TRUNCADA`.

## 028 · Razón social desde `company`, orden del nombre y datos obligatorios (2026-10-20)

- **Razón social:** sale del campo `company` (`billing_address`, respaldo `shipping_address`),
  donde la empresa escribe su NIT y su nombre. El pipeline separa el número del nombre
  (`separar_company`); el número sigue las reglas de la R-06. Un NIT sin nombre usa el de
  facturación con la alerta `RAZON_SOCIAL_DESDE_NOMBRE`. El campo `order.company` de Shopify
  (B2B) no sirve: en la REST API solo trae identificadores, no el nombre.
- **Nombre completo:** en orden APELLIDOS NOMBRES en `F015_CONTACTO` y
  `F201_DESCRIPCION_SUCURSAL`. Con NIT, apellidos y nombres van vacíos.
- **Obligatorios:** email y teléfono se suman a los datos sin los cuales el cliente no se
  carga (R-34), porque son requeridos para la facturación electrónica.
- **Dirección en `Clientes`:** confirmado unir los campos 2 y 3 de `Terceros`, máximo 40.

## 029 · Plantilla de pedidos (2026-10-20)

- **Decisión:** columnas definidas por TI (ver `plantillas_siesa.md`). El tipo de documento
  sale de la bodega de salida (nueva columna `tipo_docto_siesa` en `bodegas_siesa.csv`): CEDI
  → `CPW`, tiendas → `CPT`, Melonn → `CPM`. El consecutivo empieza en 1 por tipo y los
  pedidos van por bloques CPW → CPT → CPM. Las fechas son la de la carga. Precio = precio neto.
- **Un pedido, todo o nada:** si no se puede cargar (cliente incompleto, línea sin SKU o
  bodega, bodega sin tipo de documento o bodegas de tipos distintos), no va en ninguna de las
  dos plantillas, para no dejar clientes sin pedido ni pedidos sin cliente.
- **Resuelto en la 030:** vending no se carga y no hay pedidos con bodegas de tipos distintos.
- **NIT:** lleva las mismas 3 filas de impuestos que una persona y el DV no va en la plantilla.

## 030 · Vending fuera de Siesa y notas de 500 caracteres (2026-10-20)

- **Vending:** los pedidos de las 4 bodegas de vending no se cargan a Siesa. Se marcan en
  `bodegas_siesa.csv` con `tipo_docto_siesa = NO_CARGA` (distinto de vacío, que significa
  "falta configurar"). No entran en las plantillas (`BODEGA_NO_SE_CARGA`, sin contar como
  error para `--strict`) y en la conciliación salen como `NO_SE_CARGA`, para no reportarlos
  como faltantes en Siesa. Siguen en el reporte de la fase 1, como registro.
- **Bodegas mixtas:** TI confirma que no hay pedidos con productos de bodegas de tipos
  distintos. Se deja la validación `PEDIDO_BODEGAS_MIXTAS` solo como control.
- **Notas:** `_notas` se corta a 500 caracteres, el límite de Siesa, con la alerta
  `NOTAS_RECORTADAS`.

## 031 · La corrida diaria también genera las plantillas (2026-10-20)

- **Decisión:** `scripts/ejecutar_pipeline.ps1` corre dos pasos: `extract --incremental
  --strict` y, si dejó un reporte nuevo en esa corrida, `plantillas --input <reporte> --strict`.
  La persona encargada solo valida y sube las plantillas. La tarea pasa a llamarse
  `Shopify Pipeline - Corrida diaria`.
- **Por qué solo con reporte nuevo:** si la extracción falla, el reporte más reciente es el
  del día anterior; regenerar sus plantillas invitaría a subirlas dos veces.
- **Código de salida:** el de la extracción si falló; si no, el de las plantillas (4 = hay
  pedidos que no se pueden cargar). `ejecuciones.csv` registra el resultado de cada paso.
