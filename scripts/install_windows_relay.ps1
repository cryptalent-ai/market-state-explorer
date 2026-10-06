$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Kept in this installer so it also works when executed as a standalone download.
# Tests load only these function definitions, never the production install flow.
function Write-RelayLaunchers {
    param(
        [Parameter(Mandatory)][string]$InstallRoot,
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][string]$Publisher,
        [Parameter(Mandatory)][string]$GhPath,
        [Parameter(Mandatory)][string]$PowerShellExe
    )
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    $PsPath = Join-Path $InstallRoot "run_relay_hidden.ps1"
    $VbsPath = Join-Path $InstallRoot "run_relay_hidden.vbs"
    $LogPath = Join-Path $InstallRoot "relay.log"
    # Single-quoted PS literals: spaces, apostrophes, $, backticks and Unicode
    # in user paths must remain data, never interpolation or executable text.
    $PsRoot = $InstallRoot.Replace("'", "''")
    $PsPython = $PythonExe.Replace("'", "''")
    $PsPublisher = $Publisher.Replace("'", "''")
    $PsGh = $GhPath.Replace("'", "''")
    $PsLog = $LogPath.Replace("'", "''")
    $PsTemplate = @'
$ErrorActionPreference = "Continue"
$RelayRoot = '__ROOT__'
$PythonExe = '__PYTHON__'
$Publisher = '__PUBLISHER__'
$LogPath = '__LOG__'
$env:MARKET_STATE_GH = '__GH__'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$PublisherExitCode = 1
$LocationPushed = $false
try {
    # Preserve old manual Windows PowerShell UTF-16 logs; new logs use UTF-8.
    $LogEncoding = 'utf8'
    if (Test-Path -LiteralPath $LogPath) {
        $Reader = [IO.File]::OpenRead($LogPath)
        try {
            if ($Reader.ReadByte() -eq 255 -and $Reader.ReadByte() -eq 254) {
                $LogEncoding = 'unicode'
            }
        } finally { $Reader.Dispose() }
    }
    $PSDefaultParameterValues['Out-File:Encoding'] = $LogEncoding
    # Fail before starting Python if the log cannot be created/appended.
    $LogProbe = [IO.File]::Open($LogPath, [IO.FileMode]::Append,
        [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
    $LogProbe.Dispose()
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Relay Python executable is missing: $PythonExe"
    }
    if (-not (Test-Path -LiteralPath $Publisher -PathType Leaf)) {
        throw "Relay publisher is missing: $Publisher"
    }
    Push-Location -LiteralPath $RelayRoot -ErrorAction Stop
    $LocationPushed = $true
    & $PythonExe $Publisher *>> $LogPath
    # Capture immediately; cleanup must not replace the publisher's exit code.
    if ($null -ne $LASTEXITCODE) { $PublisherExitCode = $LASTEXITCODE }
} catch {
    [Console]::Error.WriteLine("Relay launcher failed: " + $_.Exception.Message)
    $PublisherExitCode = 1
} finally {
    if ($LocationPushed) { Pop-Location }
}
exit $PublisherExitCode
'@
    # One regex replacement pass avoids accidentally substituting text INSIDE a
    # path (e.g. a username containing __LOG__). Replace is otherwise literal.
    $Values = @{ ROOT=$PsRoot; PYTHON=$PsPython; PUBLISHER=$PsPublisher; GH=$PsGh; LOG=$PsLog }
    $PsText = [regex]::Replace($PsTemplate, '__(ROOT|PYTHON|PUBLISHER|GH|LOG)__', {
        param($Match)
        $Values[$Match.Groups[1].Value]
    })
    $VbsPowerShell = $PowerShellExe.Replace('"', '""')
    $VbsScript = $PsPath.Replace('"', '""')
    $VbsText = @"
On Error Resume Next
Set sh = CreateObject("WScript.Shell")
q = Chr(34)
cmd = q & "$VbsPowerShell" & q & " -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " & q & "$VbsScript" & q
rc = sh.Run(cmd, 0, True)
If Err.Number <> 0 Then WScript.Quit 1
WScript.Quit rc
"@
    # BOMs are intentional: PS 5.1 and Windows Script Host must decode Unicode
    # user paths correctly. File writes overwrite launchers, never the log.
    [IO.File]::WriteAllText($PsPath, $PsText, [Text.UTF8Encoding]::new($true))
    [IO.File]::WriteAllText($VbsPath, $VbsText, [Text.UnicodeEncoding]::new($false, $true))
    [pscustomobject]@{ PowerShellPath=$PsPath; VbsPath=$VbsPath; LogPath=$LogPath }
}

function New-RelayTaskAction {
    param(
        [Parameter(Mandatory)][string]$WScriptExe,
        [Parameter(Mandatory)][string]$VbsPath,
        [Parameter(Mandatory)][string]$InstallRoot
    )
    # Structured executable/arguments avoids command-shell and nested /TR quoting.
    New-ScheduledTaskAction -Execute $WScriptExe -Argument ('//B //Nologo "' + $VbsPath + '"') -WorkingDirectory $InstallRoot
}

$Repo = "cryptalent-ai/market-state-explorer"
$Root = Join-Path $env:LOCALAPPDATA "MarketStateExplorerRelay"
$ZipPath = Join-Path $env:TEMP "market-state-explorer-main.zip"
$ExtractRoot = Join-Path $env:TEMP "market-state-explorer-main-extract"
$TaskName = "MarketStateExplorerRelay"

Write-Host "Market State Explorer - Local Relay Installer" -ForegroundColor Cyan
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

# Windows PowerShell 5.1 can turn a native program's stderr into a terminating
# NativeCommandError when ErrorActionPreference is Stop. `gh auth status`
# intentionally exits non-zero before first login, so probe it non-terminatingly.
$SavedErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $GhPath auth status --hostname github.com *> $null
$GhAuthExitCode = $LASTEXITCODE
$ErrorActionPreference = $SavedErrorActionPreference

if ($GhAuthExitCode -ne 0) {
    Write-Host "GitHub CLI is installed but not signed in." -ForegroundColor Yellow
    Write-Host "A browser authorization flow will start now." -ForegroundColor Yellow
    & $GhPath auth login --hostname github.com --web --git-protocol https
    if ($LASTEXITCODE -ne 0) { throw "GitHub authentication was not completed." }
}

# Make the freshly installed gh executable visible to child processes in this run.
$GhDir = Split-Path -Parent $GhPath
if (($env:PATH -split ';') -notcontains $GhDir) {
    $env:PATH = "$GhDir;$env:PATH"
}

Write-Host "Downloading the current production source..."
# Validate the one named temporary extraction directory before recursive cleanup.
$ResolvedTempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd([IO.Path]::DirectorySeparatorChar)
$ResolvedExtractRoot = [IO.Path]::GetFullPath($ExtractRoot)
if ([IO.Path]::GetDirectoryName($ResolvedExtractRoot) -ne $ResolvedTempRoot -or
    [IO.Path]::GetFileName($ResolvedExtractRoot) -ne "market-state-explorer-main-extract") {
    throw "Unsafe relay extraction cleanup path."
}
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
if (Test-Path -LiteralPath $ResolvedExtractRoot) { Remove-Item -LiteralPath $ResolvedExtractRoot -Recurse -Force }
New-Item -ItemType Directory -Path $ExtractRoot -Force | Out-Null
Invoke-WebRequest -Uri "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $ZipPath
Expand-Archive -Path $ZipPath -DestinationPath $ExtractRoot -Force
$SourceRoot = Join-Path $ExtractRoot "market-state-explorer-main"
if (-not (Test-Path $SourceRoot)) { throw "Downloaded repository archive had an unexpected layout." }

# Reinstall in place: keep existing relay.log and .venv. Never purge Relay cache.
New-Item -ItemType Directory -Path $Root -Force | Out-Null
Copy-Item -Path (Join-Path $SourceRoot "*") -Destination $Root -Recurse -Force

Write-Host "Creating the isolated Python environment..."
& py -3.12 -m venv (Join-Path $Root ".venv")
if ($LASTEXITCODE -ne 0) { throw "Relay Python environment creation failed." }
$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
& $PythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Relay pip upgrade failed." }
& $PythonExe -m pip install -e $Root
if ($LASTEXITCODE -ne 0) { throw "Relay package installation failed." }

$Publisher = Join-Path $Root "scripts\publish_live_relay.py"
$WindowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$WScript = Join-Path $env:SystemRoot "System32\wscript.exe"
$Launchers = Write-RelayLaunchers -InstallRoot $Root -PythonExe $PythonExe -Publisher $Publisher -GhPath $GhPath -PowerShellExe $WindowsPowerShell
Write-Host "Running one live publish test..." -ForegroundColor Cyan
$LiveTest = Start-Process -FilePath $WScript -ArgumentList ('//B //Nologo "' + $Launchers.VbsPath + '"') -WindowStyle Hidden -Wait -PassThru
if ($LiveTest.ExitCode -ne 0) {
    throw "The first relay publish failed (exit $($LiveTest.ExitCode)); see $($Launchers.LogPath). The scheduled task was not updated."
}

Write-Host "Creating a 5-minute Windows scheduled task..."
$Action = New-RelayTaskAction -WScriptExe $WScript -VbsPath $Launchers.VbsPath -InstallRoot $Root
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null

Write-Host ""
Write-Host "Relay installation complete." -ForegroundColor Green
Write-Host "Task: $TaskName"
Write-Host "Install folder: $Root"
Write-Host "Publisher log (append): $($Launchers.LogPath)"
Write-Host "The Streamlit site will treat relay data as stale if no successful update arrives for 15 minutes."
Write-Host "You can stop it later with: schtasks /Delete /TN $TaskName /F"
