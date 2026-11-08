param(
    [string]$Python = 'python',
    [string]$NvttSdk = $env:NVTT_SDK_DIR
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($NvttSdk)) {
    throw 'Specify -NvttSdk or set NVTT_SDK_DIR to the NVTT SDK directory.'
}
$sdkRoot = (Resolve-Path -LiteralPath $NvttSdk).Path
$environmentDir = Join-Path $projectRoot '.build-env'
$buildPython = Join-Path $environmentDir 'Scripts\python.exe'
if (!(Test-Path -LiteralPath $buildPython)) {
    & $Python -m venv $environmentDir
    if ($LASTEXITCODE -ne 0) { throw 'Creating packaging environment failed' }
}
$basePython = & $buildPython -I -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw 'Resolving base Python failed' }
$buildVariables = @('PATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML_IMPORT_PATH', 'QML2_IMPORT_PATH', 'PYTHONPATH', 'NVTT_SDK_DIR')
$originalEnvironment = @{}
foreach ($name in $buildVariables) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    # PyInstaller resolves native imports using PATH, independently of Python's -I.
    $env:PATH = @(
        (Join-Path $environmentDir 'Scripts'), $basePython,
        (Join-Path $basePython 'DLLs'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot
    ) -join [IO.Path]::PathSeparator
    foreach ($name in $buildVariables | Where-Object { $_ -notin @('PATH', 'NVTT_SDK_DIR') }) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $env:NVTT_SDK_DIR = $sdkRoot
    & $buildPython -I -m pip install -r (Join-Path $projectRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Installing build dependencies failed' }
    & $buildPython -I (Join-Path $projectRoot 'tools\prepare_licenses.py')
    if ($LASTEXITCODE -ne 0) { throw 'Collecting license texts failed' }
    & $buildPython -I -m PyInstaller --clean --noconfirm --distpath (Join-Path $projectRoot 'dist') --workpath (Join-Path $projectRoot 'build') (Join-Path $projectRoot 'Cubemap_IWI_Tool.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
}
finally {
    foreach ($name in $buildVariables) {
        [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], 'Process')
    }
}
$portable = Join-Path $projectRoot 'dist\Cubemap_IWI_Tool'
Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md') -Destination $portable
Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination $portable
Copy-Item -LiteralPath (Join-Path $projectRoot '使用说明.md') -Destination $portable
Copy-Item -LiteralPath (Join-Path $projectRoot 'UserGuide.md') -Destination $portable
Copy-Item -LiteralPath (Join-Path $projectRoot 'licenses') -Destination $portable -Recurse -Force
$figureDir = Join-Path $portable 'docs\figures'
New-Item -ItemType Directory -Path $figureDir -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'docs\figures') -File -Filter '*.png' |
    Copy-Item -Destination $figureDir
$archive = Join-Path $projectRoot 'dist\Cubemap_IWI_ToolV1.zip'
Compress-Archive -LiteralPath $portable -DestinationPath $archive -Force
Write-Host "Portable application: $portable\Cubemap_IWI_Tool.exe"
Write-Host "Portable archive: $archive"
