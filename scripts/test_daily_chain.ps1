# Pruebas de scripts/daily.ps1 y del filtro de demo_daily.ps1 (D030 F5).
# Usa scripts falsos en una carpeta temporal: no toca la red, Git ni Binance.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test_daily_chain.ps1

$ErrorActionPreference = "Continue"
$root = Join-Path $env:TEMP ("bottrading_chaintest_" + [guid]::NewGuid())
$scripts = Join-Path $root "scripts"
New-Item -ItemType Directory $scripts | Out-Null
Copy-Item (Join-Path $PSScriptRoot "daily.ps1") $scripts
$marker = Join-Path $root "demo_ejecutado.txt"
$results = @()
function Check($name, $ok) { $script:results += "{0}: {1}" -f $(if ($ok) {"OK  "} else {"FALLO"}), $name }

function Set-Fakes([int]$PaperCode) {
    "exit $PaperCode" | Out-File -Encoding ascii (Join-Path $scripts "paper_daily.ps1")
    "'x' | Out-File -Encoding ascii '$marker'; exit 0" |
        Out-File -Encoding ascii (Join-Path $scripts "demo_daily.ps1")
    Remove-Item $marker -ErrorAction SilentlyContinue
}

Set-Fakes 1
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scripts "daily.ps1")
Check "A paper falla -> codigo de la cadena = 1" ($LASTEXITCODE -eq 1)
Check "A paper falla -> demo NO se ejecuta" (-not (Test-Path $marker))

Set-Fakes 0
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scripts "daily.ps1")
Check "B paper OK -> codigo 0" ($LASTEXITCODE -eq 0)
Check "B paper OK -> demo se ejecuta" (Test-Path $marker)

$log = Get-ChildItem (Join-Path $root "reports\automation") -Filter "daily_*.log" | Select-Object -First 1
Check "C el log registra que demo no se ejecuto" ((Get-Content $log.FullName -Raw) -like "*demo: NO se ejecuta*")

# D: filtro de secretos del log de demo.
. (Join-Path $PSScriptRoot "demo_daily.ps1")
$key = "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A"
$hidden = Hide-Secrets "error clave=$key url=https://x/api?a=1&signature=abc123def&b=2 X-MBX-APIKEY: $key"
Check "D oculta claves de 64 caracteres" ($hidden -notlike "*$key*")
Check "D oculta la firma" ($hidden -notlike "*abc123def*")
Check "D deja el texto normal" ((Hide-Secrets "Sin ordenes: la cuenta ya coincide") -eq "Sin ordenes: la cuenta ya coincide")

Set-Location $env:TEMP
Remove-Item -Recurse -Force $root
$results
if ($results -match "FALLO") { exit 1 } else { exit 0 }
