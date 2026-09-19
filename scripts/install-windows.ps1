param([switch]$DesktopShortcut)

$ErrorActionPreference = "Stop"
$AppName = "Elite Journal Helper"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceDir = Split-Path -Parent $ScriptDir
$InstallDir = Join-Path $env:LOCALAPPDATA "EliteJournalHelper"
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$StartLink = Join-Path $StartMenu "$AppName.lnk"
$DesktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk"

if (-not (Test-Path (Join-Path $SourceDir "ed_journal_probe.py"))) {
    throw "Could not find ed_journal_probe.py in the project root."
}

$Python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" }
          elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" }
          else { throw "Python 3 was not found." }

if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

Get-ChildItem $SourceDir -Force | Where-Object {
    $_.Name -notin @(".git",".github","__pycache__",".pytest_cache",".venv","venv","build","dist",
                     "docs","tests","tools","scripts","requirements-dev.txt") `
    -and $_.Name -notmatch '^PreviousVersion' `
    -and $_.Name -notmatch '\.(log|sqlite|sqlite3|bak|patch)$'
} | ForEach-Object {
    Copy-Item $_.FullName $InstallDir -Recurse -Force
}

$Venv = Join-Path $InstallDir ".venv"
if ($Python -eq "py") { & py -3 -m venv $Venv } else { & python -m venv $Venv }

$Py = Join-Path $Venv "Scripts\python.exe"
$PyW = Join-Path $Venv "Scripts\pythonw.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r (Join-Path $InstallDir "requirements.txt")

$Main = Join-Path $InstallDir "ed_journal_probe.py"
$Ico = Join-Path $InstallDir "assets\ed_helper_icon.ico"
$Icon = if (Test-Path $Ico) { $Ico } else { $PyW }

function New-Link([string]$Path) {
    $Shell = New-Object -ComObject WScript.Shell
    $Link = $Shell.CreateShortcut($Path)
    $Link.TargetPath = $PyW
    $Link.Arguments = "`"$Main`""
    $Link.WorkingDirectory = $InstallDir
    $Link.Description = "Elite Dangerous exploration and construction journal helper"
    $Link.IconLocation = "$Icon,0"
    $Link.Save()
}

New-Item -ItemType Directory -Path $StartMenu -Force | Out-Null
New-Link $StartLink
if ($DesktopShortcut) { New-Link $DesktopLink }

Write-Host "$AppName installed to $InstallDir"
