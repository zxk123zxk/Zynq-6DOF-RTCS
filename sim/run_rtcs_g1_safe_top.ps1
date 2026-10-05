$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $repoRoot 'build\sim'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$iverilog = Get-Command iverilog.exe -ErrorAction Stop
$vvp = Get-Command vvp.exe -ErrorAction Stop
$rtl = @(
  (Join-Path $repoRoot 'src\pl\rtl\rtcs_pkg.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\hx30hm_protocol_pkg.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\axi_lite_regs.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\uart_byte_tx.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\uart_byte_rx.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\hx30hm_g1_engine.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\servo_bus_master.sv'),
  (Join-Path $repoRoot 'src\pl\rtl\rtcs_top.sv')
)
$output = Join-Path $buildDir 'tb_rtcs_g1_safe_top.vvp'
& $iverilog.Source -g2012 -s tb_rtcs_g1_safe_top -o $output @rtl (Join-Path $PSScriptRoot 'tb_rtcs_g1_safe_top.sv')
if ($LASTEXITCODE -ne 0) { throw 'safe G1 top compile failed' }
& $vvp.Source $output
if ($LASTEXITCODE -ne 0) { throw 'safe G1 top simulation failed' }
