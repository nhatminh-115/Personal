$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $RepoRoot

$OutputDirectory = Join-Path $RepoRoot 'desktop\src-tauri\binaries'
$AlembicConfig = (Join-Path $RepoRoot 'alembic.ini') + ';.'
$Migrations = (Join-Path $RepoRoot 'migrations') + ';migrations'
$TempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$WorkDirectory = Join-Path $TempRoot 'aura-sidecar-pyinstaller'
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $WorkDirectory | Out-Null

$Arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean', '--onefile', '--noconsole',
    '--name', 'aura-api',
    '--distpath', $OutputDirectory,
    '--workpath', $WorkDirectory,
    '--specpath', $WorkDirectory,
    '--collect-all', 'app',
    '--collect-all', 'langgraph',
    '--collect-all', 'langchain_core',
    '--collect-all', 'langchain_openai',
    '--collect-all', 'sqlalchemy',
    '--collect-all', 'alembic',
    '--collect-all', 'asyncpg',
    '--collect-all', 'uvicorn',
    '--collect-submodules', 'mcp.client',
    '--collect-submodules', 'mcp.shared',
    '--collect-submodules', 'mcp.os',
    '--collect-all', 'pydantic',
    '--hidden-import', 'app.api.routes.desktop',
    '--hidden-import', 'desktop.data_backup',
    '--add-data', $AlembicConfig,
    '--add-data', $Migrations,
    'desktop\sidecar_entry.py'
)

python @Arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
