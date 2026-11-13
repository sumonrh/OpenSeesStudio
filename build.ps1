param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

function Get-SignTool {
    $patterns = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe",
        "$env:ProgramFiles\Windows Kits\10\bin\*\x64\signtool.exe"
    )
    foreach ($pattern in $patterns) {
        $found = @(Get-ChildItem $pattern -ErrorAction SilentlyContinue |
                   Sort-Object FullName -Descending | Select-Object -First 1)
        if ($found) { return $found[0].FullName }
    }
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Invoke-Sign {
    param([string[]]$Files)
    $pfx = $env:OSS_SIGN_PFX
    $thumb = $env:OSS_SIGN_THUMBPRINT
    if (-not $pfx -and -not $thumb) {
        Write-Host "   no certificate configured, skipping signing" -ForegroundColor DarkYellow
        return
    }
    $signtool = Get-SignTool
    if (-not $signtool) { throw "signtool.exe not found (install the Windows SDK)" }
    $signArgs = @("sign", "/fd", "sha256", "/tr", "http://timestamp.digicert.com", "/td", "sha256")
    if ($pfx) {
        $signArgs += @("/f", $pfx)
        if ($env:OSS_SIGN_PASSWORD) { $signArgs += @("/p", $env:OSS_SIGN_PASSWORD) }
    } else {
        $signArgs += @("/sha1", $thumb)
    }
    foreach ($file in $Files) {
        Write-Host "   signing $file"
        & $signtool @signArgs $file
        if ($LASTEXITCODE -ne 0) { throw "signing failed: $file" }
    }
}

try {
    $version = (Select-String -Path "packaging\installer.iss" `
        -Pattern '#define MyAppVersion "([^"]+)"').Matches[0].Groups[1].Value
    if (-not $version) { throw "could not read MyAppVersion from packaging\installer.iss" }
    $setup = "dist\OpenSeesStudio-$version-Setup.exe"
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

        Write-Host "== Analysis runner tests ==" -ForegroundColor Cyan
        & $py tests\test_analysis_runner.py
        if ($LASTEXITCODE -ne 0) { throw "analysis runner tests failed" }
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

    Write-Host "== Code signing ==" -ForegroundColor Cyan
    Invoke-Sign @("dist\OpenSeesStudio\OpenSeesStudio.exe",
                  "dist\OpenSeesStudioMCP\OpenSeesStudioMCP.exe")

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

    Write-Host "== Signing installer ==" -ForegroundColor Cyan
    Invoke-Sign @($setup)

    Write-Host "`nBuild complete:" -ForegroundColor Green
    Write-Host "  dist\OpenSeesStudio\OpenSeesStudio.exe"
    Write-Host "  dist\OpenSeesStudioMCP\OpenSeesStudioMCP.exe"
    Write-Host "  $setup"
    $hash = (Get-FileHash $setup -Algorithm SHA256).Hash
    Write-Host "  SHA256  $hash"
}
finally {
    Pop-Location
}
