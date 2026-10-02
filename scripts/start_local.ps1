param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath 'frontend/dist/index.html')) {
    throw 'Run npm ci and npm run build in frontend before starting the combined application.'
}
$env:APP_ENV = 'development'
$env:DEMO_MODE = 'true'
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = 'sqlite:///./data/prototype.db' }
if (-not $env:UPLOAD_DIR) { $env:UPLOAD_DIR = './data/uploads' }
if (-not $env:SESSION_SECRET) {
    $env:SESSION_SECRET = [System.Guid]::NewGuid().ToString('N') + [System.Guid]::NewGuid().ToString('N')
}
python -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
