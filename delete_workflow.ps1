[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string]$ProjectId,
    [string]$ProjectRoot = '',
    [string]$GitHubRepository = 'sakshatshetty/RitzzStudio'
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'Projects\Ritzz'
}

function Get-GitHubRunInfo {
    param(
        [Parameter(Mandatory = $true)][string]$GhPath,
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][long]$RunId
    )

    $runJson = & $GhPath run view $RunId `
        --repo $Repository `
        --json databaseId,displayTitle,status,conclusion,workflowName
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect GitHub Actions run $RunId."
    }
    return (($runJson -join "`n") | ConvertFrom-Json)
}

try {
    if ([string]::IsNullOrWhiteSpace($ProjectId)) {
        $ProjectId = Read-Host 'Enter the exact project ID to delete'
    }
    $ProjectId = $ProjectId.Trim()
    if ($ProjectId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$') {
        throw 'Project ID must contain 1-80 letters, numbers, underscores, or hyphens.'
    }
    if ($GitHubRepository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
        throw "Invalid GitHub repository name: $GitHubRepository"
    }

    $resolvedProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
    $localProjectDirectory = [System.IO.Path]::GetFullPath(
        (Join-Path $resolvedProjectRoot $ProjectId)
    )
    if ([System.IO.Path]::GetDirectoryName($localProjectDirectory) -ine $resolvedProjectRoot) {
        throw "Refusing to delete a path outside the project root: $localProjectDirectory"
    }

    if (Test-Path -LiteralPath $resolvedProjectRoot) {
        $rootItem = Get-Item -LiteralPath $resolvedProjectRoot -Force
        if (-not $rootItem.PSIsContainer) {
            throw "Project root is not a directory: $resolvedProjectRoot"
        }
        if (($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to use a project root that is a reparse point: $resolvedProjectRoot"
        }
    }

    $localProjectExists = Test-Path -LiteralPath $localProjectDirectory
    if ($localProjectExists) {
        $localItem = Get-Item -LiteralPath $localProjectDirectory -Force
        if (-not $localItem.PSIsContainer) {
            throw "The project path exists but is not a folder: $localProjectDirectory"
        }
        if (($localItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to delete a project folder that is a reparse point: $localProjectDirectory"
        }
    }

    $ghCommand = Get-Command gh -ErrorAction Stop
    & $ghCommand.Source auth status --hostname github.com
    if ($LASTEXITCODE -ne 0) {
        throw 'GitHub CLI authentication failed. Run gh auth login, then retry.'
    }

    $releaseJson = & $ghCommand.Source release list `
        --repo $GitHubRepository `
        --limit 1000 `
        --json tagName
    if ($LASTEXITCODE -ne 0) {
        throw "Could not list GitHub releases for $GitHubRepository."
    }
    $releaseList = @()
    if (-not [string]::IsNullOrWhiteSpace(($releaseJson -join ''))) {
        $releaseList = @(($releaseJson -join "`n") | ConvertFrom-Json)
    }
    $releaseExists = @(
        $releaseList | Where-Object { $_.tagName -ceq $ProjectId }
    ).Count -gt 0

    $tagJson = & $ghCommand.Source api `
        --method GET `
        "repos/$GitHubRepository/git/matching-refs/tags/$ProjectId"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect GitHub tags for $GitHubRepository."
    }
    $tagRefs = @()
    if (-not [string]::IsNullOrWhiteSpace(($tagJson -join ''))) {
        $tagRefs = @(($tagJson -join "`n") | ConvertFrom-Json)
    }
    $tagExists = @(
        $tagRefs | Where-Object { $_.ref -ceq "refs/tags/$ProjectId" }
    ).Count -gt 0

    $artifactPagesJson = & $ghCommand.Source api `
        --paginate `
        --slurp `
        "repos/$GitHubRepository/actions/artifacts?per_page=100"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not list GitHub Actions artifacts for $GitHubRepository."
    }
    $artifactPages = @()
    if (-not [string]::IsNullOrWhiteSpace(($artifactPagesJson -join ''))) {
        $artifactPages = @(($artifactPagesJson -join "`n") | ConvertFrom-Json)
    }
    $creativeArtifactPrefix = "ritzz-creative-production-$ProjectId-"
    $legacyArtifactPrefix = "ritzz-production-$ProjectId-"
    $matchingArtifacts = @(
        foreach ($page in $artifactPages) {
            foreach ($artifact in $page.artifacts) {
                $artifactName = [string]$artifact.name
                if (
                    $null -ne $artifact.workflow_run -and
                    (
                        $artifactName.StartsWith(
                            $creativeArtifactPrefix,
                            [System.StringComparison]::Ordinal
                        ) -or
                        $artifactName.StartsWith(
                            $legacyArtifactPrefix,
                            [System.StringComparison]::Ordinal
                        )
                    )
                ) {
                    [pscustomobject]@{
                        RunId = [long]$artifact.workflow_run.id
                        Name = $artifactName
                    }
                }
            }
        }
    )
    $workflowRuns = @(
        foreach ($runArtifacts in ($matchingArtifacts | Group-Object RunId)) {
            $runInfo = Get-GitHubRunInfo `
                -GhPath $ghCommand.Source `
                -Repository $GitHubRepository `
                -RunId ([long]$runArtifacts.Name)
            [pscustomobject]@{
                RunId = [long]$runInfo.databaseId
                DisplayTitle = [string]$runInfo.displayTitle
                WorkflowName = [string]$runInfo.workflowName
                Status = [string]$runInfo.status
                Conclusion = [string]$runInfo.conclusion
                ArtifactNames = @(
                    $runArtifacts.Group |
                        Select-Object -ExpandProperty Name -Unique
                )
            }
        }
    )

    Write-Host ''
    Write-Host "Project ID:       $ProjectId"
    Write-Host "Local folder:     $localProjectDirectory"
    Write-Host "Folder exists:    $localProjectExists"
    Write-Host "GitHub release:   $releaseExists ($GitHubRepository)"
    Write-Host "Exact Git tag:    $tagExists ($GitHubRepository)"
    Write-Host "Matching Actions runs: $($workflowRuns.Count)"
    foreach ($run in $workflowRuns) {
        Write-Host (
            "  Run {0}: {1} | {2} | {3} | artifacts: {4}" -f
            $run.RunId,
            $run.Status,
            $run.Conclusion,
            $run.WorkflowName,
            ($run.ArtifactNames -join ', ')
        )
    }
    Write-Host 'Matching Actions runs (including their logs and artifacts) will be deleted.'
    Write-Host 'Workflow definition files will not be deleted.'

    if (
        -not $localProjectExists -and
        -not $releaseExists -and
        -not $tagExists -and
        $workflowRuns.Count -eq 0
    ) {
        Write-Host 'Nothing matched this project ID; no changes made.' -ForegroundColor Yellow
        exit 0
    }

    if (-not $WhatIfPreference) {
        $confirmation = Read-Host "To permanently delete the listed project data, type DELETE $ProjectId"
        if ($confirmation -cne "DELETE $ProjectId") {
            Write-Host 'Confirmation did not match; nothing was deleted.' -ForegroundColor Yellow
            exit 0
        }
    }

    foreach ($run in $workflowRuns) {
        $runTarget = "Actions run $($run.RunId): $($run.WorkflowName)"
        if ($run.Status -ne 'completed') {
            if (-not $PSCmdlet.ShouldProcess(
                $runTarget,
                'Cancel active run, wait for completion, then delete run, logs, and artifacts'
            )) {
                continue
            }

            & $ghCommand.Source run cancel $run.RunId --repo $GitHubRepository
            if ($LASTEXITCODE -ne 0) {
                $runState = Get-GitHubRunInfo `
                    -GhPath $ghCommand.Source `
                    -Repository $GitHubRepository `
                    -RunId $run.RunId
                if ($runState.Status -ne 'completed') {
                    throw "Could not cancel active GitHub Actions run $($run.RunId)."
                }
            }

            $deadline = (Get-Date).AddMinutes(2)
            do {
                Start-Sleep -Seconds 2
                $runState = Get-GitHubRunInfo `
                    -GhPath $ghCommand.Source `
                    -Repository $GitHubRepository `
                    -RunId $run.RunId
            } while ($runState.Status -ne 'completed' -and (Get-Date) -lt $deadline)
            if ($runState.Status -ne 'completed') {
                throw "Run $($run.RunId) was canceled but has not finished yet; retry cleanup after it completes."
            }

            & $ghCommand.Source run delete $run.RunId --repo $GitHubRepository
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to delete GitHub Actions run $($run.RunId)."
            }
            Write-Host "Deleted GitHub Actions run: $($run.RunId)" -ForegroundColor Green
        }
        elseif ($PSCmdlet.ShouldProcess(
            $runTarget,
            'Delete workflow run, logs, and artifacts'
        )) {
            & $ghCommand.Source run delete $run.RunId --repo $GitHubRepository
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to delete GitHub Actions run $($run.RunId)."
            }
            Write-Host "Deleted GitHub Actions run: $($run.RunId)" -ForegroundColor Green
        }
    }

    if ($releaseExists) {
        if ($PSCmdlet.ShouldProcess(
            "$GitHubRepository release/tag $ProjectId",
            'Delete release and associated Git tag'
        )) {
            & $ghCommand.Source release delete $ProjectId `
                --repo $GitHubRepository `
                --cleanup-tag `
                --yes
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to delete GitHub release/tag '$ProjectId'."
            }
            Write-Host "Deleted GitHub release and tag: $ProjectId" -ForegroundColor Green
        }
    }
    elseif ($tagExists) {
        if ($PSCmdlet.ShouldProcess(
            "$GitHubRepository Git tag $ProjectId",
            'Delete exact Git tag'
        )) {
            & $ghCommand.Source api `
                --method DELETE `
                "repos/$GitHubRepository/git/refs/tags/$ProjectId"
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to delete Git tag '$ProjectId'."
            }
            Write-Host "Deleted Git tag: $ProjectId" -ForegroundColor Green
        }
    }

    if ($localProjectExists -and $PSCmdlet.ShouldProcess(
        $localProjectDirectory,
        'Recursively delete local project folder'
    )) {
        Remove-Item -LiteralPath $localProjectDirectory -Recurse -Force
        if (Test-Path -LiteralPath $localProjectDirectory) {
            throw "The local project folder still exists after deletion: $localProjectDirectory"
        }
        Write-Host "Deleted local project folder: $localProjectDirectory" -ForegroundColor Green
    }

    if ($WhatIfPreference) {
        Write-Host 'WhatIf mode: no project data was deleted.' -ForegroundColor Yellow
    }
}
catch {
    Write-Host "`nFAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
