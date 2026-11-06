[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PostInstallArguments
)

$ErrorActionPreference = "Stop"
$launcher = Join-Path $PSScriptRoot "post-install.py"
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue

if ($pyLauncher) {
    & $pyLauncher.Source -3 $launcher @PostInstallArguments
}
else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python 3.11 or newer is required. Neither 'py' nor 'python' was found."
    }
    & $python.Source $launcher @PostInstallArguments
}

exit $LASTEXITCODE
