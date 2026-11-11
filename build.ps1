param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    $py = ".\.venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        throw "Virtual environment missing. Run: py -3.12 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    }

    Write-Host "== Rendering icon ==" -ForegroundColor Cyan
    & $py tools\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }

    if (-not $SkipTests) {
        Write-Host "== Solver tests ==" -ForegroundColor Cyan
        & $py tests\test_solver.py
        if ($LASTEXITCODE -ne 0) { throw "solver tests failed" }

        Write-Host "== GUI tests ==" -ForegroundColor Cyan
        & $py tests\test_gui.py
        if ($LASTEXITCODE -ne 0) { throw "GUI tests failed" }
    }

    Write-Host "== PyInstaller ==" -ForegroundColor Cyan
    & $py -m PyInstaller --noconfirm --clean OpenSeesStudio.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

    Write-Host "== PyInstaller (MCP server) ==" -ForegroundColor Cyan
    & $py -m PyInstaller --noconfirm --clean OpenSeesStudioMCP.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller (MCP) failed" }

    Write-Host "== MCP tests (source) ==" -ForegroundColor Cyan
    & $py tests\test_mcp.py
    if ($LASTEXITCODE -ne 0) { throw "MCP tests failed" }

    Write-Host "== MCP tests (frozen exe) ==" -ForegroundColor Cyan
    $env:MCP_EXE = (Resolve-Path "dist\OpenSeesStudioMCP\OpenSeesStudioMCP.exe").Path
    & $py tests\test_mcp.py
    Remove-Item Env:MCP_EXE -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) { throw "frozen MCP tests failed" }

    Write-Host "== Inno Setup ==" -ForegroundColor Cyan
    $iscc = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
    & $iscc "packaging\installer.iss"
    if ($LASTEXITCODE -ne 0) { throw "installer build failed" }

    Write-Host "== Frozen self test ==" -ForegroundColor Cyan
    $report = Join-Path $env:TEMP "opensees_studio_selftest.txt"
    $p = Start-Process -FilePath "dist\OpenSeesStudio\OpenSeesStudio.exe" `
        -ArgumentList "--selftest", "--report", $report -Wait -PassThru
    Get-Content $report -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) { throw "frozen self test failed" }

    Write-Host "`nBuild complete:" -ForegroundColor Green
    Write-Host "  dist\OpenSeesStudio\OpenSeesStudio.exe"
    Write-Host "  dist\OpenSeesStudioMCP\OpenSeesStudioMCP.exe"
    Write-Host "  dist\OpenSeesStudio-1.0.0-Setup.exe"
}
finally {
    Pop-Location
}
