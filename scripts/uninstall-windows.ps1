$ErrorActionPreference = "Stop"

$AppName = "Elite Journal Helper"
$InstallDir = Join-Path $env:LOCALAPPDATA "EliteJournalHelper"
$StartLink = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"
$DesktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk"

Remove-Item $StartLink -Force -ErrorAction SilentlyContinue
Remove-Item $DesktopLink -Force -ErrorAction SilentlyContinue
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "$AppName removed."
