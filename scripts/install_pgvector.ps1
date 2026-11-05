#Requires -RunAsAdministrator
<#
  Installs pgvector 0.8.7 for PostgreSQL 18 on Windows (x64).
  Source: https://github.com/andreiramani/pgvector_pgsql_windows/releases/tag/0.8.7
#>
$ErrorActionPreference = "Stop"
$pgRoot = "C:\Program Files\PostgreSQL\18"
if (-not (Test-Path "$pgRoot\bin\postgres.exe")) {
    Write-Error "PostgreSQL 18 not found at $pgRoot. Edit `$pgRoot in this script if installed elsewhere."
}

$zip = Join-Path $env:TEMP "vector.v0.8.7-pg18.zip"
$extract = Join-Path $env:TEMP "vector-pg18-install"
$url = "https://github.com/andreiramani/pgvector_pgsql_windows/releases/download/0.8.7/vector.v0.8.7-pg18.zip"

Write-Host "Downloading pgvector for PostgreSQL 18..."
Invoke-WebRequest -Uri $url -OutFile $zip
if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $extract -Force

$service = Get-Service -Name "postgresql-x64-18" -ErrorAction SilentlyContinue
if ($service -and $service.Status -eq "Running") {
    Write-Host "Stopping PostgreSQL service..."
    Stop-Service -Name "postgresql-x64-18" -Force
    Start-Sleep -Seconds 2
}

Write-Host "Installing extension files into $pgRoot ..."
Copy-Item "$extract\lib\vector.dll" "$pgRoot\lib\" -Force
Copy-Item "$extract\share\extension\*" "$pgRoot\share\extension\" -Force

if ($service) {
    Write-Host "Starting PostgreSQL service..."
    Start-Service -Name "postgresql-x64-18"
}

Write-Host "Done. In psql or the app, run: CREATE EXTENSION vector;"
Write-Host "Verify: SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
