$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $repoRoot 'build\sim'
$output = Join-Path $buildDir 'tb_servo_rx_only.vvp'
$iverilog = Get-Command iverilog.exe -ErrorAction SilentlyContinue
if ($null -eq $iverilog) {
  $fallback = 'D:\3.Electronic_Information\iverilog\bin\iverilog.exe'
  if (Test-Path -LiteralPath $fallback) { $iverilog = Get-Item -LiteralPath $fallback }
}
if ($null -eq $iverilog) { throw 'iverilog.exe not found' }
$vvp = Join-Path (Split-Path -Parent $iverilog.Source) 'vvp.exe'
if (-not (Test-Path -LiteralPath $vvp)) { throw 'vvp.exe not found' }
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
& $iverilog.Source -g2012 -s tb_servo_rx_only -o $output (Join-Path $repoRoot 'src\pl\rtl\servo_bus_master.sv') (Join-Path $PSScriptRoot 'tb_servo_rx_only.sv')
if ($LASTEXITCODE -ne 0) { throw 'RX-only compile failed' }
& $vvp $output
if ($LASTEXITCODE -ne 0) { throw 'RX-only simulation failed' }
