#Requires -Version 5.1
<#
.SYNOPSIS
    Installs (or uninstalls) the entire Antigravity Django Suite (Roles, Skills, Rules, Workflows)
    into a target application project.

.DESCRIPTION
    Deploys the complete suite to the target repository:
      - Roles:     roles\suite-*.md            -> <Target>\.agents\agents\
      - Skills:    skills\*                     -> <Target>\.agents\skills\*
      - Rules:     .agent\rules\*              -> <Target>\.agents\rules\*
      - Workflows: workflows\*                 -> <Target>\.agents\workflows\*

    Ownership and file hashes (SHA256) are recorded in <Target>\.agents\suite-install-state.json
    to allow safe, idempotent updates and clean uninstallation without touching foreign files.

.PARAMETER Target
    Path to the application repository. Defaults to the current directory.

.PARAMETER DryRun
    Print the planned installation/uninstallation actions without writing or deleting anything.

.PARAMETER Force
    Allow overwriting foreign or locally modified files, and allow installing into the suite source repository.

.PARAMETER Uninstall
    Remove all installed suite files that have not been modified locally.

.PARAMETER List
    List catalog assets and what is currently installed in the target repository.

.EXAMPLE
    pwsh ./scripts/install-suite.ps1 -Target "D:\Projects\graviblog" -DryRun

.EXAMPLE
    pwsh ./scripts/install-suite.ps1 -Target "D:\Projects\graviblog"

.EXAMPLE
    pwsh ./scripts/install-suite.ps1 -Target "D:\Projects\graviblog" -Uninstall
#>
[CmdletBinding()]
param(
    [string]$Target = (Get-Location).Path,
    [switch]$DryRun,
    [switch]$Force,
    [switch]$Uninstall,
    [switch]$List
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$suiteRoot     = Split-Path -Parent $PSScriptRoot
$rolesDir      = Join-Path $suiteRoot 'roles'
$skillsDir     = Join-Path $suiteRoot 'skills'
$rulesDir      = Join-Path $suiteRoot '.agent\rules'
$workflowsDir  = Join-Path $suiteRoot 'workflows'
$relativeState = '.agents\suite-install-state.json'

function Get-Sha256([string]$filePath) {
    return (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash
}

function Read-State([string]$statePath) {
    if (-not (Test-Path -LiteralPath $statePath)) { return @() }
    $raw = Get-Content -LiteralPath $statePath -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) { return @() }
    try {
        $parsed = $raw | ConvertFrom-Json
        if ($null -eq $parsed) { return @() }
        if ($parsed.PSObject.Properties.Name -notcontains 'installed') { return @() }
        return @($parsed.installed)
    } catch {
        Write-Warning "Could not parse state file: $($_.Exception.Message)"
        return @()
    }
}

function Write-State([string]$statePath, [object[]]$entries, [string]$version) {
    $payload = [ordered]@{
        version      = $version
        last_updated = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
        installed    = @($entries)
    }
    $json = $payload | ConvertTo-Json -Depth 6
    $parent = Split-Path -Parent $statePath
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($statePath, $json, $utf8NoBom)
}

function Get-SuiteVersion {
    $registry = Join-Path $rolesDir 'registry.json'
    if (Test-Path -LiteralPath $registry) {
        try {
            $parsed = Get-Content -LiteralPath $registry -Raw | ConvertFrom-Json
            if ($parsed.PSObject.Properties.Name -contains 'version') {
                return [string]$parsed.version
            }
        } catch {}
    }
    return '1.0.0'
}

# Collect all files to be deployed: array of PSCustomObject with RelPath & SourcePath
function Get-CatalogFiles {
    $items = [System.Collections.Generic.List[PSCustomObject]]::new()

    # 1. Roles (suite-*.md) -> .agents/agents/
    if (Test-Path -LiteralPath $rolesDir) {
        $roles = Get-ChildItem -LiteralPath $rolesDir -Filter "suite-*.md" -File
        foreach ($f in $roles) {
            $items.Add([PSCustomObject]@{
                Category   = 'roles'
                RelPath    = ".agents\agents\$($f.Name)"
                SourcePath = $f.FullName
            })
        }
    }

    # 2. Skills (all contents) -> .agents/skills/
    if (Test-Path -LiteralPath $skillsDir) {
        $skills = Get-ChildItem -LiteralPath $skillsDir -Recurse -File
        foreach ($f in $skills) {
            $relative = $f.FullName.Substring($skillsDir.Length).TrimStart('\', '/')
            $items.Add([PSCustomObject]@{
                Category   = 'skills'
                RelPath    = ".agents\skills\$relative"
                SourcePath = $f.FullName
            })
        }
    }

    # 3. Rules -> .agents/rules/
    if (Test-Path -LiteralPath $rulesDir) {
        $rules = Get-ChildItem -LiteralPath $rulesDir -Filter "*.md" -File
        foreach ($f in $rules) {
            $items.Add([PSCustomObject]@{
                Category   = 'rules'
                RelPath    = ".agents\rules\$($f.Name)"
                SourcePath = $f.FullName
            })
        }
    }

    # 4. Workflows -> .agents/workflows/
    if (Test-Path -LiteralPath $workflowsDir) {
        $workflows = Get-ChildItem -LiteralPath $workflowsDir -Recurse -File
        foreach ($f in $workflows) {
            $relative = $f.FullName.Substring($workflowsDir.Length).TrimStart('\', '/')
            $items.Add([PSCustomObject]@{
                Category   = 'workflows'
                RelPath    = ".agents\workflows\$relative"
                SourcePath = $f.FullName
            })
        }
    }

    return $items.ToArray()
}

$catalog = Get-CatalogFiles
$version = Get-SuiteVersion

if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
    throw "Target directory does not exist: $Target"
}
$targetRoot = (Resolve-Path -LiteralPath $Target).Path
$statePath  = Join-Path $targetRoot $relativeState
$installed  = @(Read-State $statePath)

# --- LIST ACTION ---
if ($List) {
    Write-Host "Antigravity Django Suite - Catalog Assets (Version $version)" -ForegroundColor Cyan
    Write-Host "Total catalog files: $($catalog.Count)"
    $grouped = $catalog | Group-Object Category
    foreach ($g in $grouped) {
        Write-Host "  [$($g.Name)]: $($g.Count) files"
    }
    Write-Host ""
    Write-Host "Target: $targetRoot"
    Write-Host "Installed files according to state: $($installed.Count)"
    exit 0
}

# Safety check: Prevent accidental self-installation
$isSourceRepo = (Test-Path -LiteralPath (Join-Path $targetRoot 'roles\registry.json')) -and
                (Test-Path -LiteralPath (Join-Path $targetRoot 'scripts\install-suite.ps1'))
if ($isSourceRepo -and -not $Force) {
    throw "Refusing to install into the suite source repository ($targetRoot). Pass -Force if you really intend this."
}

# --- UNINSTALL ACTION ---
if ($Uninstall) {
    Write-Host "Starting uninstallation from $targetRoot..." -ForegroundColor Yellow
    if ($installed.Count -eq 0) {
        Write-Host "No installed assets recorded in $statePath."
        exit 0
    }

    $remaining = [System.Collections.Generic.List[PSCustomObject]]::new()
    $removed = 0
    $kept = 0

    foreach ($entry in $installed) {
        $destPath = Join-Path $targetRoot $entry.file
        if (-not (Test-Path -LiteralPath $destPath)) {
            Write-Host "[SKIP] $($entry.file) (already missing)" -ForegroundColor DarkGray
            continue
        }

        $currentHash = Get-Sha256 $destPath
        if ($currentHash -ne $entry.sha256 -and -not $Force) {
            Write-Warning "Keeping $($entry.file): modified locally since install (use -Force to delete)."
            $remaining.Add($entry)
            $kept++
            continue
        }

        if (-not $DryRun) {
            Remove-Item -LiteralPath $destPath -Force
        }
        Write-Host "[REMOVED] $($entry.file)" -ForegroundColor Green
        $removed++
    }

    if (-not $DryRun) {
        if ($remaining.Count -gt 0) {
            Write-State -statePath $statePath -entries $remaining.ToArray() -version $version
        } elseif (Test-Path -LiteralPath $statePath) {
            Remove-Item -LiteralPath $statePath -Force
        }
    }

    Write-Host ""
    Write-Host "Uninstall summary: removed=$removed, kept=$kept, dryRun=$($DryRun.IsPresent)" -ForegroundColor Cyan
    exit 0
}

# --- INSTALL ACTION ---
Write-Host "Installing Antigravity Django Suite (v$version) into $targetRoot..." -ForegroundColor Cyan

$copied   = 0
$skipped  = 0
$uptodate = 0
$newState = [System.Collections.Generic.List[PSCustomObject]]::new()
$now      = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')

foreach ($item in $catalog) {
    $src        = $item.SourcePath
    $dest       = Join-Path $targetRoot $item.RelPath
    $srcHash    = Get-Sha256 $src
    $ownedMatch = @($installed | Where-Object { $_.file -eq $item.RelPath })

    # If destination file does not exist yet
    if (-not (Test-Path -LiteralPath $dest)) {
        if ($DryRun) {
            Write-Host "[DRYRUN] would add: $($item.RelPath)" -ForegroundColor Magenta
        } else {
            $destDir = Split-Path -Parent $dest
            if (-not (Test-Path -LiteralPath $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            Copy-Item -LiteralPath $src -Destination $dest -Force
            Write-Host "[ADDED]    $($item.RelPath)" -ForegroundColor Green
        }
        $copied++
        $newState.Add([PSCustomObject]@{
            file           = $item.RelPath
            sha256         = $srcHash
            installed_at   = $now
            source_version = $version
        })
        continue
    }

    # Destination exists. Check if foreign or modified
    $destHash = Get-Sha256 $dest

    if ($ownedMatch.Count -eq 0 -and -not $Force) {
        Write-Warning "Skipping $($item.RelPath): file exists but is not tracked by this suite. Pass -Force to overwrite."
        $skipped++
        continue
    }

    if ($ownedMatch.Count -gt 0 -and $destHash -ne $ownedMatch[0].sha256 -and -not $Force) {
        Write-Warning "Skipping $($item.RelPath): modified locally since install. Pass -Force to overwrite."
        $skipped++
        $newState.Add($ownedMatch[0])
        continue
    }

    if ($destHash -eq $srcHash) {
        # Already up to date
        $uptodate++
        $installedTime = if ($ownedMatch.Count -gt 0) { $ownedMatch[0].installed_at } else { $now }
        $newState.Add([PSCustomObject]@{
            file           = $item.RelPath
            sha256         = $srcHash
            installed_at   = $installedTime
            source_version = $version
        })
        continue
    }

    # Needs update
    if ($DryRun) {
        Write-Host "[DRYRUN] would update: $($item.RelPath)" -ForegroundColor Yellow
    } else {
        Copy-Item -LiteralPath $src -Destination $dest -Force
        Write-Host "[UPDATED]  $($item.RelPath)" -ForegroundColor Yellow
    }
    $copied++
    $newState.Add([PSCustomObject]@{
        file           = $item.RelPath
        sha256         = $srcHash
        installed_at   = $now
        source_version = $version
    })
}

# Preserve tracking of any other files in state not in current catalog
foreach ($entry in $installed) {
    if (-not ($newState | Where-Object { $_.file -eq $entry.file })) {
        $destPath = Join-Path $targetRoot $entry.file
        if (Test-Path -LiteralPath $destPath) {
            $newState.Add($entry)
        }
    }
}

if (-not $DryRun) {
    Write-State -statePath $statePath -entries $newState.ToArray() -version $version
}

Write-Host ""
Write-Host "Install summary: added/updated=$copied, unchanged=$uptodate, skipped=$skipped, dryRun=$($DryRun.IsPresent)" -ForegroundColor Cyan
Write-Host "Target project is now fully configured with Suite roles, skills, rules, and workflows." -ForegroundColor Green
exit 0
