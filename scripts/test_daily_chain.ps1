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

# E (revision de Codex): todas las longitudes de credencial admitidas (16-128).
$chars = "aB3dE5gH7jK9mN1pQ2rS4tU6vW8xY0zC"
foreach ($n in 16, 17, 31, 32, 63, 64, 100, 128) {
    $token = ($chars * 5).Substring(0, $n)
    $masked = Hide-Secrets "fallo inesperado con $token al firmar"
    Check "E oculta una credencial de $n caracteres" ($masked -notlike "*$token*")
}
# Revision de Codex: tambien solo letras y solo digitos (validos para parse_credential).
foreach ($n in 16, 31, 64, 128) {
    foreach ($token in @(("a" * $n), ("1" * $n), ("Z" * $n))) {
        $masked = Hide-Secrets "fallo con $token"
        Check "E oculta $n caracteres de un solo tipo ($($token[0]))" ($masked -notlike "*$token*")
    }
}
Check "E una secuencia de 15 no se toca" ((Hide-Secrets ("a" * 15)) -eq ("a" * 15))
Check "E oculta SIGNATURE en mayusculas" ((Hide-Secrets "x?A=1&SIGNATURE=deadbeef") -notlike "*deadbeef*")
# Lineas reales del log que no deben cambiar.
foreach ($line in @(
        "  bt-BTCUSDT-20260817-B: FINAL FILLED ejecutado 0.01193",
        "  BTCUSDT: efectivo 0.27 USDT, cantidad 0.01191807, coste 999.73",
        "2026-10-13T23:07:42 inicio",
        "Hora: desfase con el servidor 183 ms",
        "Orden: bt-SOLUSDT-20261012-S SELL 84.532 SOLUSDT")) {
    Check "E no altera: $($line.Trim().Substring(0, 20))" ((Hide-Secrets $line) -eq $line)
}

Set-Location $env:TEMP
Remove-Item -Recurse -Force $root
$results
if ($results -match "FALLO") { exit 1 } else { exit 0 }
