<#
.SYNOPSIS
    Ejecución diaria del pipeline Shopify → Siesa. Es el script que corre la tarea programada.
    Deja listas las plantillas de Siesa: la persona solo las valida y las sube.

.DESCRIPTION
    1. Espera a que la carpeta del repo esté disponible. Si vive en Google Drive (G:), la
       unidad aparece unos minutos después de iniciar sesión.
    2. EXTRACCIÓN (fase 1):  extract --incremental --strict
       --incremental retoma desde la última extracción completa (watermark) y evita repetir
       pedidos ya reportados (ledger). --strict hace que un descuadre o un pedido que no se
       pudo transformar devuelvan código de error en vez de pasar en silencio.
    3. PLANTILLAS (fase 3):  plantillas --input <reporte de esta corrida> --strict
       Genera data\siesa\cargas\terceros_<run_id>.xlsx y pedidos_<run_id>.xlsx. Solo se
       ejecuta si la extracción dejó un reporte NUEVO en esta corrida: si Shopify falló, no
       se regeneran las plantillas del día anterior (ya subidas).
    4. Si un paso falla por un error temporal (código 1: red, Shopify caído o archivo
       bloqueado por Excel o por Drive), espera y lo reintenta una vez. Los demás códigos
       no se reintentan: esperar no los arregla.
    5. Anota el resultado de los dos pasos en data\logs\ejecuciones.csv.
    6. Devuelve un código de salida para el Programador de tareas: el de la extracción si
       falló; si no, el de las plantillas (4 = hay pedidos que no se pueden cargar y
       quedaron en data\logs\plantillas_<run_id>.csv).

.PARAMETER Python
    Ruta completa al python.exe del entorno donde se instaló el pipeline.
    Ejemplo (conda): C:\Users\usuario\miniconda3\envs\shopify-pipeline\python.exe
    Es obligatorio porque una tarea programada no "activa" entornos de conda.

.PARAMETER RepoDir
    Carpeta del repositorio. Por defecto, la carpeta padre de este script.

.PARAMETER EsperaReintentoMin
    Minutos de espera antes de reintentar ante un error temporal. Por defecto 10.

.PARAMETER EsperaCarpetaMin
    Minutos máximos que espera a que la carpeta del repo esté disponible (Google Drive
    montando la unidad G:). Por defecto 15.

.EXAMPLE
    .\scripts\ejecutar_pipeline.ps1 -Python "C:\Users\usuario\miniconda3\envs\shopify-pipeline\python.exe"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Python,

    [string]$RepoDir = (Split-Path -Parent $PSScriptRoot),

    [ValidateRange(0, 120)]
    [int]$EsperaReintentoMin = 10,

    [ValidateRange(0, 120)]
    [int]$EsperaCarpetaMin = 15
)

$ErrorActionPreference = "Stop"

# Significado de cada código de salida del pipeline (ver README, "Códigos de salida").
$Significados = @{
    0 = "OK"
    1 = "ERROR_TEMPORAL"
    2 = "ERROR_CONFIGURACION"
    3 = "CONTEO_NO_CUADRA"
    4 = "ERROR_DATOS"
    5 = "ERROR_INESPERADO"
}

function Invoke-Pipeline {
    param([string[]]$Argumentos)
    # Los logs de Python salen por stderr. En Windows PowerShell 5.1, con
    # ErrorActionPreference = "Stop", eso se toma como error y corta el script; por eso
    # aquí se relaja a "Continue". "| Out-Host" muestra la salida sin mezclarla con el código.
    $ErrorActionPreference = "Continue"
    & $Python -m shopify_pipeline @Argumentos 2>&1 | Out-Host
    return $LASTEXITCODE
}

function Invoke-Paso {
    # Ejecuta un paso del pipeline y lo reintenta una vez si el error es temporal (código 1).
    param([string]$Nombre, [string[]]$Argumentos)
    $codigo = Invoke-Pipeline $Argumentos
    $intentos = 1
    if ($codigo -eq 1) {
        Write-Warning "$($Nombre): error temporal. Reintentando en $EsperaReintentoMin minutos..."
        Start-Sleep -Seconds ($EsperaReintentoMin * 60)
        $codigo = Invoke-Pipeline $Argumentos
        $intentos = 2
    }
    return @{ Codigo = [int]$codigo; Intentos = $intentos }
}

function Get-Significado {
    param([int]$Codigo)
    $s = $Significados[$Codigo]
    if ($s) { return $s }
    return "DESCONOCIDO"
}

if (-not (Test-Path -LiteralPath $Python)) {
    [Console]::Error.WriteLine("No existe el ejecutable de Python: $Python")
    exit 2
}

# Google Drive monta G: unos minutos después de iniciar sesión: se espera un poco.
$limite = (Get-Date).AddMinutes($EsperaCarpetaMin)
while (-not (Test-Path -LiteralPath (Join-Path $RepoDir "pyproject.toml"))) {
    if ((Get-Date) -ge $limite) {
        [Console]::Error.WriteLine("La carpeta del repo no está disponible: $RepoDir (¿Google Drive sin iniciar?)")
        exit 1
    }
    Start-Sleep -Seconds 30
}

Set-Location -LiteralPath $RepoDir
$logDir = Join-Path $RepoDir "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$historial = Join-Path $logDir "ejecuciones.csv"

$inicio = Get-Date

# --- Paso 1: extracción de Shopify y reporte (fase 1) ---
$extraccion = Invoke-Paso "Extracción" @("extract", "--incremental", "--strict")

# --- Paso 2: plantillas de Siesa (fase 3), solo con un reporte nuevo de esta corrida ---
# Códigos 0, 3 y 4 de la extracción dejan reporte (3 y 4 avisan de algo a revisar).
$plantillas = @{ Codigo = $null; Intentos = 0 }
$resultadoPlantillas = "NO_GENERADAS"
$reporte = $null
if (@(0, 3, 4) -contains $extraccion.Codigo) {
    $reporte = Get-ChildItem -LiteralPath (Join-Path $RepoDir "data\processed\siesa") -Filter "pedidos_siesa_*.csv" -ErrorAction SilentlyContinue |
        Where-Object { $_.BaseName -notlike "*_revision" -and $_.LastWriteTime -ge $inicio } |
        Sort-Object Name | Select-Object -Last 1
}
if ($reporte) {
    $plantillas = Invoke-Paso "Plantillas" @("plantillas", "--input", $reporte.FullName, "--strict")
    $resultadoPlantillas = Get-Significado $plantillas.Codigo
} elseif ($extraccion.Codigo -in @(0, 3, 4)) {
    Write-Warning "La extracción no dejó un reporte nuevo: no se generan plantillas."
}

# --- Resultado ---
# Si la extracción falló, ese es el código. Si no, el de las plantillas.
if ($extraccion.Codigo -ne 0 -or $null -eq $plantillas.Codigo) { $codigo = $extraccion.Codigo }
else { $codigo = $plantillas.Codigo }
$significado = Get-Significado $codigo
$duracion = [math]::Round(((Get-Date) - $inicio).TotalSeconds, 1)

if (-not (Test-Path -LiteralPath $historial)) {
    "fecha,codigo,resultado,extraccion,intentos_extraccion,plantillas,intentos_plantillas,duracion_seg" |
        Out-File -FilePath $historial -Encoding utf8
}
"{0},{1},{2},{3},{4},{5},{6},{7}" -f $inicio.ToString("yyyy-MM-dd HH:mm:ss"), $codigo, $significado, `
    (Get-Significado $extraccion.Codigo), $extraccion.Intentos, $resultadoPlantillas, $plantillas.Intentos, `
    $duracion.ToString([System.Globalization.CultureInfo]::InvariantCulture) |
    Out-File -FilePath $historial -Append -Encoding utf8

Write-Output "Extracción: $(Get-Significado $extraccion.Codigo) ($($extraccion.Intentos) intento(s)). Plantillas: $resultadoPlantillas."
if ($reporte -and $plantillas.Codigo -in @(0, 4)) {
    Write-Output "Plantillas para validar y subir (primero clientes, luego pedidos): data\siesa\cargas\"
}
Write-Output "Resultado: $significado (código $codigo, $duracion s)."
exit $codigo
