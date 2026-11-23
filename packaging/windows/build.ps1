<#
.SYNOPSIS
  Construit les paquets Windows : dist\HandShortCut-Setup-<version>.exe (Inno Setup)
  et dist\HandShortCut-<version>-x64.msi (WiX).
.DESCRIPTION
  1. compile l'executable natif avec Nuitka (uv + compilateur C : Nuitka telecharge
     MinGW64 automatiquement au premier lancement) ;
  2. l'empaquete avec Inno Setup 6 (ISCC.exe ; $env:ISCC pour un chemin personnalise) ;
  3. construit le MSI avec WiX v5 (build_msi.ps1).
  -SkipExe / -SkipMsi / -SkipCompile : ignore une etape (ex. -SkipCompile pour reutiliser build\exe).
#>
param([switch]$SkipExe, [switch]$SkipMsi, [switch]$SkipCompile)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Version = (Select-String -Path "$Root\pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "==> HandShortCut $Version"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv introuvable : https://docs.astral.sh/uv/" }
if (-not $SkipCompile) {
Push-Location $Root
try {
    uv sync --frozen --group build --python 3.12
    if ($LASTEXITCODE -ne 0) { throw "uv sync a echoue" }
    uv run --frozen --group build python packaging/build_exe.py
    if ($LASTEXITCODE -ne 0) { throw "La compilation Nuitka a echoue" }
} finally { Pop-Location }
}

if (-not $SkipExe) {
    $Iscc = if ($env:ISCC) { $env:ISCC } else { "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
    if (-not (Test-Path $Iscc)) { throw "ISCC.exe introuvable ($Iscc). Installe Inno Setup 6 ou definis `$env:ISCC." }
    & $Iscc "/DMyAppVersion=$Version" "$PSScriptRoot\setup.iss"
    if ($LASTEXITCODE -ne 0) { throw "ISCC a echoue" }
}
if (-not $SkipMsi) { & "$PSScriptRoot\build_msi.ps1" }
Get-ChildItem "$Root\dist" | Where-Object { $_.Name -match 'HandShortCut' }
