param(
    [ValidateSet("All", "Backend", "Frontend", "Docs", "Contract")]
    [string] $Scope = "All",
    [switch] $CheckOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$mode = if ($CheckOnly) { "check" } else { "fix" }

Push-Location $repoRoot
try {
    & node scripts/quality.mjs --mode $mode --scope $Scope.ToLowerInvariant()
    if ($LASTEXITCODE -ne 0) { throw "Quality gate failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
