# Build Genius Control for Windows: dist\GeniusControl.exe (one self-contained file).
#
# Run this ON Windows (PyInstaller can't cross-compile), either by
# double-clicking build_windows.bat or from PowerShell:
#     powershell -ExecutionPolicy Bypass -File build_windows.ps1
#
# Needs Python 3.10+ from https://www.python.org/downloads/windows/ (it includes
# tkinter / Tcl/Tk). To pick a specific Python:  $env:PYTHON = "C:\path\python.exe"

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Test-Python([string]$Exe) {
    # Returns "ok <python> <tk>" or "bad <reason>".
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $Exe -I "$Root\tools\check_python.py" 2>$null | Select-Object -First 1
    } catch {
        $out = $null
    } finally {
        $ErrorActionPreference = $old
    }
    if (-not $out) { return "bad could not run it" }
    return [string]$out
}

function Get-Candidates {
    if ($env:PYTHON) { return @($env:PYTHON) }
    $list = New-Object System.Collections.Generic.List[string]
    # The py launcher knows every python.org install.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in "3.14", "3.13", "3.12", "3.11", "3.10") {
            $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            try { $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null } catch { $exe = $null }
            $ErrorActionPreference = $old
            if ($LASTEXITCODE -eq 0 -and $exe) { $list.Add(([string]$exe).Trim()) }
        }
    }
    foreach ($v in "314", "313", "312", "311", "310") {
        $list.Add("$env:LOCALAPPDATA\Programs\Python\Python$v\python.exe")
        $list.Add("$env:ProgramFiles\Python$v\python.exe")
    }
    foreach ($cmd in Get-Command python, python3 -All -ErrorAction SilentlyContinue) {
        # Skip the Microsoft Store "python" shortcut, which only opens the Store.
        if ($cmd.Source -notlike "*\WindowsApps\*") { $list.Add($cmd.Source) }
    }
    return $list
}

$Py = $null
$seen = @{}
foreach ($c in Get-Candidates) {
    if (-not $c -or $seen.ContainsKey($c)) { continue }
    $seen[$c] = $true
    if (-not (Test-Path $c) -and -not (Get-Command $c -ErrorAction SilentlyContinue)) { continue }
    $result = Test-Python $c
    if ($result.StartsWith("ok ")) {
        $Py = $c
        $parts = $result.Split(" ")
        $PyVer = $parts[1]; $TkVer = $parts[2]
        break
    }
    Write-Host "Skipping ${c}: $($result.Substring(4))"
}

if (-not $Py) {
    Write-Host ""
    Write-Host "No suitable Python found. Genius Control needs Python 3.10+ with tkinter."
    Write-Host "Install it from https://www.python.org/downloads/windows/ (keep the"
    Write-Host "'tcl/tk and IDLE' option ticked), then run this script again."
    Write-Host "Or choose one:  `$env:PYTHON = 'C:\path\to\python.exe'"
    exit 1
}
Write-Host "Using $Py (Python $PyVer, Tcl/Tk $TkVer)"

# Build venv for this OS; recreated if it was made from a different Python.
$Venv = "build\venv-windows"
$VenvPy = "$Venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    $venvBase = & $VenvPy -c "import sys; print(sys.base_prefix)"
    $pyBase = & $Py -c "import sys; print(sys.base_prefix)"
    if (-not (Test-Python $VenvPy).StartsWith("ok ") -or $venvBase -ne $pyBase) {
        Write-Host "Recreating $Venv (it was built with a different Python)"
        Remove-Item -Recurse -Force $Venv
    }
}
if (-not (Test-Path "$Venv\Scripts\pyinstaller.exe")) {
    & $Py -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create $Venv" }
    & $VenvPy -m pip install -q --upgrade pip pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller" }
}

$Name = "GeniusControl"
Remove-Item -Force -ErrorAction SilentlyContinue "dist\$Name.exe"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "build\pyinstaller-windows"
& "$Venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed `
    --name $Name `
    --icon "$Root\assets\GeniusControl.ico" `
    --add-data "$Root\assets\icon.png;assets" `
    --workpath build\pyinstaller-windows --specpath build\pyinstaller-windows --distpath dist `
    genius_control.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host ""
Write-Host "Built: $Root\dist\$Name.exe"
Write-Host "Copy it anywhere (for example your Desktop) and double-click it to run."
