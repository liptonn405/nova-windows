$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Run install.ps1 first.' }
& $Python -m pip install -c (Join-Path $Root 'constraints-windows.txt') -e "${Root}[voice]"
if ($LASTEXITCODE -ne 0) { throw 'Voice dependency installation failed.' }
$Models = Join-Path $Root 'models'
New-Item -ItemType Directory -Force $Models | Out-Null
$Archive = Join-Path $Models 'vosk-model-small-ru-0.22.zip'
$Model = Join-Path $Models 'vosk-model-small-ru-0.22'
if (-not (Test-Path (Join-Path $Model 'am'))) {
    Write-Host 'Downloading the official Russian Vosk model (~45 MB)...'
    Invoke-WebRequest -Uri 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip' -OutFile $Archive
    Expand-Archive -LiteralPath $Archive -DestinationPath $Models -Force
    if (-not (Test-Path (Join-Path $Model 'am'))) { throw 'Model archive is incomplete.' }
    Remove-Item -LiteralPath $Archive
}
Write-Host 'Select this folder in NOVA Settings -> Vosk model:' -ForegroundColor Green
Write-Host $Model
