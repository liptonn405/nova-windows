param([switch]$Voice, [switch]$Dev)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
# Prefer Python 3.12. 3.11 also supported. Do not install system software silently.
$Python = $null
foreach ($version in @('3.12', '3.11')) {
    try {
        & py "-$version" -c 'import sys; assert sys.maxsize > 2**32' 2>$null
        if ($LASTEXITCODE -eq 0) { $Python = $version; break }
    } catch { }
}
if (-not $Python) { throw 'Install Python 3.12 x64 with the Python launcher (py), then run install.ps1 again. See README.md.' }
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    & py "-$Python" -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
}
$Exe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $Exe -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,13) and sys.maxsize > 2**32'
if ($LASTEXITCODE -ne 0) { throw 'Existing .venv uses an unsupported Python. Rename it and retry.' }
& $Exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip update failed.' }
$Target = '.'
if ($Voice -and $Dev) { $Target = '.[voice,dev]' }
elseif ($Voice) { $Target = '.[voice]' }
elseif ($Dev) { $Target = '.[dev]' }
& $Exe -m pip install -c (Join-Path $PSScriptRoot 'constraints-windows.txt') -e $Target
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See output above.' }
Write-Host 'NOVA installed. Run start.bat. Model setup is described in README.md.' -ForegroundColor Green
