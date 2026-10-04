$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Repo = "cryptalent-ai/market-state-explorer"
$Root = Join-Path $env:LOCALAPPDATA "MarketStateExplorerRelay"
$ZipPath = Join-Path $env:TEMP "market-state-explorer-main.zip"
$ExtractRoot = Join-Path $env:TEMP "market-state-explorer-main-extract"
$TaskName = "MarketStateExplorerRelay"

Write-Host "Market State Explorer v1.1 - Local Relay Installer" -ForegroundColor Cyan
Write-Host "This uses your own network connection to fetch official Binance public data."
Write-Host "It does not use a proxy, VPN, or geo-bypass."

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' was not found. Install Python 3.12 first."
}
& py -3.12 -c "import sys; assert sys.version_info[:2] == (3,12)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Python 3.12 was not found." }

$Gh = (Get-Command gh -ErrorAction SilentlyContinue)
if (-not $Gh) {
    Write-Host "GitHub CLI not found. Installing with winget..." -ForegroundColor Yellow
    & winget install --id GitHub.cli --exact --source winget --accept-package-agreements --accept-source-agreements
    $KnownGh = "C:\Program Files\GitHub CLI\gh.exe"
    if (Test-Path $KnownGh) {
        $GhPath = $KnownGh
    } else {
        throw "GitHub CLI was installed but could not be located. Re-open PowerShell and run this installer again."
    }
} else {
    $GhPath = $Gh.Source
}

& $GhPath auth status --hostname github.com 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "A browser window will open for GitHub authorization." -ForegroundColor Yellow
    & $GhPath auth login --hostname github.com --web --git-protocol https
    if ($LASTEXITCODE -ne 0) { throw "GitHub authentication was not completed." }
}

Write-Host "Downloading the current production source..."
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
if (Test-Path $ExtractRoot) { Remove-Item $ExtractRoot -Recurse -Force }
New-Item -ItemType Directory -Path $ExtractRoot -Force | Out-Null
Invoke-WebRequest -Uri "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $ZipPath
Expand-Archive -Path $ZipPath -DestinationPath $ExtractRoot -Force
$SourceRoot = Join-Path $ExtractRoot "market-state-explorer-main"
if (-not (Test-Path $SourceRoot)) { throw "Downloaded repository archive had an unexpected layout." }

if (Test-Path $Root) { Remove-Item $Root -Recurse -Force }
New-Item -ItemType Directory -Path $Root -Force | Out-Null
Copy-Item -Path (Join-Path $SourceRoot "*") -Destination $Root -Recurse -Force

Write-Host "Creating the isolated Python environment..."
& py -3.12 -m venv (Join-Path $Root ".venv")
$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -e $Root

$Publisher = Join-Path $Root "scripts\publish_live_relay.py"
Write-Host "Running one live publish test..." -ForegroundColor Cyan
Push-Location $Root
try {
    & $PythonExe $Publisher
    if ($LASTEXITCODE -ne 0) {
        throw "The first relay publish failed. No scheduled task was created."
    }
} finally {
    Pop-Location
}

$TaskCommand = '"' + $PythonExe + '" "' + $Publisher + '"'
Write-Host "Creating a 5-minute Windows scheduled task..."
& schtasks.exe /Create /SC MINUTE /MO 5 /TN $TaskName /TR $TaskCommand /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "The live publish succeeded, but Windows Task Scheduler registration failed."
}

Write-Host ""
Write-Host "Relay installation complete." -ForegroundColor Green
Write-Host "Task: $TaskName"
Write-Host "Install folder: $Root"
Write-Host "The Streamlit site will treat relay data as stale if no successful update arrives for 15 minutes."
Write-Host "You can stop it later with: schtasks /Delete /TN $TaskName /F"
