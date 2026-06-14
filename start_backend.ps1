param(
    [int]$Port = 8000
)

Set-Location "$PSScriptRoot\backend"
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

function Stop-PortListener([int]$TargetPort) {
    $connections = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $connections) {
        $processId = $conn.OwningProcess
        if ($processId -gt 0) {
            $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "Port $TargetPort is in use by $($proc.ProcessName) (PID $processId). Stopping..."
                Stop-Process -Id $processId -Force
                Start-Sleep -Seconds 1
            }
        }
    }
}

Stop-PortListener -TargetPort $Port

# If port still busy, try next port
$maxAttempts = 5
$attempt = 0
while ($attempt -lt $maxAttempts) {
    $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $busy) { break }
    Write-Host "Port $Port still busy, trying $($Port + 1)..."
    $Port++
    $attempt++
}

if ($attempt -ge $maxAttempts) {
    Write-Host "ERROR: Could not find a free port."
    exit 1
}

& $py -m pip install -r requirements.txt -q
Write-Host "Starting API server on http://127.0.0.1:$Port"
Write-Host "Set this URL in the app settings if needed."
& $py -m uvicorn api.main:app --host 0.0.0.0 --port $Port --reload
