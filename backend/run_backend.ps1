# AutoCut — бэкенд с автоперезапуском при падении (watchdog)
$root = Split-Path -Parent $PSScriptRoot
$py = "$root\.venv\Scripts\python.exe"
$backend = "$root\backend"
$log = "$backend\uvicorn.out.log"

Set-Location -LiteralPath $backend

while ($true) {
    Write-Host ("[{0}] starting backend..." -f (Get-Date -Format HH:mm:ss))
    try {
        & $py -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload *>> $log
    } catch {
        Write-Host ("[{0}] uvicorn error: {1}" -f (Get-Date -Format HH:mm:ss), $_)
    }
    Write-Host ("[{0}] backend exited, restart in 3s" -f (Get-Date -Format HH:mm:ss))
    Start-Sleep -Seconds 3
}