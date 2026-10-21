<#
.SYNOPSIS
    Registra (o actualiza) la tarea programada de Windows que ejecuta el pipeline cada día.

.DESCRIPTION
    Crea en el Programador de tareas una tarea que corre scripts\ejecutar_pipeline.ps1
    todos los días a la hora indicada. Si la tarea ya existe, la reemplaza con la nueva
    configuración. Se ejecuta UNA vez, en el único equipo que va a correr el pipeline.

    Configuración de la tarea:
      * Corre con el usuario actual y mientras tenga la sesión iniciada: así Google Drive
        está montado y data\ (en Drive) es accesible.
      * Si el equipo estaba apagado o sin sesión a la hora programada, corre apenas se pueda.
      * No arranca una segunda copia si la anterior sigue corriendo.
      * Se detiene si tarda más de 1 hora.

.PARAMETER Python
    Ruta completa al python.exe del entorno del pipeline (igual que en ejecutar_pipeline.ps1).

.PARAMETER Hora
    Hora diaria de ejecución, formato 24 h. Por defecto 06:30.

.EXAMPLE
    .\scripts\registrar_tarea.ps1 -Python "C:\Users\usuario\miniconda3\envs\shopify-pipeline\python.exe" -Hora "06:30"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Python,

    [ValidatePattern("^\d{2}:\d{2}$")]
    [string]$Hora = "06:30",

    [string]$NombreTarea = "Shopify Pipeline - Corrida diaria",

    [string]$RepoDir = ""
)

# En Windows PowerShell 5.1, $PSScriptRoot puede llegar vacío en los valores por defecto
# de param() (pasa al ejecutar con "powershell -File"). Por eso se calcula aquí.
if (-not $RepoDir) {
    $carpetaScript = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    $RepoDir = Split-Path -Parent $carpetaScript
}

$ErrorActionPreference = "Stop"

$script = Join-Path $RepoDir "scripts\ejecutar_pipeline.ps1"
foreach ($ruta in @($Python, $script)) {
    if (-not (Test-Path -LiteralPath $ruta)) { throw "No existe: $ruta" }
}

$existentes = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like "Shopify Pipeline*" -and $_.TaskName -ne $NombreTarea }
if ($existentes) {
    Write-Warning ("Ya hay otra tarea del pipeline en este equipo: " + ($existentes.TaskName -join ", ") +
        ". Solo una tarea (y un solo equipo) debe escribir data\state.")
}

$argumentos = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Python `"$Python`""
$accion = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumentos -WorkingDirectory $RepoDir
$disparador = New-ScheduledTaskTrigger -Daily -At $Hora
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$usuario = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $NombreTarea -Action $accion -Trigger $disparador -Settings $ajustes `
    -Principal $usuario -Description "Extrae los pedidos de Shopify y deja listas las plantillas de Siesa para validar y subir. Repo: $RepoDir" `
    -Force | Out-Null

Write-Output "Tarea '$NombreTarea' registrada: todos los días a las $Hora (usuario actual, con sesión iniciada)."
Write-Output "Probarla ahora:   Start-ScheduledTask -TaskName '$NombreTarea'"
Write-Output "Ver su estado:    Get-ScheduledTaskInfo -TaskName '$NombreTarea'"
