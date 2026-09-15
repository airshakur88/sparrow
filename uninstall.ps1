#requires -Version 5.1

$ErrorActionPreference = 'Stop'

if ($args.Count -gt 0 -and $args[0] -in @('-h', '--help')) {
    Write-Output 'Uninstall Sparrow installed with uv.'
    Write-Output 'Usage: irm https://raw.githubusercontent.com/airshakur88/sparrow/refs/heads/main/uninstall.ps1 | iex'
    exit 0
}

if ($args.Count -gt 0) {
    throw "Unknown option: $($args[0])"
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    $uvPath = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (Test-Path -LiteralPath $uvPath) {
        $uv = Get-Command $uvPath
    }
}

if ($null -eq $uv) {
    throw 'uv was not found. Sparrow may already be uninstalled.'
}

& $uv.Source tool uninstall sparrow
if ($LASTEXITCODE -ne 0) {
    throw 'uv could not uninstall Sparrow.'
}
Write-Output 'Sparrow uninstalled. User configuration and data were preserved.'
