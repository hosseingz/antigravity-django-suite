#Requires -Version 5.1
<#
.SYNOPSIS
    Install (or remove) the suite role catalog in a target project without
    touching any file this catalog does not own.

.DESCRIPTION
    Copies roles\suite-*.md to <Target>\.agents\agents\ and records ownership
    (file name + sha256) in <Target>\.agents\suite-install-state.json.

    Safety contract:
      * writes only .agents\agents\suite-*.md and the ownership file
      * never writes .agent\, .agents\skills\, .agents\rules\, .agents\workflows\
      * never overwrites a foreign file, or a file the user modified locally,
        unless -Force is passed
      * refuses to install into the suite source repository itself (unless -Force)

.PARAMETER Target
    Path to the application repository. Defaults to the current directory.

.PARAMETER Only
    One or more role names to install (with or without the "suite-" prefix).

.PARAMETER DryRun
    Print the plan without writing anything.

.PARAMETER Force
    Allow overwriting foreign or locally modified files, and allow installing
    into the suite source repository.

.PARAMETER Uninstall
    Remove only files recorded in the ownership file and unchanged since install.

.PARAMETER List
    List the catalog and what is installed in Target.

.EXAMPLE
    pwsh ./scripts/install-roles.ps1 -Target C:\src\myapp -DryRun

.EXAMPLE
    pwsh ./scripts/install-roles.ps1 -Target C:\src\myapp -Only suite-auth-security-reviewer

.EXAMPLE
    pwsh ./scripts/install-roles.ps1 -Target C:\src\myapp -Uninstall
#>
[CmdletBinding()]
param(
    [string]$Target = (Get-Location).Path,
    [string[]]$Only,
    [switch]$DryRun,
    [switch]$Force,
    [switch]$Uninstall,
    [switch]$List
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$prefix        = 'suite-'
$sourceDir     = Join-Path (Split-Path -Parent $PSScriptRoot) 'roles'
$relativeAgents = '.agents\agents'
$relativeState  = '.agents\suite-install-state.json'

if (-not (Test-Path -LiteralPath $sourceDir)) {
    throw "Role source directory not found: $sourceDir"
}

function Get-Sha256([string]$path) {
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
}

function Read-State([string]$statePath) {
    if (-not (Test-Path -LiteralPath $statePath)) { return @() }
    $raw = Get-Content -LiteralPath $statePath -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) { return @() }
    $parsed = $raw | ConvertFrom-Json
    if ($null -eq $parsed) { return @() }
    if ($parsed.PSObject.Properties.Name -notcontains 'installed') { return @() }
    return @($parsed.installed)
}

function Write-State([string]$statePath, [object[]]$entries, [string]$version) {
    $payload = [ordered]@{
        version   = $version
        installed = @($entries)
    }
    $json = $payload | ConvertTo-Json -Depth 6
    $parent = Split-Path -Parent $statePath
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    # UTF-8 without BOM: BOM breaks strict JSON parsers (Node's JSON.parse, many CI checks).
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($statePath, $json, $utf8NoBom)
}

function Get-CatalogVersion {
    $registry = Join-Path $sourceDir 'registry.json'
    if (-not (Test-Path -LiteralPath $registry)) { return '0.0.0' }
    try {
        $parsed = Get-Content -LiteralPath $registry -Raw | ConvertFrom-Json
        if ($parsed.PSObject.Properties.Name -contains 'version') { return [string]$parsed.version }
    } catch {
        Write-Warning "Could not read registry.json version: $($_.Exception.Message)"
    }
    return '0.0.0'
}

# ---------------------------------------------------------------- catalog ---
$catalog = @(Get-ChildItem -LiteralPath $sourceDir -Filter "$prefix*.md" -File | Sort-Object Name)

if ($List) {
    Write-Host "Catalog ($($catalog.Count) roles) from $sourceDir"
    foreach ($file in $catalog) {
        Write-Host ("  " + $file.Name)
    }
    $statePath = Join-Path $Target $relativeState
    $installed = @(Read-State $statePath)
    Write-Host ""
    Write-Host "Installed in $Target : $($installed.Count)"
    foreach ($entry in $installed) {
        Write-Host ("  " + $entry.file + "  sha256=" + $entry.sha256)
    }
    exit 0
}

# ----------------------------------------------------------------- target ---
if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
    throw "Target directory does not exist: $Target"
}
$targetRoot = (Resolve-Path -LiteralPath $Target).Path
$agentsDir  = Join-Path $targetRoot $relativeAgents
$statePath  = Join-Path $targetRoot $relativeState
$version    = Get-CatalogVersion
$installed  = @(Read-State $statePath)

$isSourceRepo = Test-Path -LiteralPath (Join-Path $targetRoot 'roles\registry.json')
if ($isSourceRepo -and -not $Force) {
    throw "Refusing to install into the suite source repository ($targetRoot). Roles belong in an application repository. Pass -Force only if you really mean it."
}

$selected = $catalog
if ($Only -and $Only.Count -gt 0) {
    $wanted = @()
    foreach ($name in $Only) {
        $clean = $name.Trim()
        if ($clean.EndsWith('.md')) { $clean = $clean.Substring(0, $clean.Length - 3) }
        if (-not $clean.StartsWith($prefix)) { $clean = $prefix + $clean }
        $wanted += $clean
    }
    $selected = @($catalog | Where-Object { $wanted -contains $_.BaseName })
    $missing = @($wanted | Where-Object { $selected.BaseName -notcontains $_ })
    if ($missing.Count -gt 0) {
        throw "Unknown role(s): $($missing -join ', ')"
    }
}

# -------------------------------------------------------------- uninstall ---
if ($Uninstall) {
    if ($installed.Count -eq 0) {
        Write-Host "Nothing recorded as installed in $targetRoot"
        exit 0
    }
    $remaining = @()
    $kept = 0
    $removed = 0
    foreach ($entry in $installed) {
        $path = Join-Path $agentsDir $entry.file
        if (-not (Test-Path -LiteralPath $path)) {
            Write-Host ("[SKIP] " + $entry.file + " (already missing)")
            continue
        }
        $current = Get-Sha256 $path
        if ($current -ne $entry.sha256 -and -not $Force) {
            Write-Warning ("Keeping " + $entry.file + ": modified locally since install (use -Force to remove)")
            $remaining += $entry
            $kept++
            continue
        }
        if (-not $DryRun) { Remove-Item -LiteralPath $path -Force }
        Write-Host ("[REMOVED] " + $entry.file)
        $removed++
    }
    if (-not $DryRun) {
        if ($remaining.Count -gt 0) {
            Write-State -statePath $statePath -entries @($remaining) -version $version
        } elseif (Test-Path -LiteralPath $statePath) {
            Remove-Item -LiteralPath $statePath -Force
        }
    }
    Write-Host ""
    Write-Host "Uninstall summary: removed=$removed kept=$kept dry-run=$($DryRun.IsPresent)"
    exit 0
}

# ---------------------------------------------------------------- install ---
if (-not $DryRun -and -not (Test-Path -LiteralPath $agentsDir)) {
    New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null
}

$copied = 0
$skipped = 0
$uptodate = 0
$newState = @()
$now = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')

foreach ($file in $selected) {
    $source = $file.FullName
    $dest   = Join-Path $agentsDir $file.Name
    $owned  = @($installed | Where-Object { $_.file -eq $file.Name })
    $sourceHash = Get-Sha256 $source

    if (-not (Test-Path -LiteralPath $dest)) {
        if ($DryRun) {
            Write-Host ("[DRYRUN] would add    " + $file.Name)
        } else {
            Copy-Item -LiteralPath $source -Destination $dest -Force
            Write-Host ("[ADDED]   " + $file.Name)
        }
        $copied++
        $newState += [pscustomobject]@{ file = $file.Name; sha256 = $sourceHash; installed_at = $now; source_version = $version }
        continue
    }

    $destHash = Get-Sha256 $dest
    if ($owned.Count -eq 0 -and -not $Force) {
        Write-Warning ("Skipping " + $file.Name + ": file exists but is not owned by this catalog (foreign file). Use -Force to overwrite.")
        $skipped++
        continue
    }
    if ($owned.Count -gt 0 -and $destHash -ne $owned[0].sha256 -and -not $Force) {
        Write-Warning ("Skipping " + $file.Name + ": modified locally since install. Use -Force to overwrite.")
        $skipped++
        $newState += $owned[0]
        continue
    }
    if ($destHash -eq $sourceHash) {
        Write-Host ("[OK]      " + $file.Name + " (unchanged)")
        $uptodate++
        $newState += [pscustomobject]@{ file = $file.Name; sha256 = $sourceHash; installed_at = $owned[0].installed_at; source_version = $version }
        continue
    }

    if ($DryRun) {
        Write-Host ("[DRYRUN] would update " + $file.Name)
    } else {
        Copy-Item -LiteralPath $source -Destination $dest -Force
        Write-Host ("[UPDATED] " + $file.Name)
    }
    $copied++
    $newState += [pscustomobject]@{ file = $file.Name; sha256 = $sourceHash; installed_at = $now; source_version = $version }
}

# Preserve ownership of files that exist but were not selected this run
foreach ($entry in $installed) {
    if ($newState.file -notcontains $entry.file) {
        $path = Join-Path $agentsDir $entry.file
        if (Test-Path -LiteralPath $path) { $newState += $entry }
    }
}

if (-not $DryRun) {
    Write-State -statePath $statePath -entries @($newState) -version $version
}

Write-Host ""
Write-Host "Install summary: added/updated=$copied unchanged=$uptodate skipped=$skipped dry-run=$($DryRun.IsPresent)"
Write-Host "Target:  $agentsDir"
Write-Host "State:   $statePath"
Write-Host "Next:    open the project in Antigravity, start a new conversation, and activate a role by exact name."
exit 0
