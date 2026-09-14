#requires -Version 5.1

$ErrorActionPreference = 'Stop'

if ($args.Count -gt 0 -and $args[0] -in @('-h', '--help')) {
    Write-Output 'Install Sparrow with uv.'
    Write-Output 'Usage: irm https://raw.githubusercontent.com/airshakur88/sparrow/refs/heads/main/install.ps1 | iex'
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

& $uv.Source tool install --python 3.11 --force sparrow
Write-Output 'Sparrow installed. Open a new PowerShell session if sparrow is not on PATH yet.'
& $uv.Source tool run --from sparrow sparrow --version
