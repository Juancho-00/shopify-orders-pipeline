<#
.SYNOPSIS
    Ejecución diaria del pipeline Shopify → Siesa. Es el script que corre la tarea programada.

.DESCRIPTION
    1. Espera a que la carpeta del repo esté disponible. Si vive en Google Drive (G:), la
       unidad aparece unos minutos después de iniciar sesión.
    2. Ejecuta la corrida recomendada para la tarea programada:
         extract --incremental --strict
       --incremental retoma desde la última extracción completa (watermark) y evita repetir
       pedidos ya reportados (ledger). --strict hace que un descuadre o un pedido que no se
       pudo transformar devuelvan código de error en vez de pasar en silencio.
    3. Si el error es temporal (código 1: red, Shopify caído o archivo bloqueado por Excel o
       por Drive), espera y reintenta una vez. Los demás códigos no se reintentan: esperar
       no los arregla.
    4. Anota el resultado en data\logs\ejecuciones.csv (fecha, código, resultado, intentos,
       duración).
    5. Devuelve el mismo código de salida del pipeline, para que el Programador de tareas
       de Windows marque la ejecución como fallida si algo salió mal.

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
    # Los logs de Python salen por stderr. En Windows PowerShell 5.1, con
    # ErrorActionPreference = "Stop", eso se toma como error y corta el script; por eso
    # aquí se relaja a "Continue". "| Out-Host" muestra la salida sin mezclarla con el código.
    $ErrorActionPreference = "Continue"
    & $Python -m shopify_pipeline extract --incremental --strict 2>&1 | Out-Host
    return $LASTEXITCODE
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
$intento = 1
$codigo = Invoke-Pipeline

if ($codigo -eq 1) {
    Write-Warning "Error temporal. Reintentando en $EsperaReintentoMin minutos..."
    Start-Sleep -Seconds ($EsperaReintentoMin * 60)
    $intento = 2
    $codigo = Invoke-Pipeline
}

$significado = $Significados[[int]$codigo]
if (-not $significado) { $significado = "DESCONOCIDO" }
$duracion = [math]::Round(((Get-Date) - $inicio).TotalSeconds, 1)

if (-not (Test-Path -LiteralPath $historial)) {
    "fecha,codigo,resultado,intentos,duracion_seg" | Out-File -FilePath $historial -Encoding utf8
}
"{0},{1},{2},{3},{4}" -f $inicio.ToString("yyyy-MM-dd HH:mm:ss"), $codigo, $significado, $intento, `
    $duracion.ToString([System.Globalization.CultureInfo]::InvariantCulture) |
    Out-File -FilePath $historial -Append -Encoding utf8

Write-Output "Resultado: $significado (código $codigo, $intento intento(s), $duracion s)."
exit $codigo
