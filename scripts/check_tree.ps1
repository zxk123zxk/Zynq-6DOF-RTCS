$required = @(
  'README.md',
  'docs/hardware_bringup.md',
  'docs/0.G0-ps-pl-foundation.md',
  'docs/1.G1-single-servo-protocol.md',
  'docs/2.G2-six-axis-calibration.md',
  'docs/3.G3-static-closed-loop.md',
  'docs/4.G4-dynamic-demo.md',
  'skill/README.md',
  'src/pl/rtl/rtcs_top.sv',
  'src/ps/linux/CMakeLists.txt',
  'sim/README.md'
)

$missing = $required | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) {
  $missing | ForEach-Object { Write-Error "Missing required artifact: $_" }
  exit 1
}

Write-Output 'Repository skeleton check passed.'
