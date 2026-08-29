param(
    [ValidateSet("All", "Backend", "Frontend", "Docs")]
    [string] $Scope = "All",
    [switch] $CheckOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

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

function Get-BackendTool {
    param([string] $Name)

    foreach ($path in @("backend/.venv/Scripts/$Name.exe", "backend/.venv/bin/$Name")) {
        $candidate = Join-Path $repoRoot $path
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "Backend tool '$Name' missing. Run 'uv sync --frozen --extra dev' in backend/."
}

function Invoke-BackendPython {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments)

    $python = Get-BackendPython
    Push-Location (Join-Path $repoRoot "backend")
    try { & $python @Arguments } finally { Pop-Location }
}

function Invoke-BackendTool {
    param(
        [Parameter(Mandatory = $true)] [string] $Name,
        [Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments
    )

    $tool = Get-BackendTool $Name
    Push-Location (Join-Path $repoRoot "backend")
    try { & $tool @Arguments } finally { Pop-Location }
}

function Invoke-FrontendPnpm {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments)

    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
        throw "pnpm missing from PATH. CiteLadder is pnpm-only; never substitute npm or yarn."
    }
    Push-Location (Join-Path $repoRoot "frontend")
    try { & pnpm @Arguments } finally { Pop-Location }
}

function Invoke-BackendChecks {
    # `.` is the backend tree. The two Python files ABOVE it were linted by
    # nothing at all, so they are passed explicitly with the backend config;
    # ruff would otherwise fall back to its defaults for them, there being no
    # pyproject.toml at the repository root. Keep in step with ci.yml.
    $rootScripts = @("--config", "pyproject.toml", "../reset-db.py", "../docs/validate_documentation.py")
    if ($CheckOnly) {
        Invoke-Step "Ruff lint" { Invoke-BackendTool ruff check . @rootScripts }
        Invoke-Step "Ruff format" { Invoke-BackendTool ruff format --check . @rootScripts }
    }
    else {
        Invoke-Step "Ruff lint fixes" { Invoke-BackendTool ruff check . --fix @rootScripts }
        Invoke-Step "Ruff format fixes" { Invoke-BackendTool ruff format . @rootScripts }
    }
    Invoke-Step "Mypy" { Invoke-BackendTool mypy }
    # Fixed CC/LOC ceilings plus named exceptions. There is deliberately no
    # baseline-rewrite command: a regression fails here instead of becoming budget.
    Invoke-Step "Complexity policy" { Invoke-BackendPython -m scripts.check_complexity }
    # Layer contracts (backend/.importlinter): the backend equivalent of the
    # frontend's design-system/architecture policy.
    Invoke-Step "Architecture policy" { Invoke-BackendTool lint-imports }
    Invoke-Step "Dead-code policy" { Invoke-BackendTool vulture app evaluations scripts --min-confidence 80 }
    # Declared-but-unused, used-but-undeclared, transitively-relied-upon deps.
    Invoke-Step "Dependency hygiene" { Invoke-BackendTool deptry . }
}

function Invoke-FrontendChecks {
    if ($CheckOnly) {
        Invoke-Step "Prettier format" { Invoke-FrontendPnpm format:check }
    }
    else {
        Invoke-Step "Prettier format fixes" { Invoke-FrontendPnpm format }
    }
    Invoke-Step "ESLint" { Invoke-FrontendPnpm lint }
    Invoke-Step "TypeScript" { Invoke-FrontendPnpm exec tsc --noEmit }
    Invoke-Step "Frontend complexity policy" { Invoke-FrontendPnpm check:complexity }
    Invoke-Step "Duplication policy" { Invoke-FrontendPnpm check:duplicates }
    Invoke-Step "Design-system and architecture policy" { Invoke-FrontendPnpm check:policy }
    Invoke-Step "API contract policy" { Invoke-FrontendPnpm check:contract }
}

function Invoke-DocsChecks {
    Invoke-Step "Documentation index" {
        $python = Get-BackendPython
        Push-Location $repoRoot
        try { & $python docs/validate_documentation.py } finally { Pop-Location }
    }
}

if ($Scope -in @("All", "Backend")) { Invoke-BackendChecks }
if ($Scope -in @("All", "Frontend")) { Invoke-FrontendChecks }
if ($Scope -in @("All", "Docs")) { Invoke-DocsChecks }

Write-Host "`n$Scope static validation passed." -ForegroundColor Green
