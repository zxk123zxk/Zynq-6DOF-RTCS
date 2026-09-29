$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $repoRoot 'artifacts\sim'
$output = Join-Path $buildDir 'tb_hx30hm_protocol.vvp'
$package = Join-Path $repoRoot 'src\pl\rtl\hx30hm_protocol_pkg.sv'
$testbench = Join-Path $PSScriptRoot 'tb_hx30hm_protocol.sv'

$iverilog = Get-Command iverilog.exe -ErrorAction SilentlyContinue
if ($null -eq $iverilog) {
  $fallback = 'D:\3.Electronic_Information\iverilog\bin\iverilog.exe'
  if (Test-Path -LiteralPath $fallback) { $iverilog = Get-Item -LiteralPath $fallback }
}
if ($null -eq $iverilog) { throw 'iverilog.exe was not found. Install Icarus Verilog or add it to PATH.' }

$vvp = Get-Command vvp.exe -ErrorAction SilentlyContinue
if ($null -eq $vvp) {
  $fallback = Join-Path (Split-Path -Parent $iverilog.Source) 'vvp.exe'
  if (Test-Path -LiteralPath $fallback) { $vvp = Get-Item -LiteralPath $fallback }
}
if ($null -eq $vvp) { throw 'vvp.exe was not found next to iverilog.exe.' }

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
& $iverilog.Source -g2012 -s tb_hx30hm_protocol -o $output $package $testbench
if ($LASTEXITCODE -ne 0) { throw 'Icarus compile failed.' }
& $vvp.Source $output
if ($LASTEXITCODE -ne 0) { throw 'HX-30HM protocol simulation failed.' }
