param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Link = Join-Path ([Environment]::GetFolderPath('Startup')) 'NOVA.lnk'
if ($Remove) {
    if (Test-Path $Link) { Remove-Item -LiteralPath $Link }
    Write-Host 'NOVA startup shortcut removed.'
    exit
}
$Python = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $Python)) { throw 'Install NOVA first.' }
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($Link)
$Shortcut.TargetPath = $Python
$Shortcut.Arguments = '-m nova.app'
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = 'NOVA desktop companion'
$Shortcut.Save()
Write-Host 'NOVA will start at sign-in for this Windows user.'
