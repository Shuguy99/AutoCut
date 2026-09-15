# AutoCut — запуск: бэкенд (watchdog) + фронтенд одной командой (Windows)
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$EXPECTED_VERSION = "0.3.0"

$py = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Создаю виртуальное окружение..."
    python -m venv "$root\.venv"
    & "$root\.venv\Scripts\pip.exe" install -r "$root\backend\requirements.txt"
    if ($LASTEXITCODE -ne 0) { Write-Host "pip install не удалась (код $LASTEXITCODE)" -ForegroundColor Red }
}
if (-not (Test-Path "$root\frontend\node_modules")) {
    Write-Host "Ставлю зависимости фронтенда..."
    Push-Location "$root\frontend"
    & npm install
    if ($LASTEXITCODE -ne 0) { Write-Host "npm install не удалась (код $LASTEXITCODE)" -ForegroundColor Red }
    Pop-Location
}

# NOTE: Invoke-WebRequest/Invoke-RestMethod в контексте -File падают с WebException;
# работаем через WebClient с отключённым прокси.
function Get-Health {
    $wc = New-Object System.Net.WebClient
    $wc.Proxy = $null
    try {
        $json = $wc.DownloadString("http://127.0.0.1:8000/api/health")
        return ($json | ConvertFrom-Json)
    } catch { }
    return $null
}

function Test-Port([int]$Port) {
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(1000)) { $c.EndConnect($iar); return $true }
    } catch { }
    finally { $c.Close() }
    return $false
}

function Clear-StrayBackends {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*uvicorn*main:app*' } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# ---------- Ollama ----------
if (Test-Port 11434) {
    Write-Host "Ollama уже запущен (11434)."
} else {
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if ($ollama) {
        Write-Host "Запускаю Ollama..."
        Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
        $tries = 0
        while ($tries -lt 30) {
            Start-Sleep -Seconds 1
            if (Test-Port 11434) { break }
            $tries++
        }
        if (Test-Port 11434) { Write-Host "Ollama поднялся (11434)." }
        else { Write-Host "Ollama запущен, но 11434 ещё не слушается." -ForegroundColor Yellow }
    } else {
        Write-Host "Команда ollama не найдена в PATH — ИИ-скоринг недоступен." -ForegroundColor Yellow
    }
}

# ---------- Бэкенд ----------
$h = Get-Health
$needStartB = $true
if ($h -and $h.version -eq $EXPECTED_VERSION) {
    Write-Host "Бэкенд уже запущен (v$EXPECTED_VERSION)."
    $needStartB = $false
} elseif ($h) {
    Write-Host "Бэкенд работает на старой версии ($($h.version)) — перезапускаю..."
} else {
    Write-Host "Бэкенд не отвечает — запускаю..."
}

if ($needStartB) {
    Clear-StrayBackends
    Start-Sleep -Seconds 1
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "$root\backend\run_backend.ps1" -WindowStyle Hidden

    $tries = 0
    $h = $null
    while ($tries -lt 45) {
        Start-Sleep -Seconds 1
        $h = Get-Health
        if ($h -and $h.version -eq $EXPECTED_VERSION) { break }
        $tries++
    }
    if ($h -and $h.version -eq $EXPECTED_VERSION) {
        Write-Host "Бэкенд поднялся (v$EXPECTED_VERSION): http://127.0.0.1:8000"
    } else {
        Write-Host "Бэкенд не поднялся за 45с. Смотри лог: backend\uvicorn.out.log" -ForegroundColor Red
    }
}

# ---------- Фронтенд ----------
if (Test-Port 5173) {
    Write-Host "Фронтенд уже запущен."
} else {
    Write-Host "Запускаю фронтенд..."
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm", "run", "dev", "--", "--host", "127.0.0.1" -WorkingDirectory "$root\frontend" -WindowStyle Hidden

    $tries = 0
    while ($tries -lt 45) {
        Start-Sleep -Seconds 1
        if (Test-Port 5173) { break }
        $tries++
    }
    if (Test-Port 5173) { Write-Host "Фронтенд поднялся: http://127.0.0.1:5173" }
    else { Write-Host "Фронтенд не поднялся за 45с. Проверь npm/node" -ForegroundColor Red }
}

Start-Process "http://127.0.0.1:5173"
Write-Host ""
Write-Host "AutoCut готов: http://127.0.0.1:5173 (бэкенд http://127.0.0.1:8000)"