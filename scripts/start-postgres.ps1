# Starts the project's local PostgreSQL (api/var/pgdata) outside this terminal's process tree.
# See docs/local-setup-no-docker.md for why. Safe to run when it is already running.
$api = Join-Path (Split-Path -Parent $PSScriptRoot) 'api'
$pgctl = 'C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe'

& $pgctl status -D "$api\var\pgdata" *> $null
if ($LASTEXITCODE -eq 0) { Write-Output 'Postgres is already running.'; exit 0 }

$cmd = "`"$pgctl`" start -D `"$api\var\pgdata`" -l `"$api\var\postgres.log`" -o `"-c listen_addresses=localhost -c port=5432`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; CurrentDirectory = $api }
if ($r.ReturnValue -ne 0) { Write-Error "Could not start Postgres (code $($r.ReturnValue))"; exit 1 }
Write-Output 'Starting Postgres; it is ready when api\var\postgres.log says so.'
