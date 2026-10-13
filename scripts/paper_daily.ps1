# Paper trading automatico (DECISIONS.md D028).
# Descarga los dias cerrados, simula y versiona paper/. Sin dinero ni ordenes.
# Solo hace commit de paper/ y push normal (nunca --force). Antes del commit
# comprueba que esta en main y que los commits pendientes de publicar son
# solo commits automaticos de paper/; si no, se detiene sin hacer commit.
# Los errores quedan en reports/automation/ (ignorado por Git).

$AutomationPrefix = "paper: datos hasta "

function Get-UnpushedForeignCommits {
    # Commits de origin/main..HEAD que NO son automaticos de paper/.
    $foreign = @()
    $commits = git rev-list "origin/main..HEAD"
    if ($LASTEXITCODE -ne 0) { throw "git rev-list termino con codigo $LASTEXITCODE" }
    foreach ($commit in $commits) {
        $subject = git log -1 --format=%s $commit
        # La automatizacion nunca crea merges: un merge pendiente es ajeno
        # (diff-tree no lista los cambios de un merge; revision de Codex).
        $parents = @((git rev-list --parents -n 1 $commit) -split " ").Count - 1
        $files = git diff-tree --no-commit-id --name-only -r $commit
        $onlyPaper = @($files | Where-Object { -not $_.StartsWith("paper/") }).Count -eq 0
        if ($parents -ne 1 -or -not $subject.StartsWith($AutomationPrefix) -or -not $onlyPaper) {
            $foreign += $commit
        }
    }
    return $foreign
}

function Get-UnpushedNonPaperFiles {
    # Archivos fuera de paper/ en la diferencia acumulada origin/main..HEAD
    # (cubre cualquier via, incluidos merges).
    $files = git diff --name-only "origin/main" HEAD
    if ($LASTEXITCODE -ne 0) { throw "git diff origin/main termino con codigo $LASTEXITCODE" }
    return @($files | Where-Object { $_ -and -not $_.StartsWith("paper/") })
}

function Assert-SafeToCommit {
    $branch = git rev-parse --abbrev-ref HEAD
    if ($LASTEXITCODE -ne 0 -or $branch -ne "main") {
        throw "la rama actual es '$branch', no main; no se hace commit"
    }
    $foreign = @(Get-UnpushedForeignCommits)
    if ($foreign.Count -gt 0) {
        throw ("hay $($foreign.Count) commits sin publicar que no son automaticos de paper/ " +
               "($($foreign -join ', ')); no se hace commit para no publicarlos")
    }
    $outside = @(Get-UnpushedNonPaperFiles)
    if ($outside.Count -gt 0) {
        throw ("los cambios sin publicar tocan archivos fuera de paper/ " +
               "($($outside -join ', ')); no se hace commit para no publicarlos")
    }
}

function Test-PaperStaged {
    # $true si paper/ tiene cambios preparados; error si git diff falla.
    git diff --cached --quiet -- paper/
    switch ($LASTEXITCODE) {
        0 { return $false }
        1 { return $true }
        default { throw "git diff --cached termino con codigo $LASTEXITCODE" }
    }
}

function Invoke-Daily {
    $ErrorActionPreference = "Continue"  # se comprueba $LASTEXITCODE de cada paso
    $repo = Split-Path -Parent $PSScriptRoot
    Set-Location $repo
    $env:PYTHONIOENCODING = "utf-8"
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }  # acentos en el log
    $python = Join-Path $repo ".venv\Scripts\python.exe"
    $logDir = Join-Path $repo "reports\automation"
    New-Item -ItemType Directory -Force $logDir | Out-Null
    $script:log = Join-Path $logDir ("paper_" + (Get-Date -Format "yyyy-MM-dd") + ".log")

    try {
        Write-Log "inicio"
        foreach ($symbol in "BTCUSDT", "ETHUSDT", "SOLUSDT") {
            Invoke-Step "descarga $symbol" {
                & $python -m bottrading.download --symbol $symbol --interval 1d --daily --start 2026-10-01
            }
        }
        Invoke-Step "paper" { & $python -m bottrading.paper }

        Assert-SafeToCommit
        Invoke-Step "git add" { git add -- paper/ }
        if (Test-PaperStaged) {
            $day = (Select-String -Path "paper\ledger.state" -Pattern '^last_day=(.+)$').Matches[0].Groups[1].Value
            # Con rutas, git commit incluye SOLO paper/ aunque haya otros cambios preparados.
            Invoke-Step "git commit" { git commit -m "$AutomationPrefix$day (automatico, D028)" -- paper/ }
        } else {
            Write-Log "sin cambios en paper/"
        }
        # Publica lo pendiente; Assert-SafeToCommit garantizo que solo son commits
        # automaticos de paper/. Si el push falla, se reintenta al dia siguiente.
        $pending = @(git rev-list "origin/main..HEAD").Count
        if ($pending -gt 0) {
            Invoke-Step "git push" { git push origin main }
            Write-Log "publicados $pending commits automaticos"
        }
        Write-Log "OK"
        return 0
    }
    catch {
        Write-Log "ERROR: $_"
        return 1
    }
}

function Write-Log([string]$message) {
    "$(Get-Date -Format s) $message" | Out-File -Append -Encoding utf8 $script:log
}

function Invoke-Step([string]$name, [scriptblock]$command) {
    $output = & $command 2>&1 | ForEach-Object { "$_" }
    $output | Out-File -Append -Encoding utf8 $script:log
    if ($LASTEXITCODE -ne 0) { throw "$name termino con codigo $LASTEXITCODE" }
}

# Al cargarlo con ". .\paper_daily.ps1" (pruebas) solo se definen las funciones.
if ($MyInvocation.InvocationName -ne ".") {
    exit (Invoke-Daily)
}
