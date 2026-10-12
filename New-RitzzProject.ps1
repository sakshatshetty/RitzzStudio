param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [Parameter(Mandatory = $true)][string]$Topic,
    [Parameter(Mandatory = $true)][double]$TargetDurationMinutes,
    [string]$ProjectsRoot = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectsRoot)) {
    $ProjectsRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'Projects\Ritzz'
}
$root = [System.IO.Path]::GetFullPath($ProjectsRoot)
$projectDir = Join-Path $root $ProjectId

if (Test-Path -LiteralPath $projectDir) {
    throw "Project folder already exists: $projectDir"
}

New-Item -ItemType Directory -Path $projectDir -Force | Out-Null

$files = [ordered]@{
    script      = "01_${ProjectId}_Script.txt"
    title       = "02_${ProjectId}_Title.txt"
    description = "03_${ProjectId}_Description.txt"
    tags        = "04_${ProjectId}_Tags.txt"
}

foreach ($name in $files.Values) {
    New-Item -ItemType File -Path (Join-Path $projectDir $name) | Out-Null
}

$project = [ordered]@{
    project_id              = $ProjectId
    topic                   = $Topic
    target_duration_minutes = $TargetDurationMinutes
    script_file             = $files.script
    title_file              = $files.title
    description_file        = $files.description
    tags_file               = $files.tags
    thumbnail_file          = 'thumbnail.png'
}

$json = $project | ConvertTo-Json
[System.IO.File]::WriteAllText(
    (Join-Path $projectDir 'project.json'),
    $json,
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host "Created project at $projectDir"
