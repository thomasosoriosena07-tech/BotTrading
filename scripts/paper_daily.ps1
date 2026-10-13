# Paper trading automatico (DECISIONS.md D028).
# Descarga los dias cerrados, simula y versiona paper/. Sin dinero ni ordenes.
# Solo hace commit de paper/ y push normal (nunca --force). Si algo falla,
# no hace commit y deja el error en reports/automation/ (ignorado por Git).

$ErrorActionPreference = "Continue"  # se comprueba $LASTEXITCODE de cada paso
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }  # acentos en el log
$python = Join-Path $repo ".venv\Scripts\python.exe"
$logDir = Join-Path $repo "reports\automation"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("paper_" + (Get-Date -Format "yyyy-MM-dd") + ".log")

function Write-Log([string]$message) {
    "$(Get-Date -Format s) $message" | Out-File -Append -Encoding utf8 $log
}

function Invoke-Step([string]$name, [scriptblock]$command) {
    $output = & $command 2>&1 | ForEach-Object { "$_" }
    $output | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) { throw "$name termino con codigo $LASTEXITCODE" }
}

try {
    Write-Log "inicio"
    foreach ($symbol in "BTCUSDT", "ETHUSDT", "SOLUSDT") {
        Invoke-Step "descarga $symbol" {
            & $python -m bottrading.download --symbol $symbol --interval 1d --daily --start 2026-10-01
        }
    }
    Invoke-Step "paper" { & $python -m bottrading.paper }

    Invoke-Step "git add" { git add -- paper/ }
    git diff --cached --quiet -- paper/
    if ($LASTEXITCODE -eq 0) {
        Write-Log "sin cambios en paper/; nada que versionar"
        exit 0
    }
    $day = (Select-String -Path "paper\ledger.state" -Pattern '^last_day=(.+)$').Matches[0].Groups[1].Value
    # Con rutas, git commit incluye SOLO paper/ aunque haya otros cambios preparados.
    Invoke-Step "git commit" { git commit -m "paper: datos hasta $day (automatico, D028)" -- paper/ }
    Invoke-Step "git push" { git push origin main }
    Write-Log "OK: datos hasta $day"
    exit 0
}
catch {
    Write-Log "ERROR: $_"
    exit 1
}
