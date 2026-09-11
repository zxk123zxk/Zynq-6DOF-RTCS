param(
  [Parameter(Mandatory = $true)]
  [string]$PetaLinuxProject
)

$source = Join-Path $PSScriptRoot '..\..\src\ps\linux\apps\rtcs_uart_smoke.c'
$source = [System.IO.Path]::GetFullPath($source)
$destination = Join-Path $PetaLinuxProject 'project-spec\meta-user\recipes-apps\rtcs-uart-smoke\files\rtcs_uart_smoke.c'

if (-not (Test-Path -LiteralPath $source)) { throw "Missing canonical app source: $source" }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $destination))) { throw "Missing PetaLinux recipe destination: $destination" }
Copy-Item -LiteralPath $source -Destination $destination -Force
Write-Output "Synchronized rtcs-uart-smoke source to $destination"
