<#
.SYNOPSIS
  Construit le paquet MSI : dist\PhysicalShortCut-<version>-x64.msi
.DESCRIPTION
  Suppose que l'executable natif est deja compile (build\exe\physicalshortcut.dist, voir
  build.ps1). Necessite le WiX Toolset v5 :  dotnet tool install --global wix --version 5.0.2
  (l'extension d'interface WixToolset.UI.wixext est ajoutee automatiquement).
#>
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Dist = Join-Path $Root "build\exe\physicalshortcut.dist"
if (-not (Test-Path (Join-Path $Dist "physicalshortcut.exe"))) {
    throw "Executable introuvable ($Dist). Lance d'abord packaging\windows\build.ps1 (ou build_exe.py)."
}
if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    throw "wix introuvable. Installe-le : dotnet tool install --global wix --version 5.0.2"
}

$Version = (Select-String -Path "$Root\pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
# MSI : version numerique a 3 champs (x.y.z), sans suffixe de pre-version
$MsiVersion = ($Version -replace '^(\d+)\.(\d+)\.(\d+).*$', '$1.$2.$3')

# licence au format RTF (exigee par l'interface WiX)
$Build = Join-Path $Root "build\msi"
New-Item -ItemType Directory -Force $Build | Out-Null
$Rtf = Join-Path $Build "license.rtf"
$Text = (Get-Content -Raw -Encoding UTF8 "$Root\LICENSE") -replace '\\', '\\' -replace '\{', '\{' -replace '\}', '\}'
$Text = ($Text -split "`r?`n") -join "\par`r`n"
Set-Content -Encoding ASCII $Rtf ("{\rtf1\ansi\deff0{\fonttbl{\f0 Segoe UI;}}\fs18 " + $Text + "}")

wix extension add --global WixToolset.UI.wixext/5.0.2
if ($LASTEXITCODE -ne 0) { throw "Ajout de l'extension WiX UI impossible" }

$OutDir = Join-Path $Root "dist"
New-Item -ItemType Directory -Force $OutDir | Out-Null
$Msi = Join-Path $OutDir "PhysicalShortCut-$Version-x64.msi"
wix build "$PSScriptRoot\physicalshortcut.wxs" `
    -arch x64 -culture fr-FR `
    -ext WixToolset.UI.wixext `
    -d Version=$MsiVersion `
    -d DistDir=$Dist `
    -d IconFile="$Root\assets\icon.ico" `
    -d LicenseRtf=$Rtf `
    -o $Msi
if ($LASTEXITCODE -ne 0) { throw "wix build a echoue" }
Get-Item $Msi
