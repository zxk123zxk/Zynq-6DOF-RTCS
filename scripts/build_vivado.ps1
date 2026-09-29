param([switch]$Build)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$artifacts = Join-Path $repoRoot 'artifacts'
foreach ($name in @('vivado','hw','reports','sd','logs','sim')) {
  New-Item -ItemType Directory -Force -Path (Join-Path $artifacts $name) | Out-Null
}
$vivado = Get-Command vivado.bat -ErrorAction SilentlyContinue
if ($null -eq $vivado) {
  $fallback = 'D:\3.Electronic_Information\vivado\Vivado\2023.2\bin\vivado.bat'
  if (Test-Path -LiteralPath $fallback) { $vivado = Get-Item -LiteralPath $fallback }
}
if ($null -eq $vivado) { throw 'Vivado 2023.2 vivado.bat not found' }
$script = Join-Path $repoRoot 'src\pl\vivado\create_project.tcl'
$modeArg = if ($Build) { @('-tclargs','build') } else { @() }
Push-Location (Join-Path $artifacts 'vivado')
try {
  & $vivado.Source -mode batch -source $script -log (Join-Path $artifacts 'logs\vivado.log') -journal (Join-Path $artifacts 'logs\vivado.jou') @modeArg
  if ($LASTEXITCODE -ne 0) { throw "Vivado failed, exit code $LASTEXITCODE; see artifacts/logs/vivado.log" }
} finally {
  Pop-Location
}
if ($Build) {
  $xsa = Join-Path $artifacts 'hw\rtcs_system.xsa'
  if (-not (Test-Path -LiteralPath $xsa) -or (Get-Item -LiteralPath $xsa).Length -eq 0) {
    throw "Vivado returned success without nonempty XSA: $xsa"
  }
  Write-Output "RTCS_BUILD_OK $xsa"
}
