$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $repoRoot 'build\sim'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

$iverilog = Get-Command iverilog.exe -ErrorAction SilentlyContinue
if ($null -eq $iverilog) {
  $fallback = 'D:\3.Electronic_Information\iverilog\bin\iverilog.exe'
  if (Test-Path -LiteralPath $fallback) { $iverilog = Get-Item -LiteralPath $fallback }
}
$vvp = Get-Command vvp.exe -ErrorAction SilentlyContinue
if ($null -eq $vvp) {
  $fallback = 'D:\3.Electronic_Information\iverilog\bin\vvp.exe'
  if (Test-Path -LiteralPath $fallback) { $vvp = Get-Item -LiteralPath $fallback }
}
if ($null -eq $iverilog -or $null -eq $vvp) { throw 'iverilog/vvp not found (PATH or D:\3.Electronic_Information\iverilog\bin)' }

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
$output = Join-Path $buildDir 'tb_rtcs_g2_one_servo.vvp'
& $iverilog.Source -g2012 -s tb_rtcs_g2_one_servo -o $output @rtl (Join-Path $PSScriptRoot 'tb_rtcs_g2_one_servo.sv')
if ($LASTEXITCODE -ne 0) { throw 'G2 one-servo compile failed' }
& $vvp.Source $output
if ($LASTEXITCODE -ne 0) { throw 'G2 one-servo simulation failed' }
