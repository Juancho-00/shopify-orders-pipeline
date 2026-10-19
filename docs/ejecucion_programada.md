# Ejecución programada (Programador de tareas de Windows)

Cómo dejar el pipeline corriendo solo, todos los días, en **un único equipo** de la empresa.

## Qué se ejecuta y cuándo

| | Valor | Por qué |
|---|---|---|
| Frecuencia | Diaria, **6:30 a. m.** (configurable) | Siesa recibe al inicio del día los pedidos pagados del día anterior |
| Comando | `extract --incremental --strict` | Retoma desde la última corrida completa y no repite pedidos ya reportados (ver README, *Corridas incrementales*) |
| Reintento | 1 vez, 10 minutos después, solo si el error es temporal (código 1) | Una caída breve de red, de Shopify o un archivo bloqueado por Drive no debe perder el día |
| Si Drive no ha montado G: | Espera hasta 15 minutos | Google Drive tarda en montar la unidad después de iniciar sesión |
| Duración máxima | 1 hora | Si se queda colgado, Windows lo detiene |
| Si el equipo estaba apagado | Corre apenas haya sesión iniciada | No se salta días; además, `--incremental` recupera el periodo perdido |
| Historial | `data\logs\ejecuciones.csv` | Una línea por corrida: fecha, código, resultado, intentos y duración |

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

Todos los comandos en **PowerShell**, en el equipo que va a ejecutar el pipeline.

**1. Entorno de Python e instalación**

```powershell
conda create -n shopify-pipeline python=3.12 -y
conda activate shopify-pipeline
cd "G:\Unidades compartidas\TI\002 - Juan Pablo Quintero\Shopify\shopify-orders-pipeline"
pip install -e .
```

**2. Ubicar el `python.exe` del entorno** (lo necesita la tarea)

```powershell
(Get-Command python).Source
# Ejemplo: C:\Users\usuario\miniconda3\envs\shopify-pipeline\python.exe
```

**3. Verificar el `.env`** (credenciales de Shopify y `SIESA_CODIGO_ENVIO`).

**4. Probar el script a mano**

```powershell
.\scripts\ejecutar_pipeline.ps1 -Python "C:\Users\usuario\miniconda3\envs\shopify-pipeline\python.exe"
```

Debe terminar con `Resultado: OK (código 0 ...)` y dejar archivos en `data\processed\siesa\`.
La primera corrida incremental toma los últimos 7 días.

**5. Registrar la tarea programada**

```powershell
.\scripts\registrar_tarea.ps1 -Python "C:\Users\usuario\miniconda3\envs\shopify-pipeline\python.exe" -Hora "06:30"
```

**6. Probar la tarea**

```powershell
Start-ScheduledTask -TaskName "Shopify Pipeline - Extraccion diaria"
Get-ScheduledTaskInfo -TaskName "Shopify Pipeline - Extraccion diaria"   # LastTaskResult 0 = OK
Get-Content .\data\logs\ejecuciones.csv -Tail 5
```

## Revisión diaria (unos 10 minutos con la conciliación)

1. Abrir `data\logs\ejecuciones.csv` y ver la última línea:

   | resultado | Código | Qué hacer |
   |---|---|---|
   | `OK` | 0 | Nada. Revisar el reporte y las alertas |
   | `ERROR_TEMPORAL` | 1 | Falló dos veces seguidas. Revisar internet, el estado de Shopify, que no haya archivos de `data\` abiertos en Excel y que Drive esté sincronizado. La próxima corrida recupera el periodo |
   | `ERROR_CONFIGURACION` | 2 | Credenciales vencidas, permiso faltante o `.env` mal. No se arregla esperando: ver la bitácora |
   | `CONTEO_NO_CUADRA` | 3 | El watermark no avanzó; la próxima corrida repite el periodo. Si se repite varios días, investigar |
   | `ERROR_DATOS` | 4 | Pedidos que no se pudieron transformar o estado dañado. Ver `alertas_<run_id>.csv` (`ERROR_TRANSFORMACION`) y la bitácora |
   | `ERROR_INESPERADO` | 5 | Posible bug. La traza está en la bitácora; reportarlo |

2. Abrir `data\logs\alertas_<run_id>.csv` y resolver lo marcado: documentos, SKU, bodegas,
   `CAMBIO_POST_REPORTE`.
3. Tomar el reporte `data\processed\siesa\pedidos_siesa_<run_id>.xlsx`.
4. **Conciliación (fase 2), manual:** exportar de Siesa el Excel de pedidos (columnas
   `Nro documento` y `_num_docto_referencia`), guardarlo en `data\siesa\exportes\` y
   ejecutar:

   ```powershell
   conda activate shopify-pipeline
   cd "G:\Unidades compartidas\TI\002 - Juan Pablo Quintero\Shopify\shopify-orders-pipeline"
   shopify-pipeline conciliar
   ```

   Revisar `data\reconciliation\conciliacion_<fecha>.xlsx`: los `FALTA_EN_SIESA` salen
   primero. Exporte de Siesa **después** de cargar los pedidos del día: si no, los del
   reporte de hoy saldrán como `FALTA_EN_SIESA` aunque estén por cargar. A futuro se
   evaluará que un agente de IA haga la exportación desde Siesa.

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
Disable-ScheduledTask    -TaskName "Shopify Pipeline - Extraccion diaria"
Enable-ScheduledTask     -TaskName "Shopify Pipeline - Extraccion diaria"
Unregister-ScheduledTask -TaskName "Shopify Pipeline - Extraccion diaria"
```

**Cambiar de equipo:** primero `Unregister-ScheduledTask` en el equipo anterior y después
registrar en el nuevo. Nunca dos equipos con la tarea activa al mismo tiempo.

## Pendiente

- [ ] Registrar la tarea cuando Shopify entregue el Client ID y el Client Secret (pasos 3 a 6).
- [ ] Definir quién reemplaza en la revisión diaria (asistente o digitador) y capacitarlo.
- [ ] Evaluar un agente de IA para la exportación de Siesa de la conciliación.
