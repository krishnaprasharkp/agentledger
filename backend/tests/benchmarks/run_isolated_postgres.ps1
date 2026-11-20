param(
    [string]$Docker = "docker",
    [string]$Python = "",
    [int]$Samples = 200,
    [int]$Warmup = 20
)
$ErrorActionPreference = 'Stop'
if (!$Python) { $Python = Join-Path $PSScriptRoot '../../.venv/Scripts/python.exe' }
$suffix = [Guid]::NewGuid().ToString('N').Substring(0, 12)
$name = "agentledger-bench-$suffix"
$database = "agentledger_bench_$suffix"
$secret = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
$oldPassword = $env:POSTGRES_PASSWORD
$oldBenchmarkUrl = $env:BENCHMARK_DATABASE_URL
$containerCreated = $false
try {
    $env:POSTGRES_PASSWORD = $secret
    $container = & $Docker run --rm -d --name $name --label agentledger.purpose=isolated-benchmark --tmpfs '/var/lib/postgresql/data' -p '127.0.0.1::5432' -e POSTGRES_PASSWORD -e "POSTGRES_DB=$database" postgres:17
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the disposable PostgreSQL container.' }
    $containerCreated = $true
    $binding = & $Docker port $container 5432/tcp
    if ($binding -notmatch '^127\.0\.0\.1:(\d+)$') { throw 'Unexpected benchmark port binding.' }
    $port = $Matches[1]
    $env:BENCHMARK_DATABASE_URL = "postgresql+psycopg://postgres:${secret}@127.0.0.1:${port}/$database"
    $ready = $false
    for ($i=0; $i -lt 40; $i++) {
        & $Docker exec $container pg_isready -h 127.0.0.1 -U postgres -d $database -q
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Milliseconds 250
    }
    if (!$ready) { throw 'The disposable database did not become ready.' }
    $dockerInfo = & $Docker info --format '{{.OperatingSystem}}|{{.KernelVersion}}|{{.NCPU}}|{{.MemTotal}}|{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw 'Could not read Docker execution environment.' }
    $dockerInfo | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'docker_environment.txt') -Encoding UTF8
    & $Python (Join-Path $PSScriptRoot 'postgres_queries.py') --samples $Samples --warmup $Warmup --output (Join-Path $PSScriptRoot 'postgres_results.json')
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL benchmark failed.' }
} finally {
    if ($containerCreated) {
        & $Docker stop $container | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Warning "Could not stop the isolated benchmark container $name." }
    }
    $env:POSTGRES_PASSWORD = $oldPassword
    $env:BENCHMARK_DATABASE_URL = $oldBenchmarkUrl
}
