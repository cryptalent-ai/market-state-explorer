"""Installer functions exercised without auth/download/production task mutations.

All-platform tests execute real PowerShell generation. Windows tests additionally
execute real PowerShell 5.1 and wscript with a hermetic fake publisher. Hidden
window configuration is tested; GUI visibility still requires a human observer.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "scripts/install_windows_relay.ps1"
SOURCE = INSTALLER.read_text(encoding="utf-8-sig")
SHELL = shutil.which("powershell.exe") if sys.platform == "win32" else shutil.which("pwsh")
WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Real Windows PowerShell 5.1 / WSH integration")
LOAD_FUNCTIONS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$Tokens = $null
$ParseErrors = $null
$Ast = [Management.Automation.Language.Parser]::ParseFile($env:RELAY_TEST_INSTALLER, [ref]$Tokens, [ref]$ParseErrors)
if ($ParseErrors.Count) { throw ($ParseErrors | Out-String) }
$Definitions = $Ast.FindAll({ param($Node) $Node -is [Management.Automation.Language.FunctionDefinitionAst] }, $false)
foreach ($Definition in $Definitions) { . ([scriptblock]::Create($Definition.Extent.Text)) }
$Data = $env:RELAY_TEST_DATA | ConvertFrom-Json
"""


def ps(command, data=None, *, check=True):
    if not SHELL:
        pytest.skip("PowerShell unavailable; CI installs/uses pwsh and Windows PowerShell")
    env = dict(os.environ, RELAY_TEST_INSTALLER=str(INSTALLER), RELAY_TEST_DATA=json.dumps(data or {}, ensure_ascii=False))
    result = subprocess.run([SHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", LOAD_FUNCTIONS+command],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    if check:
        assert result.returncode == 0, result.stdout+result.stderr
    return result


def generate(root, python=None, publisher=None):
    data = {"root": str(root), "python": python or r"C:\Users\Test User\Python 3.12\python.exe",
            "publisher": publisher or str(root / "scripts" / "publish_live_relay.py"),
            "gh": r"C:\Program Files\GitHub CLI\gh.exe",
            "powershell": os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\WindowsPowerShell\v1.0\powershell.exe")}
    result = ps("Write-RelayLaunchers -InstallRoot $Data.root -PythonExe $Data.python -Publisher $Data.publisher -GhPath $Data.gh -PowerShellExe $Data.powershell | ConvertTo-Json -Compress", data)
    return json.loads(result.stdout)


@pytest.fixture
def launchers(tmp_path):
    root = tmp_path / "Users" / "O'Brien Tést & $user ` __LOG__" / "Local Relay With Spaces"
    paths = generate(root)
    return root, paths


def test_installer_creates_powershell_launcher(launchers):
    _, paths = launchers
    path = Path(paths["PowerShellPath"])
    assert path.name == "run_relay_hidden.ps1" and path.exists()
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_installer_creates_vbs_launcher(launchers):
    _, paths = launchers
    path = Path(paths["VbsPath"])
    assert path.name == "run_relay_hidden.vbs" and path.exists()
    assert path.read_bytes().startswith(b"\xff\xfe")


def test_hidden_vbs_waits_and_propagates_exit_code(launchers):
    _, paths = launchers
    text = Path(paths["VbsPath"]).read_text(encoding="utf-16")
    assert "rc = sh.Run(cmd, 0, True)" in text
    assert "WScript.Quit rc" in text
    assert "If Err.Number <> 0 Then WScript.Quit 1" in text
    assert "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File" in text
    assert f'q & "{paths["PowerShellPath"]}" & q' in text
    assert "cmd.exe" not in text.lower()


def test_wrapper_calls_production_publisher_and_appends_all_streams(launchers):
    root, paths = launchers
    text = Path(paths["PowerShellPath"]).read_text(encoding="utf-8-sig")
    assert "& $PythonExe $Publisher *>> $LogPath" in text
    assert "exit $PublisherExitCode" in text
    assert "$PublisherExitCode = $LASTEXITCODE" in text
    assert "$ErrorActionPreference = \"Continue\"" in text
    assert str(root / "scripts" / "publish_live_relay.py").replace("'", "''") in text
    assert str(root / "relay.log").replace("'", "''") in text
    assert "MARKET_STATE_GH = 'C:\\Program Files\\GitHub CLI\\gh.exe'" in text


@pytest.mark.parametrize("username", ["Test User", "O'Brien", "Tést 使用者", "user $() & ` name", "__ROOT__ __LOG__ __PYTHON__"])
def test_windows_quoting_survives_literal_user_paths(tmp_path, username):
    root = tmp_path / username / "Relay Install With Spaces"
    python = rf"C:\Users\{username}\Python Runtime With Spaces\python.exe"
    publisher = rf"C:\Users\{username}\Relay Install With Spaces\scripts\publish_live_relay.py"
    paths = generate(root, python, publisher)
    text = Path(paths["PowerShellPath"]).read_text(encoding="utf-8-sig")
    assert f"$PythonExe = '{python.replace(chr(39), chr(39)*2)}'" in text
    assert f"$Publisher = '{publisher.replace(chr(39), chr(39)*2)}'" in text
    # Parse actual generated PS literals, do not merely compare source templates.
    result = ps(r"""
    $T = $null; $E = $null
    $A = [Management.Automation.Language.Parser]::ParseFile($Data.ps, [ref]$T, [ref]$E)
    if ($E.Count) { throw ($E | Out-String) }
    $Assignments = $A.FindAll({ param($N) $N -is [Management.Automation.Language.AssignmentStatementAst] }, $true)
    $Values = @{}
    foreach ($N in $Assignments) {
        if ($N.Left.Extent.Text -in '$PythonExe', '$Publisher', '$LogPath', '$RelayRoot') {
            $Literal = $N.Right.Find({ param($S) $S -is [Management.Automation.Language.StringConstantExpressionAst] }, $false)
            $Values[$N.Left.Extent.Text] = $Literal.Value
        }
    }
    $Values | ConvertTo-Json -Compress
    """, {"ps": paths["PowerShellPath"]})
    values = json.loads(result.stdout)
    assert values["$PythonExe"] == python and values["$Publisher"] == publisher
    assert values["$RelayRoot"] == str(root)
    assert values["$LogPath"] == str(root / "relay.log")


def test_scheduled_action_uses_wscript_not_python(launchers):
    root, paths = launchers
    # Mock CIM construction only; execute the real action-generation function.
    result = ps(r"""
    function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory)
        [pscustomobject]@{ Execute=$Execute; Arguments=$Argument; WorkingDirectory=$WorkingDirectory }
    }
    New-RelayTaskAction -WScriptExe 'C:\Windows\System32\wscript.exe' -VbsPath $Data.vbs -InstallRoot $Data.root | ConvertTo-Json -Compress
    """, {"vbs": paths["VbsPath"], "root": str(root)})
    action = json.loads(result.stdout)
    assert action["Execute"] == r"C:\Windows\System32\wscript.exe"
    assert action["Arguments"] == f'//B //Nologo "{paths["VbsPath"]}"'
    assert action["WorkingDirectory"] == str(root)
    assert "python" not in action["Execute"].lower()


def test_reinstall_overwrites_launchers_but_preserves_log(launchers):
    root, paths = launchers
    log = Path(paths["LogPath"])
    log.write_text("previous successful relay\n", encoding="utf-8")
    Path(paths["PowerShellPath"]).write_text("old launcher", encoding="utf-8")
    Path(paths["VbsPath"]).write_text("old launcher", encoding="utf-8")
    again = generate(root)
    assert paths == again and log.read_text(encoding="utf-8") == "previous successful relay\n"
    assert "old launcher" not in Path(paths["PowerShellPath"]).read_text(encoding="utf-8-sig")
    assert "old launcher" not in Path(paths["VbsPath"]).read_text(encoding="utf-16")


def test_installer_preserves_main_auth_python_schedule_and_cache_contracts():
    assert "archive/refs/heads/main.zip" in SOURCE
    assert "& py -3.12 -m venv" in SOURCE and "-m pip install -e $Root" in SOURCE
    assert "auth status --hostname github.com" in SOURCE
    assert "auth login --hostname github.com --web --git-protocol https" in SOURCE
    assert '$Root = Join-Path $env:LOCALAPPDATA "MarketStateExplorerRelay"' in SOURCE
    assert '$TaskName = "MarketStateExplorerRelay"' in SOURCE
    assert "-RepetitionInterval (New-TimeSpan -Minutes 5)" in SOURCE
    assert "Register-ScheduledTask -TaskName $TaskName" in SOURCE and "-Force | Out-Null" in SOURCE
    assert "Remove-Item $Root" not in SOURCE and "Remove-Item $LogPath" not in SOURCE
    assert ".market-state-explorer" not in SOURCE
    assert "Start-Process -FilePath $WScript" in SOURCE
    assert "-WindowStyle Hidden -Wait -PassThru" in SOURCE
    assert "$LiveTest.ExitCode -ne 0" in SOURCE
    assert SOURCE.index("$LiveTest.ExitCode -ne 0") < SOURCE.index("Register-ScheduledTask -TaskName")
    assert "cmd.exe /c" not in SOURCE.lower()


@pytest.fixture
def real_launcher(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows-only executable integration")
    root = tmp_path / "O'Brien Tést & $user `" / "Relay With Spaces"
    root.mkdir(parents=True)
    # A junction gives the REAL base Python executable a path with spaces, with
    # its DLLs/stdlib intact. Remove only the junction itself before pytest cleanup.
    alias = root / "Python Runtime With Spaces"
    base = Path(sys._base_executable)
    ps("New-Item -ItemType Junction -Path $Data.alias -Target $Data.target | Out-Null", {"alias": str(alias), "target": str(base.parent)})
    publisher = root / "scripts" / "publish_live_relay.py"
    publisher.parent.mkdir()
    paths = generate(root, str(alias / base.name), str(publisher))
    try:
        yield root, publisher, paths
    finally:
        alias.rmdir()  # does NOT traverse/delete the Python runtime target


def run_launcher(paths, *, via_vbs):
    if via_vbs:
        command = [os.path.join(os.environ["SystemRoot"], "System32", "wscript.exe"), "//B", "//Nologo", paths["VbsPath"]]
    else:
        command = [SHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", paths["PowerShellPath"]]
    return subprocess.run(command, capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)


@WINDOWS
@pytest.mark.parametrize("via_vbs", [False, True])
@pytest.mark.parametrize("exit_code", [0, 7, 23])
def test_real_python_exit_and_stdout_stderr_logging(real_launcher, via_vbs, exit_code):
    root, publisher, paths = real_launcher
    publisher.write_text("import json, os, sys\nprint('Published relay (isolated mock only) — 使用者')\nprint('stderr-marker', file=sys.stderr)\nprint(json.dumps({'cwd':os.getcwd(), 'gh':os.environ.get('MARKET_STATE_GH'), 'argv':sys.argv}, ensure_ascii=False))\nsys.exit("+str(exit_code)+")\n", encoding="utf-8")
    result = run_launcher(paths, via_vbs=via_vbs)
    assert result.returncode == exit_code, result.stderr
    log = Path(paths["LogPath"]).read_text(encoding="utf-8-sig")
    assert "Published relay (isolated mock only) — 使用者" in log
    assert "stderr-marker" in log
    audit = json.loads(next(line for line in log.splitlines() if line.startswith('{"cwd"')))
    assert audit["cwd"] == str(root)
    assert audit["argv"] == [str(publisher)]
    assert audit["gh"] == r"C:\Program Files\GitHub CLI\gh.exe"


@WINDOWS
@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_real_reinstall_and_repeated_run_append_existing_log(real_launcher, encoding):
    root, publisher, paths = real_launcher
    publisher.write_text("print('append-marker 使用者')\n", encoding="utf-8")
    log = Path(paths["LogPath"])
    log.write_text("prior-log-marker 使用者\n", encoding=encoding)
    before = log.read_bytes()
    for _ in range(2):
        generate(root, str(root / "Python Runtime With Spaces" / Path(sys._base_executable).name), str(publisher))
        assert run_launcher(paths, via_vbs=True).returncode == 0
    assert log.read_bytes().startswith(before)
    text = log.read_text(encoding=encoding)
    assert text.count("append-marker 使用者") == 2 and "prior-log-marker 使用者" in text


@WINDOWS
@pytest.mark.parametrize("failure", ["missing_python", "missing_publisher", "log_is_directory"])
def test_launcher_failure_cannot_masquerade_as_success(real_launcher, failure):
    root, publisher, paths = real_launcher
    if failure != "missing_publisher":
        publisher.write_text("print('should-not-run')\n", encoding="utf-8")
    if failure == "missing_python":
        generate(root, str(root / "missing python.exe"), str(publisher))
    if failure == "log_is_directory":
        Path(paths["LogPath"]).mkdir()
    assert run_launcher(paths, via_vbs=True).returncode != 0


@WINDOWS
@pytest.mark.parametrize("exit_code", [0, 7])
def test_real_isolated_scheduled_task_result_and_re_registration(real_launcher, exit_code):
    root, publisher, paths = real_launcher
    publisher.write_text("import sys\nprint('Published relay (scheduler mock only)')\nprint('scheduler-stderr', file=sys.stderr)\nsys.exit("+str(exit_code)+")\n", encoding="utf-8")
    # Unique temporary test task, never the user's production task. Admin CI can
    # use S4U headlessly; a normal desktop token uses its existing login session.
    task_name = "MarketStateExplorerRelay-Test-" + uuid4().hex
    result = ps(r"""
    if ($Data.name -notmatch '^MarketStateExplorerRelay-Test-[0-9a-f]{32}$') { throw 'Unsafe test task name' }
    $Action = New-RelayTaskAction -WScriptExe (Join-Path $env:SystemRoot 'System32\wscript.exe') -VbsPath $Data.vbs -InstallRoot $Data.root
    $Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddDays(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $IsAdmin = ([Security.Principal.WindowsPrincipal]::new($Identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $LogonType = if ($IsAdmin) { 'S4U' } else { 'Interactive' }
    $Principal = New-ScheduledTaskPrincipal -UserId $Identity.Name -LogonType $LogonType
    try {
        foreach ($Iteration in 1..2) {
            Register-ScheduledTask -TaskName $Data.name -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
        }
        $Installed = Get-ScheduledTask -TaskName $Data.name
        $BeforeRun = (Get-ScheduledTaskInfo -TaskName $Data.name).LastRunTime
        Start-ScheduledTask -TaskName $Data.name
        $Deadline = (Get-Date).AddSeconds(20)
        do {
            Start-Sleep -Milliseconds 100
            $Info = Get-ScheduledTaskInfo -TaskName $Data.name
            $Task = Get-ScheduledTask -TaskName $Data.name
            # CIM LastRunTime and wall-clock DateTime may use different zones.
            # Observe the scheduler's own before/after value, not Get-Date.
            $Finished = $Info.LastRunTime -ne $BeforeRun -and $Task.State -ne 'Running' -and $Info.LastTaskResult -ne 267009
        } while (-not $Finished -and (Get-Date) -lt $Deadline)
        if (-not $Finished) { throw 'Isolated scheduled task did not complete' }
        [pscustomobject]@{ result=$Info.LastTaskResult; execute=$Installed.Actions[0].Execute;
            arguments=$Installed.Actions[0].Arguments; interval=$Installed.Triggers[0].Repetition.Interval;
            duration=$Installed.Triggers[0].Repetition.Duration } | ConvertTo-Json -Compress
    } finally {
        Stop-ScheduledTask -TaskName $Data.name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $Data.name -Confirm:$false -ErrorAction SilentlyContinue
    }
    """, {"name": task_name, "vbs": paths["VbsPath"], "root": str(root)})
    info = json.loads(result.stdout)
    assert info["result"] == exit_code
    assert info["execute"].lower().endswith("wscript.exe")
    assert info["arguments"] == f'//B //Nologo "{paths["VbsPath"]}"'
    assert info["interval"] == "PT5M" and info["duration"] in (None, "")
    log = Path(paths["LogPath"]).read_text(encoding="utf-8-sig")
    assert "Published relay (scheduler mock only)" in log and "scheduler-stderr" in log


def test_v131_publisher_and_cache_implementation_are_frozen():
    # Captured from approved production main, not regenerated model fixtures.
    expected = json.loads((ROOT / "tests/fixtures/v132_launcher_protected_sha256.json").read_text("utf-8"))
    assert set(expected) == {"scripts/publish_live_relay.py", "src/cache.py", "src/live_data.py", "src/oi_alignment.py"}
    for path, digest in expected.items():
        assert hashlib.sha256((ROOT/path).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest
