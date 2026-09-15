#requires -Version 5.1

$ErrorActionPreference = 'Stop'

$sparrowRef = if ($env:SPARROW_REF) { $env:SPARROW_REF } else { 'main' }
$sparrowSource = "git+https://github.com/airshakur88/sparrow@$sparrowRef"

if ($args.Count -gt 0 -and $args[0] -in @('-h', '--help')) {
    Write-Output 'Update Sparrow with uv.'
    Write-Output 'Usage: irm https://raw.githubusercontent.com/airshakur88/sparrow/refs/heads/main/update.ps1 | iex'
    exit 0
}

if ($args.Count -gt 0) {
    throw "Unknown option: $($args[0])"
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $uvPath = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (Test-Path -LiteralPath $uvPath) {
        $uv = Get-Command $uvPath
    } else {
        $uv = Get-Command uv -ErrorAction SilentlyContinue
    }
}

if ($null -eq $uv) {
    throw 'uv was not found after installation.'
}

& $uv.Source tool install --python 3.11 --force $sparrowSource
$binPath = (& $uv.Source tool dir --bin).Trim()
$env:Path = "$binPath;$env:Path"
if (-not (Get-Command sparrow -ErrorAction SilentlyContinue)) {
    throw 'sparrow command was not found after update.'
}
Write-Output 'Sparrow updated from GitHub. User configuration and data were preserved.'
& sparrow --help | Out-Null
