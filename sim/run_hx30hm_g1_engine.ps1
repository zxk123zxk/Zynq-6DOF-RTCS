$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $repoRoot 'build\sim'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$iverilog = Get-Command iverilog.exe -ErrorAction Stop
$vvp = Get-Command vvp.exe -ErrorAction Stop
$rtl = @(
  (Join-Path $repoRoot 'src\pl\rtl\hx30hm_protocol_pkg.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\uart_byte_tx.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\uart_byte_rx.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\hx30hm_g1_engine.sv')
)
$output = Join-Path $buildDir 'tb_hx30hm_g1_engine.vvp'
& $iverilog.Source -g2012 -s tb_hx30hm_g1_engine -o $output @rtl (Join-Path $PSScriptRoot 'tb_hx30hm_g1_engine.sv')
if ($LASTEXITCODE -ne 0) { throw 'G1 engine compile failed' }
& $vvp.Source $output
if ($LASTEXITCODE -ne 0) { throw 'G1 engine simulation failed' }
