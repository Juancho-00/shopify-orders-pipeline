# Ejecución programada (Programador de tareas de Windows)

Cómo dejar el pipeline corriendo solo, todos los días, en **un único equipo** de la empresa.

## Qué se ejecuta y cuándo

| | Valor | Por qué |
|---|---|---|
| Frecuencia | Diaria, 6:00 a. m. (configurable) | Siesa recibe al inicio del día los pedidos pagados del día anterior |
| Comando | `extract --incremental --strict` | Retoma desde la última corrida completa y no repite pedidos ya reportados (ver README, *Corridas incrementales*) |
| Reintento | 1 vez, 10 minutos después, solo si el error es temporal (código 1) | Una caída breve de red, de Shopify o un archivo bloqueado por Drive no debe perder el día |
| Si Drive no ha montado G: | Espera hasta 15 minutos | Google Drive tarda en montar la unidad después de iniciar sesión |
| Duración máxima | 1 hora | Si se queda colgado, Windows lo detiene |
| Si el equipo estaba apagado | Corre apenas haya sesión iniciada | No se salta días; además, `--incremental` recupera el periodo perdido |
| Historial | `data\logs\ejecuciones.csv` | Una línea por corrida: fecha, código, resultado, intentos y duración |

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
.\scripts\registrar_tarea.ps1 -Python "C:\Users\usuario\miniconda3\envs\shopify-pipeline\python.exe" -Hora "06:00"
```

**6. Probar la tarea**

```powershell
Start-ScheduledTask -TaskName "Shopify Pipeline - Extraccion diaria"
Get-ScheduledTaskInfo -TaskName "Shopify Pipeline - Extraccion diaria"   # LastTaskResult 0 = OK
Get-Content .\data\logs\ejecuciones.csv -Tail 5
```

## Revisión diaria (2 minutos)

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

## Pendiente por definir

- [ ] **Equipo** que ejecutará la tarea (encendido a diario, con sesión iniciada, idealmente no el portátil de una persona).
- [ ] **Usuario de Windows / cuenta de Google** con la que corre.
- [ ] **Hora** de ejecución.
- [ ] **Quién revisa** `ejecuciones.csv` y el log de alertas cada día, y a quién escala.
