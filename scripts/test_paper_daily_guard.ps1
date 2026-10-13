# Pruebas de la guarda de scripts/paper_daily.ps1 (D028), en un repositorio
# git temporal con remoto local. No toca este repositorio ni la red.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test_paper_daily_guard.ps1

$ErrorActionPreference = "Continue"
$root = Join-Path $env:TEMP ("bottrading_guardtest_" + [guid]::NewGuid())
New-Item -ItemType Directory $root | Out-Null
Set-Location $root
git init -q --bare remote.git
git clone -q remote.git work 2>$null
Set-Location work
git config user.email "t@t"; git config user.name "t"
git checkout -q -b main
New-Item -ItemType Directory paper | Out-Null
"a" | Out-File paper/ledger.csv; "x" | Out-File other.txt
git add -A; git commit -q -m "inicial"; git push -q origin main 2>$null

. (Join-Path $PSScriptRoot "paper_daily.ps1")
$results = @()
function Check($name, $ok) { $script:results += "{0}: {1}" -f $(if ($ok) {"OK  "} else {"FALLO"}), $name }

Check "A sin pendientes -> 0 ajenos" (@(Get-UnpushedForeignCommits).Count -eq 0)

"b" | Out-File paper/ledger.csv; git add paper; git commit -q -m "paper: datos hasta 2026-10-13 (automatico, D028)"
Check "B commit automatico de paper/ -> 0 ajenos" (@(Get-UnpushedForeignCommits).Count -eq 0)
$threw = $false; try { Assert-SafeToCommit } catch { $threw = $true }
Check "B Assert no lanza" (-not $threw)

"y" | Out-File other.txt; git add other.txt; git commit -q -m "cambio manual"
Check "C commit ajeno -> 1 ajeno" (@(Get-UnpushedForeignCommits).Count -eq 1)
$threw = $false; try { Assert-SafeToCommit } catch { $threw = $_.ToString() -like "*no son automaticos*" }
Check "C Assert lanza por commit ajeno" $threw
git reset -q --hard HEAD~1

"z" | Out-File other.txt; "c" | Out-File paper/ledger.csv; git add -A
git commit -q -m "paper: datos hasta 2026-10-14 (automatico, D028)"
Check "D mensaje automatico pero toca otro archivo -> ajeno" (@(Get-UnpushedForeignCommits).Count -eq 1)
git reset -q --hard HEAD~1

git checkout -q -b otra
$threw = $false; try { Assert-SafeToCommit } catch { $threw = $_.ToString() -like "*no main*" }
Check "E rama distinta de main -> lanza" $threw

# G (revision de Codex): merge con mensaje automatico que mete un archivo ajeno.
"ajeno" | Out-File ajeno.txt; git add ajeno.txt; git commit -q -m "rama con archivo ajeno"
git checkout -q main
"e" | Out-File paper/ledger.csv; git add paper; git commit -q -m "paper: datos hasta 2026-10-15 (automatico, D028)"
git merge -q --no-ff otra -m "paper: datos hasta 2026-10-16 (automatico, D028)" 2>$null
$merge = git rev-parse HEAD
Check "G el merge cuenta como ajeno" (@(Get-UnpushedForeignCommits) -contains $merge)
Check "G la diferencia acumulada detecta ajeno.txt" (@(Get-UnpushedNonPaperFiles) -contains "ajeno.txt")
$threw = $false; try { Assert-SafeToCommit } catch { $threw = $true }
Check "G Assert lanza" $threw
git reset -q --hard origin/main

# H: diferencia acumulada solo con paper/ -> vacia.
"f" | Out-File paper/ledger.csv; git add paper; git commit -q -m "paper: datos hasta 2026-10-17 (automatico, D028)"
Check "H solo paper/ -> sin archivos ajenos" (@(Get-UnpushedNonPaperFiles).Count -eq 0)
git reset -q --hard origin/main

# I (revision de Codex): carrera. Se fija y valida el SHA; otro proceso
# anade un commit ajeno; solo se publica el SHA fijado.
$script:log = Join-Path $root "guard.log"
"g" | Out-File paper/ledger.csv; git add paper; git commit -q -m "paper: datos hasta 2026-10-18 (automatico, D028)"
$sha = Get-ValidatedTip
"carrera" | Out-File other.txt; git add other.txt; git commit -q -m "commit ajeno concurrente"
Push-Tip $sha
$remote = git ls-remote origin refs/heads/main
Check "I el remoto queda en el SHA validado" ($remote.StartsWith($sha))
Check "I el commit ajeno no se publica" (-not ($remote.StartsWith((git rev-parse HEAD))))
git fetch -q origin
git reset -q --hard origin/main

# J: commit ajeno DEBAJO del automatico (entre comprobacion y commit) -> no valida.
"carrera2" | Out-File other.txt; git add other.txt; git commit -q -m "commit ajeno previo"
"h" | Out-File paper/ledger.csv; git add paper; git commit -q -m "paper: datos hasta 2026-10-19 (automatico, D028)"
$threw = $false; try { Get-ValidatedTip | Out-Null } catch { $threw = $true }
Check "J Get-ValidatedTip lanza si hay un ajeno debajo" $threw
git reset -q --hard origin/main

Check "F nada preparado -> false" (-not (Test-PaperStaged))
"d" | Out-File paper/ledger.csv; git add paper
Check "F cambio preparado en paper/ -> true" (Test-PaperStaged)

Set-Location $env:TEMP
Remove-Item -Recurse -Force $root
$results
if ($results -match "FALLO") { exit 1 } else { exit 0 }
