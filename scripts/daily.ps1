# Tarea diaria de BotTrading (D028 + D030 F5). Unica accion de la tarea
# programada "BotTrading paper trading".
# 1. paper_daily.ps1 (descarga, simula y publica paper/).
# 2. demo_daily.ps1 (ordenes en la cuenta DEMO), SOLO si paper termino con
#    codigo 0 (revision de Codex: un fallo de paper, aunque ya haya descargado
#    datos, no debe dejar que demo envie ordenes).
# Log de la cadena en reports/automation/daily_<fecha>.log (ignorado por Git).

function Invoke-Chain([string]$Dir) {
    $repo = Split-Path -Parent $Dir
    $logDir = Join-Path $repo "reports\automation"
    New-Item -ItemType Directory -Force $logDir | Out-Null
    $log = Join-Path $logDir ("daily_" + (Get-Date -Format "yyyy-MM-dd") + ".log")
    $shell = "powershell.exe"
    $common = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File")

    "$(Get-Date -Format s) paper: inicio" | Out-File -Append -Encoding utf8 $log
    & $shell @common (Join-Path $Dir "paper_daily.ps1")
    $paper = $LASTEXITCODE
    "$(Get-Date -Format s) paper: codigo $paper" | Out-File -Append -Encoding utf8 $log
    if ($paper -ne 0) {
        "$(Get-Date -Format s) demo: NO se ejecuta porque paper fallo" |
            Out-File -Append -Encoding utf8 $log
        return $paper
    }
    & $shell @common (Join-Path $Dir "demo_daily.ps1")
    $demo = $LASTEXITCODE
    "$(Get-Date -Format s) demo: codigo $demo" | Out-File -Append -Encoding utf8 $log
    return $demo
}

if ($MyInvocation.InvocationName -ne ".") {
    exit (Invoke-Chain $PSScriptRoot)
}
