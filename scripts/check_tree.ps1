$required = @(
  'README.md',
  'docs/architecture.md',
  'docs/register_map.md',
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
