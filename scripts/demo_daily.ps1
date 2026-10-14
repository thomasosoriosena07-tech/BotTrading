# Ordenes automaticas en la cuenta DEMO de Binance (DECISIONS.md D030, F5).
# Dinero ficticio. Aprobado por el usuario (2026-10-13). Se ejecuta como segunda
# accion de la tarea "BotTrading paper trading", despues de paper_daily.ps1, y usa
# los mismos datos ya descargados (si no estan, el bot se detiene sin enviar).
#
# - Activa el doble consentimiento SOLO dentro de este proceso: --send-orders y
#   BOTTRADING_DEMO_ORDERS=1. El host sigue fijo en demo-api.binance.com.
# - Para detenerlo: crear el archivo STOP en %USERPROFILE%\.bottrading\demo\
#   (kill switch); el bot no consulta ni envia nada mientras exista.
# - No publica nada en Git. Log en reports/automation/demo_<fecha>.log (ignorado).

function Hide-Secrets([string]$Line) {
    # Barrera propia del log (revision de Codex): la CLI ya oculta claves, pero
    # si una excepcion inesperada las mostrara, aqui se tapan igualmente.
    # Credenciales admitidas: 16 a 128 alfanumericos de cualquier composicion
    # (revisiones de Codex). Se tapa TODA secuencia alfanumerica de 16 o mas;
    # IDs bt-..., fechas y decimales tienen separadores y no se ven afectados.
    $Line = $Line -replace '(?<![A-Za-z0-9])[A-Za-z0-9]{16,}(?![A-Za-z0-9])', '[oculto]'
    $Line = $Line -replace '(?i)signature=[^&\s]*', 'signature=[oculto]'
    return ($Line -replace '(?i)X-MBX-APIKEY\S*\s*\S*', 'X-MBX-APIKEY [oculto]')
}

function Invoke-DemoDaily {
    $ErrorActionPreference = "Continue"
    $repo = Split-Path -Parent $PSScriptRoot
    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
    $python = Join-Path $repo ".venv\Scripts\python.exe"
    $logDir = Join-Path $repo "reports\automation"
    New-Item -ItemType Directory -Force $logDir | Out-Null
    $log = Join-Path $logDir ("demo_" + (Get-Date -Format "yyyy-MM-dd") + ".log")
    "$(Get-Date -Format s) inicio" | Out-File -Append -Encoding utf8 $log
    $env:BOTTRADING_DEMO_ORDERS = "1"
    try {
        $output = & $python -m bottrading.demo_client run --send-orders 2>&1 |
            ForEach-Object { Hide-Secrets "$_" }
        $code = $LASTEXITCODE
        $output | Out-File -Append -Encoding utf8 $log
        "$(Get-Date -Format s) fin, codigo $code" | Out-File -Append -Encoding utf8 $log
        return $code
    }
    catch {
        "$(Get-Date -Format s) ERROR: $_" | Out-File -Append -Encoding utf8 $log
        return 1
    }
    finally {
        Remove-Item Env:BOTTRADING_DEMO_ORDERS -ErrorAction SilentlyContinue
    }
}

# Al cargarlo con ". .\demo_daily.ps1" (pruebas) solo se define la funcion.
if ($MyInvocation.InvocationName -ne ".") {
    exit (Invoke-DemoDaily)
}
