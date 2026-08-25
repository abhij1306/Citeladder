param(
    [string[]] $ChangedFiles = @()
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot "validation.json") -Raw |
    ConvertFrom-Json -AsHashtable

# Deliberately fixed. Agents may narrow a retry to files changed after a failed
# run, but may not redefine the repository comparison base.
$baseRef = "origin/main"

function Invoke-Step {
    param([string] $Name, [scriptblock] $Command)

    Write-Host "`n==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE." }
}

function Get-BackendPython {
    foreach ($path in @("backend/.venv/Scripts/python.exe", "backend/.venv/bin/python")) {
        $candidate = Join-Path $repoRoot $path
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Backend virtual environment missing. Run 'uv sync --frozen --extra dev' in backend/."
}

function Invoke-BackendPython {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments)

    $python = Get-BackendPython
    Push-Location (Join-Path $repoRoot "backend")
    try { & $python @Arguments } finally { Pop-Location }
}

function Invoke-FrontendPnpm {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments)

    $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
    if (-not $pnpmCommand) {
        throw "pnpm missing from PATH. CiteLadder is pnpm-only; never substitute npm or yarn."
    }
    $invokeArguments = $Arguments
    if ($pnpmCommand.Path -and $pnpmCommand.Path.EndsWith(".cmd", "OrdinalIgnoreCase")) {
        # PowerShell invokes a .cmd shim through cmd.exe, which reparses
        # parentheses and other metacharacters in Next.js route-group paths.
        # Embedded quotes survive PowerShell and keep each argument intact for
        # the shim; native/PowerShell pnpm launchers must receive plain values.
        $invokeArguments = @(
            $Arguments | ForEach-Object {
                if ($_ -match '[&|<>()^]') { '"' + $_.Replace('"', '""') + '"' }
                else { $_ }
            }
        )
    }
    Push-Location (Join-Path $repoRoot "frontend")
    try { & $pnpmCommand.Path @invokeArguments } finally { Pop-Location }
}

function Invoke-GitPaths {
    param([string[]] $Arguments)

    $output = @(& git -C $repoRoot @Arguments 2>$null)
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed." }
    return @(
        $output |
            Where-Object { $_ } |
            ForEach-Object { $_.Replace("\", "/") }
    )
}

function Get-MergeBase {
    & git -C $repoRoot rev-parse --verify --quiet $baseRef *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Base ref '$baseRef' cannot be resolved. Run 'git fetch origin main'."
    }

    $output = @(& git -C $repoRoot merge-base $baseRef HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) {
        throw "Unable to determine merge base for '$baseRef'."
    }
    return [string] $output[0]
}

function Get-AllChangedPaths {
    param([string] $MergeBase)

    $paths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    function Add-Paths {
        param([string[]] $Arguments)

        foreach ($path in @(Invoke-GitPaths $Arguments)) { [void] $paths.Add($path) }
    }

    # A rename is a deletion plus an addition so the new path receives mapping.
    Add-Paths @("diff", "--no-renames", "--name-only", "--diff-filter=ACMDT", "$MergeBase..HEAD")
    Add-Paths @("diff", "--no-renames", "--name-only", "--diff-filter=ACMDT")
    Add-Paths @("diff", "--cached", "--no-renames", "--name-only", "--diff-filter=ACMDT")
    Add-Paths @("ls-files", "--others", "--exclude-standard")
    return @($paths | Sort-Object)
}

function Convert-ToRepositoryPath {
    param([string] $Path)

    $candidate = $Path.Trim().Trim('"').Replace("\", "/")
    if (-not $candidate) { throw "ChangedFiles contains an empty path." }

    $absolutePath = if ([IO.Path]::IsPathRooted($candidate)) {
        [IO.Path]::GetFullPath($candidate)
    }
    else {
        [IO.Path]::GetFullPath((Join-Path $repoRoot $candidate))
    }
    $relativePath = [IO.Path]::GetRelativePath($repoRoot, $absolutePath).Replace("\", "/")
    if ($relativePath -eq ".." -or $relativePath.StartsWith("../")) {
        throw "Changed file '$Path' is outside the repository."
    }
    return $relativePath
}

function Select-RequestedChangedPaths {
    param([string[]] $AllChangedPaths, [string[]] $RequestedPaths)

    if ($RequestedPaths.Count -eq 0) { return @($AllChangedPaths) }

    $available = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($path in $AllChangedPaths) { [void] $available.Add($path) }

    $selected = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($path in $RequestedPaths) {
        $repositoryPath = Convert-ToRepositoryPath $path
        if (-not $available.Contains($repositoryPath)) {
            throw "Changed file '$repositoryPath' is not in the current repository diff."
        }
        [void] $selected.Add($repositoryPath)
    }
    return @($selected | Sort-Object)
}

function Convert-GlobToRegex {
    param([string] $Pattern)

    $normalized = $Pattern.Replace("\", "/")
    $builder = [Text.StringBuilder]::new("^")
    $index = 0

    while ($index -lt $normalized.Length) {
        $character = $normalized[$index]
        if ($character -eq "*") {
            $isDoubleStar = (
                $index + 1 -lt $normalized.Length -and $normalized[$index + 1] -eq "*"
            )
            if ($isDoubleStar) {
                $followedBySlash = (
                    $index + 2 -lt $normalized.Length -and $normalized[$index + 2] -eq "/"
                )
                if ($followedBySlash) {
                    [void] $builder.Append("(?:.*/)?")
                    $index += 3
                }
                else {
                    [void] $builder.Append(".*")
                    $index += 2
                }
            }
            else {
                [void] $builder.Append("[^/]*")
                $index++
            }
            continue
        }

        if ($character -eq "?") { [void] $builder.Append("[^/]") }
        else { [void] $builder.Append([Regex]::Escape([string] $character)) }
        $index++
    }

    [void] $builder.Append("$")
    return $builder.ToString()
}

function Test-AnyPathMatches {
    param([string[]] $Paths, [string[]] $Patterns)

    foreach ($pattern in @($Patterns)) {
        $regex = Convert-GlobToRegex $pattern
        foreach ($path in @($Paths)) {
            if ($path -match $regex) { return $true }
        }
    }
    return $false
}

function Add-Patterns {
    param([Collections.Generic.HashSet[string]] $Target, $Patterns)

    foreach ($pattern in @($Patterns)) {
        if ($pattern) { [void] $Target.Add([string] $pattern) }
    }
}

function Resolve-TestPatterns {
    param([string] $Root, [string[]] $Patterns, [string[]] $Extensions)

    if ($Patterns.Count -eq 0) { return @() }
    if (-not (Get-Command rg -ErrorAction SilentlyContinue)) {
        throw "ripgrep ('rg') missing from PATH."
    }

    Push-Location $Root
    try { $files = @(& rg --files) } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Unable to enumerate test files under '$Root'." }
    $files = @(
        $files |
            ForEach-Object { $_.Replace("\", "/") } |
            Where-Object { [IO.Path]::GetExtension($_) -in $Extensions }
    )

    $selected = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($pattern in $Patterns) {
        $regex = Convert-GlobToRegex $pattern
        foreach ($file in $files) {
            if ($file -match $regex) { [void] $selected.Add($file) }
        }
    }
    return @($selected | Sort-Object)
}

function Select-ProductionPaths {
    param([string[]] $Paths, [string[]] $Roots, [string[]] $Extensions)

    # Tests colocate with the code they cover, so a changed test file lives under
    # a production root. It runs itself through the branch above and never needs
    # its own mapping entry.
    return @(
        $Paths | Where-Object {
            $path = $_
            $extension = [IO.Path]::GetExtension($path)
            ($extension -in $Extensions) -and
            ($path -notmatch '\.(test|spec)\.(ts|tsx|js|jsx|mjs)$') -and
            ($path -notmatch '(^|/)tests?/') -and
            (@($Roots | Where-Object { $path.StartsWith("$_/", "OrdinalIgnoreCase") }).Count -gt 0)
        }
    )
}

$mergeBase = Get-MergeBase
$allChangedPaths = @(Get-AllChangedPaths $mergeBase)
$changedPaths = @(Select-RequestedChangedPaths $allChangedPaths $ChangedFiles)

if ($changedPaths.Count -eq 0) {
    Write-Host "No changed paths selected." -ForegroundColor Green
    exit 0
}

$mode = if ($ChangedFiles.Count -gt 0) { "retry delta" } else { "full working diff" }
Write-Host "Selecting tests for $($changedPaths.Count) path(s) from $mode." -ForegroundColor Cyan

$backendPatterns = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$frontendPatterns = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$e2ePatterns = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$mappedBackendPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$mappedFrontendPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

$backendSourcePaths = @(
    Select-ProductionPaths $changedPaths @($config.backendRoots) @($config.backendExtensions)
)
$frontendSourcePaths = @(
    Select-ProductionPaths $changedPaths @($config.frontendRoots) @($config.frontendExtensions)
)

# A changed test always runs itself.
foreach ($path in $changedPaths) {
    $exists = Test-Path -LiteralPath (Join-Path $repoRoot $path)
    if (-not $exists) { continue }
    if ($path -match '^backend/tests/(?:.+/)?test_[^/]+\.py$') {
        Add-Patterns $backendPatterns @($path.Substring("backend/".Length))
    }
    elseif ($path -match '^frontend/e2e/.+\.spec\.(ts|tsx|js|jsx|mjs)$') {
        Add-Patterns $e2ePatterns @($path.Substring("frontend/".Length))
    }
    elseif ($path -match '^frontend/.+\.(test|spec)\.(ts|tsx|js|jsx|mjs)$') {
        Add-Patterns $frontendPatterns @($path.Substring("frontend/".Length))
    }
}

# Rules are additive. Each production path must have an explicit mapping.
foreach ($rule in $config.rules) {
    $matchingPaths = @($changedPaths | Where-Object { Test-AnyPathMatches @($_) @($rule.sources) })
    if ($matchingPaths.Count -eq 0) { continue }

    if ($rule.backendTests) {
        Add-Patterns $backendPatterns $rule.backendTests
        foreach ($path in $backendSourcePaths) {
            if (Test-AnyPathMatches @($path) @($rule.sources)) {
                [void] $mappedBackendPaths.Add($path)
            }
        }
    }
    if ($rule.frontendTests) { Add-Patterns $frontendPatterns $rule.frontendTests }
    if ($rule.frontendE2E) { Add-Patterns $e2ePatterns $rule.frontendE2E }
    if ($rule.frontendTests -or $rule.frontendE2E) {
        foreach ($path in $frontendSourcePaths) {
            if (Test-AnyPathMatches @($path) @($rule.sources)) {
                [void] $mappedFrontendPaths.Add($path)
            }
        }
    }
}

$unmappedPaths = @(
    $backendSourcePaths | Where-Object { -not $mappedBackendPaths.Contains($_) }
    $frontendSourcePaths | Where-Object { -not $mappedFrontendPaths.Contains($_) }
)
if ($unmappedPaths.Count -gt 0) {
    $formatted = $unmappedPaths | Sort-Object | ForEach-Object { " - $_" }
    throw "Production files lack test mappings in scripts/validation.json:`n$($formatted -join "`n")"
}

$backendTests = @(Resolve-TestPatterns (Join-Path $repoRoot "backend") @($backendPatterns) @(".py"))
# `.mjs` is a frontend production extension (validation.json) and
# Select-ProductionPaths already treats `.test.mjs` / `.spec.mjs` as tests, so
# it has to be resolvable here too — otherwise such a test is excluded from the
# unmapped-production check AND impossible to select, i.e. silently unrunnable.
$frontendTestExtensions = @(".ts", ".tsx", ".js", ".jsx", ".mjs")
$frontendTests = @(
    Resolve-TestPatterns `
        (Join-Path $repoRoot "frontend") `
        @($frontendPatterns) `
        $frontendTestExtensions
)
$frontendE2E = @(
    Resolve-TestPatterns `
        (Join-Path $repoRoot "frontend") `
        @($e2ePatterns) `
        $frontendTestExtensions
)

if ($backendSourcePaths.Count -gt 0 -and $backendTests.Count -eq 0) {
    throw "Backend mappings resolved to zero runnable tests. Fix scripts/validation.json."
}
if ($frontendSourcePaths.Count -gt 0 -and ($frontendTests.Count + $frontendE2E.Count) -eq 0) {
    throw "Frontend mappings resolved to zero runnable tests. Fix scripts/validation.json."
}

Write-Host (
    "Selected $($backendTests.Count) backend, " +
    "$($frontendTests.Count) frontend, and $($frontendE2E.Count) E2E test file(s)."
) -ForegroundColor Cyan

if ($backendTests.Count -eq 0 -and $frontendTests.Count -eq 0 -and $frontendE2E.Count -eq 0) {
    Write-Host "No tests mapped for these non-production changes." -ForegroundColor Green
    exit 0
}

if ($backendTests.Count -gt 0) {
    # Coverage is a whole-suite floor and is measured by CI, never by this
    # affected-subset selector.
    Invoke-Step "Affected backend tests" {
        Invoke-BackendPython -m pytest @backendTests -q --no-cov
    }
}
if ($frontendTests.Count -gt 0) {
    Invoke-Step "Affected frontend tests" { Invoke-FrontendPnpm exec vitest run @frontendTests }
}
if ($frontendE2E.Count -gt 0) {
    Invoke-Step "Affected frontend E2E" {
        Invoke-FrontendPnpm exec playwright test --config playwright.config.ts @frontendE2E
    }
}

Write-Host "`nAffected tests passed." -ForegroundColor Green
