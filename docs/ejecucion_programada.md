# Ejecución programada (Programador de tareas de Windows)

Cómo dejar el pipeline corriendo solo, todos los días, en **un único equipo** de la empresa.
Cada mañana la tarea extrae los pedidos de Shopify y deja listas las plantillas de Siesa: la
persona encargada solo las **valida y las sube**.

## Qué se ejecuta y cuándo

| | Valor | Por qué |
|---|---|---|
| Frecuencia | Diaria, **6:30 a. m.** (configurable) | Siesa recibe al inicio del día los pedidos pagados del día anterior |
| Paso 1: extracción | `extract --incremental --strict` | Retoma desde la última corrida completa y no repite pedidos ya reportados (ver README, *Corridas incrementales*) |
| Paso 2: plantillas | `plantillas --input <reporte de hoy> --strict` | Deja en `data\siesa\cargas\` la plantilla de clientes y la de pedidos. Solo corre si el paso 1 dejó un reporte **nuevo**: si Shopify falló, no se regeneran las del día anterior |
| Reintento | 1 vez por paso, 10 minutos después, solo si el error es temporal (código 1) | Una caída breve de red, de Shopify o un archivo bloqueado por Drive no debe perder el día |
| Si Drive no ha montado G: | Espera hasta 15 minutos | Google Drive tarda en montar la unidad después de iniciar sesión |
| Duración máxima | 1 hora | Si se queda colgado, Windows lo detiene |
| Si el equipo estaba apagado | Corre apenas haya sesión iniciada | No se salta días; además, `--incremental` recupera el periodo perdido |
| Historial | `data\logs\ejecuciones.csv` | Una línea por corrida: resultado general, resultado e intentos de cada paso y duración |
| Nombre de la tarea | `Shopify Pipeline - Corrida diaria` | — |

## Configuración definida (2026-10-19)

| | Definición |
|---|---|
| **Equipo** | El equipo de Juan Pablo Quintero (TI). Se entrega con la tarea instalada para que el proceso siga corriendo |
| **Usuario** | El usuario de Windows de Juan Pablo Quintero, con Google Drive para escritorio y acceso a la unidad compartida de TI |
| **Hora** | 6:30 a. m., todos los días |
| **Revisión diaria** | Por ahora, Juan Pablo Quintero. Después, el asistente o un digitador |
| **Escalamiento** | Según el error: a la persona responsable de TI o al encargado del e-commerce (ver *Revisión diaria*) |

> ⚠️ **Al entregar el equipo:** la tarea corre con la sesión de ese usuario de Windows y con
> su cuenta de Google Drive. Si cualquiera de las dos se desactiva o cambia de contraseña,
> la tarea deja de correr sin avisar. Antes de la entrega, confirmar con TI que ambas
> cuentas siguen activas y que alguien conoce la contraseña para iniciar sesión. Si se
> cambia de usuario, volver a registrar la tarea con el nuevo (ver *Cambiar de equipo*).

## Requisitos del equipo

1. **Un solo equipo** ejecuta la tarea. `data\state\` (watermark y pedidos reportados) está en
   Google Drive: si dos equipos lo escriben, Drive crea copias en conflicto y el registro
   deja de ser confiable.
2. **Encendido y con la sesión del usuario iniciada** a la hora programada, o en algún momento
   del día. La tarea corre con ese usuario porque la unidad G: de Drive solo existe con su
   sesión abierta.
3. **Google Drive para escritorio** iniciado con la cuenta que tiene acceso a la unidad compartida.
4. **Python y el pipeline instalados** en un entorno **fuera de Drive** (conda o venv).
5. **El archivo `.env`** con las credenciales en la carpeta del repo.

## Instalación paso a paso (una sola vez)

Todos los comandos van en **PowerShell**, en el equipo que va a ejecutar la tarea, con la
sesión del usuario que la va a correr. Los pasos 1 a 6 se pueden hacer **hoy**, sin las
credenciales de Shopify; el paso 7 se hace cuando lleguen.

**1. Abrir PowerShell e ir a la carpeta del repo**

Menú Inicio → escribir *Anaconda PowerShell Prompt* (o *PowerShell* si conda ya está en el
PATH) → Enter.

```powershell
cd "G:\Unidades compartidas\TI\002 - Juan Pablo Quintero\Shopify\shopify-orders-pipeline"
```

**2. Crear el entorno de Python e instalar el pipeline** (fuera de Drive: conda lo crea en
la carpeta del usuario)

```powershell
conda create -n shopify-pipeline python=3.12 -y     # si ya existe, saltar esta línea
conda activate shopify-pipeline
pip install -e ".[dev]"
pre-commit install                                   # revisión de secretos antes de cada commit
```

**3. Comprobar que todo quedó bien instalado**

```powershell
pytest -q                          # deben pasar todas las pruebas
shopify-pipeline --version         # shopify-pipeline 0.3.0
```

**4. Copiar la ruta del `python.exe` del entorno** (la tarea la necesita, porque una tarea
programada no "activa" conda)

```powershell
(Get-Command python).Source
# Ejemplo: C:\Users\jquintero\miniconda3\envs\shopify-pipeline\python.exe
```

Guárdela; en los pasos siguientes va donde dice `<RUTA_PYTHON>`.

**5. Probar el script a mano**

```powershell
.\scripts\ejecutar_pipeline.ps1 -Python "<RUTA_PYTHON>"
```

**Hoy, sin credenciales,** debe terminar así, y es lo correcto:

```
Extracción: ERROR_CONFIGURACION (1 intento(s)). Plantillas: NO_GENERADAS.
Resultado: ERROR_CONFIGURACION (código 2, ...)
```

Eso confirma que Python, el pipeline, la carpeta de Drive y el historial
(`data\logs\ejecuciones.csv`) funcionan; solo faltan las credenciales.

> Si PowerShell dice que *la ejecución de scripts está deshabilitada*, ejecute una vez
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y repita. La tarea programada no lo
> necesita: ya corre con `-ExecutionPolicy Bypass`.

**6. Registrar la tarea programada**

```powershell
.\scripts\registrar_tarea.ps1 -Python "<RUTA_PYTHON>" -Hora "06:30"
```

Debe responder `Tarea 'Shopify Pipeline - Corrida diaria' registrada: todos los días a las
06:30`. Para verla: menú Inicio → *Programador de tareas* → *Biblioteca del Programador de
tareas*.

Mientras no haya credenciales, cada mañana la tarea terminará en `ERROR_CONFIGURACION`
(código 2) sin hacer nada más. Si prefiere que no corra hasta tenerlas, desactívela:
`Disable-ScheduledTask -TaskName "Shopify Pipeline - Corrida diaria"`.

**7. Cuando Shopify entregue las credenciales**

1. Abrir el `.env` y completar `SHOPIFY_SHOP_DOMAIN` (`xxxx.myshopify.com`),
   `SHOPIFY_CLIENT_ID` y `SHOPIFY_CLIENT_SECRET`. Dejar `SHOPIFY_ACCESS_TOKEN` comentado.
2. Probar la conexión con una extracción corta que no toca el estado diario:

   ```powershell
   shopify-pipeline extract --days 1 --sin-ledger
   ```

3. Si la tarea estaba desactivada: `Enable-ScheduledTask -TaskName "Shopify Pipeline - Corrida diaria"`.
4. Correrla ya, sin esperar a las 6:30, y revisar el resultado:

   ```powershell
   Start-ScheduledTask -TaskName "Shopify Pipeline - Corrida diaria"
   Get-ScheduledTaskInfo -TaskName "Shopify Pipeline - Corrida diaria"   # LastTaskResult 0 = OK
   Get-Content .\data\logs\ejecuciones.csv -Tail 3
   ```

   La primera corrida incremental toma los últimos 7 días y deja las plantillas en
   `data\siesa\cargas\`.

## Revisión diaria: validar y subir (unos 10 minutos)

La tarea ya dejó todo listo a las 6:30. La persona encargada:

**1. Mira cómo terminó la corrida** en la última línea de `data\logs\ejecuciones.csv`:

| `resultado` | Código | Qué significa | Qué hacer |
|---|---|---|---|
| `OK` | 0 | Extracción y plantillas sin novedad | Seguir al paso 2 |
| `ERROR_DATOS` | 4 | Hay plantillas, pero algunos pedidos quedaron por fuera (columna `plantillas` = `ERROR_DATOS`), o hubo pedidos que no se pudieron transformar | Seguir al paso 2; los pedidos excluidos se corrigen aparte |
| `CONTEO_NO_CUADRA` | 3 | Hay plantillas, pero Shopify cambió algún pedido durante la extracción. La próxima corrida repite el periodo sin duplicar | Seguir al paso 2. Si se repite varios días, avisar a TI |
| `ERROR_TEMPORAL` | 1 | Falló dos veces seguidas (internet, Shopify caído, un archivo de `data\` abierto en Excel, Drive sin sincronizar). **No hay plantillas** | Revisar esas causas y ejecutar a mano `.\scripts\ejecutar_pipeline.ps1 -Python "<RUTA_PYTHON>"`. Si no, mañana se recupera el periodo |
| `ERROR_CONFIGURACION` | 2 | Credenciales vencidas, permiso faltante o `.env` mal. **No hay plantillas** | Avisar a TI: no se arregla esperando |
| `ERROR_INESPERADO` | 5 | Posible bug. **No hay plantillas** | Avisar a TI con la bitácora del día |

**2. Revisa qué pedidos no van** en `data\logs\plantillas_<run_id>.csv` (el `<run_id>` es
el mismo de las plantillas del día):

- `TERCERO_INCOMPLETO`, `PEDIDO_INCOMPLETO`: falta un dato (la columna `detalle` dice cuál).
  Se corrige en Shopify y el pedido se carga a mano, o con el encargado del e-commerce.
- `BODEGA_NO_SE_CARGA`: pedido de vending. No se hace nada.
- Alertas (`DIRECCION_TRUNCADA`, `NOTAS_RECORTADAS`, `RAZON_SOCIAL_DESDE_NOMBRE`): el pedido sí
  va en la plantilla, pero conviene mirar ese dato antes de subir.

Las alertas del reporte de la fase 1 están en `data\logs\alertas_<run_id>.csv`.

**3. Valida las plantillas** en `data\siesa\cargas\`, abriéndolas en Excel **sin guardar
cambios de formato**:

- `terceros_<run_id>.xlsx` (clientes): nombres, documentos, ciudades y correos con sentido.
- `pedidos_<run_id>.xlsx` (pedidos): cantidades, precios y bodegas; que no falte ningún
  pedido del día que debía ir.

Si una plantilla sale vacía, ese día no hubo pedidos pagados nuevos.

**4. Sube a Siesa, en este orden:** primero `terceros_<run_id>.xlsx` y después
`pedidos_<run_id>.xlsx` (R-30). Siesa rechaza un pedido repetido, así que subir dos veces
el mismo archivo no duplica pedidos (R-35).

**5. Conciliación, después de subir:** exportar de Siesa el Excel de pedidos (columnas
`Nro documento` y `_num_docto_referencia`), guardarlo en `data\siesa\exportes\` y ejecutar:

```powershell
conda activate shopify-pipeline
cd "G:\Unidades compartidas\TI\002 - Juan Pablo Quintero\Shopify\shopify-orders-pipeline"
shopify-pipeline conciliar
```

Revisar `data\reconciliation\conciliacion_<fecha>.xlsx`: los `FALTA_EN_SIESA` salen primero.
Los de vending salen como `NO_SE_CARGA` y no se buscan. A futuro se evaluará que un agente de
IA haga la exportación desde Siesa.

**A quién escalar:**

| Situación | Escalar a |
|---|---|
| `ERROR_CONFIGURACION`, `ERROR_INESPERADO`, `ERROR_TEMPORAL` repetido, tarea que no corrió | TI (responsable del pipeline) |
| Alertas de datos del cliente o del pedido (`SIN_DOCUMENTO`, `CIUDAD_SIN_CODIGO`, `SIN_SKU`...) | Encargado del e-commerce |
| `BODEGA_SIN_EQUIVALENCIA` (bodega nueva en Shopify) | TI: agregar la fila en `catalogos/bodegas_siesa.csv` |
| `CAMBIO_POST_REPORTE` o `FALTA_EN_SIESA` | Encargado del e-commerce (y logística si el pedido ya se cargó) |

La bitácora completa del día está en `data\logs\shopify_pipeline_AAAAMMDD.log`.

## Cambiar o quitar la tarea

```powershell
# Cambiar la hora: volver a registrar (reemplaza la anterior)
.\scripts\registrar_tarea.ps1 -Python "<ruta python.exe>" -Hora "07:30"

# Pausar / reanudar / eliminar
Disable-ScheduledTask    -TaskName "Shopify Pipeline - Corrida diaria"
Enable-ScheduledTask     -TaskName "Shopify Pipeline - Corrida diaria"
Unregister-ScheduledTask -TaskName "Shopify Pipeline - Corrida diaria"
```

**Cambiar de equipo:** primero `Unregister-ScheduledTask` en el equipo anterior y después
registrar en el nuevo. Nunca dos equipos con la tarea activa al mismo tiempo.

## Pendiente

- [ ] Pasos 1 a 6 de la instalación (se pueden hacer ya, sin credenciales).
- [ ] Paso 7 cuando Shopify entregue el Client ID y el Client Secret.
- [ ] Definir quién reemplaza en la revisión diaria (asistente o digitador) y capacitarlo.
- [ ] Evaluar un agente de IA para la exportación de Siesa de la conciliación.
