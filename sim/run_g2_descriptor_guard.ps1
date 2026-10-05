$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $repoRoot 'build\sim'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$iverilog = Get-Command iverilog.exe -ErrorAction Stop
$vvp = Get-Command vvp.exe -ErrorAction Stop
$output = Join-Path $buildDir 'tb_g2_descriptor_guard.vvp'
& $iverilog.Source -g2012 -s tb_g2_descriptor_guard -o $output `
  (Join-Path $repoRoot 'src\pl\rtl\g2_descriptor_guard.sv') `
  (Join-Path $PSScriptRoot 'tb_g2_descriptor_guard.sv')
if ($LASTEXITCODE -ne 0) { throw 'G2 descriptor guard compile failed' }
& $vvp.Source $output
if ($LASTEXITCODE -ne 0) { throw 'G2 descriptor guard simulation failed' }
