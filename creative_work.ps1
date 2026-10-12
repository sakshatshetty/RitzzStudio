[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$InputDirectory = '',
    [string]$ProjectId = '',
    [string]$OutputRoot = '',
    [string]$RitzzStudioRoot = '',
    [string]$PythonExecutable = '',
    [string]$GitHubRepository = 'sakshatshetty/RitzzStudio',
    [switch]$SkipRelease
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

if ([string]::IsNullOrWhiteSpace($RitzzStudioRoot)) {
    $RitzzStudioRoot = $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'Projects\Ritzz'
}
if ([string]::IsNullOrWhiteSpace($InputDirectory)) {
    $InputDirectory = Read-Host 'Enter the generated Flow staging folder path'
}
if ([string]::IsNullOrWhiteSpace($InputDirectory)) {
    throw 'A generated Flow staging folder path is required.'
}

function Write-Stage {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::Cyan
    )

    Write-Host "`n$Message" -ForegroundColor $Color
}

function Get-RequiredSection {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Sections,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not $Sections.ContainsKey($Name)) {
        throw "The input text is missing the '#$Name' section."
    }

    $value = ($Sections[$Name] -join "`n").Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "The '#$Name' section is empty."
    }
    return $value
}

function Invoke-RitzzPythonValidation {
    param(
        [Parameter(Mandatory = $true)][string]$PythonCode,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    $exitCode = 1
    $temporaryScript = Join-Path `
        ([System.IO.Path]::GetTempPath()) `
        ("ritzz_package_validator_{0}_{1}.py" -f $PID, [guid]::NewGuid().ToString('N'))
    try {
        [System.IO.File]::WriteAllText(
            $temporaryScript,
            "import os, sys`nsys.path.insert(0, os.getcwd())`n$PythonCode",
            $script:Utf8NoBom
        )
        Push-Location -LiteralPath $RitzzStudioRoot
        try {
            & $script:PythonPath $temporaryScript @Arguments
            $exitCode = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporaryScript -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryScript -Force
        }
    }

    if ($exitCode -ne 0) {
        throw "$FailureMessage (validator exit code $exitCode)."
    }
}

function Convert-RitzzImageToPng {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][int]$Width,
        [Parameter(Mandatory = $true)][int]$Height
    )

    $source = [System.Drawing.Image]::FromFile($SourcePath)
    try {
        $target = [System.Drawing.Bitmap]::new($Width, $Height)
        try {
            $graphics = [System.Drawing.Graphics]::FromImage($target)
            try {
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                $cropWidth = [int][Math]::Floor($source.Height * (16.0 / 9.0))
                if ($cropWidth -gt $source.Width) {
                    $cropHeight = [int][Math]::Floor($source.Width * (9.0 / 16.0))
                    $cropY = [int][Math]::Floor(($source.Height - $cropHeight) / 2)
                    $sourceRectangle = [System.Drawing.Rectangle]::new(
                        0, $cropY, $source.Width, $cropHeight
                    )
                }
                else {
                    $cropX = [int][Math]::Floor(($source.Width - $cropWidth) / 2)
                    $sourceRectangle = [System.Drawing.Rectangle]::new(
                        $cropX, 0, $cropWidth, $source.Height
                    )
                }
                $destinationRectangle = [System.Drawing.Rectangle]::new(
                    0, 0, $Width, $Height
                )
                $graphics.DrawImage(
                    $source,
                    $destinationRectangle,
                    $sourceRectangle,
                    [System.Drawing.GraphicsUnit]::Pixel
                )
            }
            finally {
                $graphics.Dispose()
            }
            $target.Save($DestinationPath, [System.Drawing.Imaging.ImageFormat]::Png)
        }
        finally {
            $target.Dispose()
        }
    }
    finally {
        $source.Dispose()
    }
}

function Assert-RitzzSourceImageSize {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$MinimumWidth,
        [Parameter(Mandatory = $true)][int]$MinimumHeight
    )

    $image = [System.Drawing.Image]::FromFile($Path)
    try {
        if ($image.Width -lt $MinimumWidth -or $image.Height -lt $MinimumHeight) {
            throw (
                "Image '$Path' is $($image.Width)x$($image.Height); " +
                "the minimum source size is ${MinimumWidth}x${MinimumHeight}."
            )
        }
    }
    finally {
        $image.Dispose()
    }
}

try {
    Write-Host 'RITZZ creative package builder' -ForegroundColor White
    Write-Host "Input folder: $InputDirectory"
    Write-Host "Output root:  $OutputRoot"

    Write-Stage '[1/6] Finding the creative brief, thumbnail, and Flow scene images...'
    if (-not (Test-Path -LiteralPath $InputDirectory -PathType Container)) {
        throw "Input folder does not exist: $InputDirectory"
    }
    if (-not (Test-Path -LiteralPath $RitzzStudioRoot -PathType Container)) {
        throw "RITZZ Studio repository was not found: $RitzzStudioRoot"
    }

    $textFiles = @(
        Get-ChildItem -LiteralPath $InputDirectory -File |
            Where-Object { $_.Extension -ieq '.txt' }
    )
    $imageFiles = @(
        Get-ChildItem -LiteralPath $InputDirectory -File |
            Where-Object { $_.Extension -match '^\.(png|jpe?g)$' }
    )
    if ($textFiles.Count -ne 1) {
        throw "Expected exactly one .txt file in '$InputDirectory'; found $($textFiles.Count)."
    }
    $thumbnailFiles = @(
        $imageFiles | Where-Object {
            $_.BaseName -match '(?i)(^thumbnail$|_thumbnail$)'
        }
    )
    if ($thumbnailFiles.Count -ne 1) {
        throw "Expected exactly one thumbnail named 'thumbnail' or ending in '_Thumbnail' in '$InputDirectory'; found $($thumbnailFiles.Count)."
    }
    $thumbnailSource = $thumbnailFiles[0]
    $sceneImageFiles = @(
        $imageFiles |
            Where-Object { $_.FullName -cne $thumbnailSource.FullName } |
            Sort-Object {
                if ($_.BaseName -match '(\d+)$') {
                    [int]$Matches[1]
                }
                else {
                    throw "Flow scene image filename must end in its scene number: $($_.Name)"
                }
            }
    )
    $sceneNumbers = @(
        $sceneImageFiles | ForEach-Object {
            [regex]::Match($_.BaseName, '(\d+)$').Groups[1].Value
        }
    )
    if (@($sceneNumbers | Select-Object -Unique).Count -ne $sceneNumbers.Count) {
        throw 'Scene image filenames contain duplicate trailing scene numbers.'
    }

    $utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
    $sourceText = [System.IO.File]::ReadAllText($textFiles[0].FullName, $utf8Strict)
    $sectionNames = @{
        'project id' = 'Project ID'
        'title' = 'Title'
        'word' = 'Word'
        'expected minutes' = 'expected minutes'
        'script' = 'script'
        'description' = 'Description'
        'tags' = 'Tags'
        'storyboard' = 'Storyboard'
    }
    $sections = @{}
    $currentSection = $null
    foreach ($line in ($sourceText -split "\r?\n")) {
        $heading = [regex]::Match(
            $line,
            '^\s*#\s*(Project ID|Title|Word|Expected minutes|Script|Description|Tags|Storyboard)\s*$',
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )
        if ($heading.Success) {
            $headingKey = $heading.Groups[1].Value.ToLowerInvariant()
            $sectionName = $sectionNames[$headingKey]
            if ($sections.ContainsKey($sectionName)) {
                throw "The input text contains the '#$sectionName' section more than once."
            }
            $sections[$sectionName] = New-Object 'System.Collections.Generic.List[string]'
            $currentSection = $sectionName
            continue
        }
        if ($null -ne $currentSection) {
            $sections[$currentSection].Add($line)
        }
    }

    $briefProjectId = Get-RequiredSection -Sections $sections -Name 'Project ID'
    if ([string]::IsNullOrWhiteSpace($ProjectId)) {
        Write-Host "Enter project ID (must match '$briefProjectId'): " -NoNewline
        $ProjectId = Read-Host
    }
    if ([string]::IsNullOrWhiteSpace($ProjectId)) {
        throw 'Project ID is required; the package was not created.'
    }
    $projectId = $ProjectId.Trim()
    if ($projectId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$') {
        throw 'Project ID must contain 1-80 letters, numbers, underscores, or hyphens.'
    }
    if ($projectId -cne $briefProjectId) {
        throw "Entered project ID '$projectId' does not match the brief's project ID '$briefProjectId'."
    }
    $title = Get-RequiredSection -Sections $sections -Name 'Title'
    $claimedWordCountText = Get-RequiredSection -Sections $sections -Name 'Word'
    $durationText = Get-RequiredSection -Sections $sections -Name 'expected minutes'
    $scriptText = Get-RequiredSection -Sections $sections -Name 'script'
    $descriptionText = Get-RequiredSection -Sections $sections -Name 'Description'
    $tagsSection = Get-RequiredSection -Sections $sections -Name 'Tags'
    $storyboardText = Get-RequiredSection -Sections $sections -Name 'Storyboard'
    try {
        $storyboard = $storyboardText | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "The '#Storyboard' section must contain valid JSON: $($_.Exception.Message)"
    }
    if ($null -eq $storyboard.scenes -or $storyboard.scenes.Count -lt 1 -or $storyboard.scenes.Count -gt 200) {
        throw 'The Storyboard JSON must contain between 1 and 200 scenes.'
    }
    if ([string]::IsNullOrWhiteSpace([string]$storyboard.thumbnail_prompt)) {
        throw 'The Storyboard JSON must include a Flow-ready thumbnail_prompt.'
    }
    if ($sceneImageFiles.Count -ne $storyboard.scenes.Count) {
        throw "Expected $($storyboard.scenes.Count) Flow scene images, found $($sceneImageFiles.Count)."
    }
    for ($index = 0; $index -lt $storyboard.scenes.Count; $index++) {
        $scene = $storyboard.scenes[$index]
        $expectedSceneId = 'scene_{0:D3}' -f ($index + 1)
        if ($scene.scene_id -cne $expectedSceneId) {
            throw "Storyboard scenes must be ordered and named scene_001, scene_002, and so on; expected $expectedSceneId."
        }
        foreach ($field in @('narration', 'visual_description', 'image_prompt')) {
            if ([string]::IsNullOrWhiteSpace([string]$scene.$field)) {
                throw "$expectedSceneId is missing the '$field' value."
            }
        }
        if ($scene.image_file -cne "images/$expectedSceneId.png") {
            throw "$expectedSceneId image_file must be 'images/$expectedSceneId.png'."
        }
    }

    Write-Stage '[2/6] Checking project metadata, script length, and tags...'
    if ($title.Length -gt 100) {
        throw 'The title exceeds the workflow limit of 100 characters.'
    }
    if ($descriptionText.Length -gt 5000) {
        throw 'The description exceeds the workflow limit of 5000 characters.'
    }
    if ($claimedWordCountText -notmatch '^\d+$') {
        throw "'#Word' must contain a whole-number word count."
    }
    if ($durationText -notmatch '^\d+$' -or [int]$durationText -lt 1) {
        throw "'#expected minutes' must contain a positive whole number."
    }
    if ($scriptText.Contains([char]0) -or $descriptionText.Contains([char]0)) {
        throw 'Script and description must be plain UTF-8 text.'
    }

    $actualWordCount = [regex]::Matches($scriptText, '\S+').Count
    $claimedWordCount = [int]$claimedWordCountText
    if ($actualWordCount -ne $claimedWordCount) {
        throw "Word count mismatch: header says $claimedWordCount; script contains $actualWordCount."
    }
    $targetMinutes = [int]$durationText
    $estimatedSeconds = $actualWordCount * 60 / 140
    $targetSeconds = $targetMinutes * 60
    if (
        $estimatedSeconds -lt [Math]::Max(1, $targetSeconds - 60) -or
        $estimatedSeconds -gt ($targetSeconds + 60)
    ) {
        throw (
            "Script estimates to $([Math]::Round($estimatedSeconds)) seconds at 140 words per minute; " +
            "the accepted range for $targetMinutes minute(s) is " +
            "$([Math]::Max(1, $targetSeconds - 60))-$($targetSeconds + 60) seconds."
        )
    }

    $tagLines = @($tagsSection -split "\r?\n")
    if ($tagLines.Count -eq 0) {
        throw 'The Tags section must contain at least one tag.'
    }
    foreach ($tag in $tagLines) {
        if ([string]::IsNullOrWhiteSpace($tag) -or $tag -cne $tag.Trim()) {
            throw 'Tags must be non-empty and trimmed, with one tag per line.'
        }
    }
    $tagCharacterCount = [long][Math]::Max(0, $tagLines.Count - 1)
    foreach ($tag in $tagLines) {
        $tagCharacterCount += $tag.Length
        if ($tag.Contains(' ')) {
            $tagCharacterCount += 2
        }
    }
    if ($tagCharacterCount -gt 500) {
        throw (
            "YouTube tags use $tagCharacterCount encoded characters; the limit is 500 " +
            '(including commas and quotes around multi-word tags).'
        )
    }
    Write-Host "YouTube tag character count: $tagCharacterCount/500" -ForegroundColor Green

    $inputRoot = [System.IO.Path]::GetFullPath($InputDirectory)
    $outputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
    $projectDirectory = [System.IO.Path]::GetFullPath(
        (Join-Path $inputRoot $projectId)
    )
    $finalProjectDirectory = [System.IO.Path]::GetFullPath(
        (Join-Path $outputRoot $projectId)
    )
    if ([System.IO.Path]::GetDirectoryName($projectDirectory) -ine $inputRoot) {
        throw "The staging folder is outside the input root: $projectDirectory"
    }
    if ([System.IO.Path]::GetDirectoryName($finalProjectDirectory) -ine $outputRoot) {
        throw "The output project folder is outside the output root: $finalProjectDirectory"
    }
    if ($projectDirectory -ieq $finalProjectDirectory) {
        throw 'The staging folder and final project folder must be different.'
    }
    $scriptName = "01_${projectId}_Script.txt"
    $titleName = "02_${projectId}_Title.txt"
    $descriptionName = "03_${projectId}_Description.txt"
    $tagsName = "04_${projectId}_Tags.txt"
    $thumbnailName = "05_${projectId}_Thumbnail.png"
    $storyboardName = 'storyboard.json'
    $sceneFileNames = @(
        foreach ($scene in $storyboard.scenes) {
            "images\$($scene.scene_id).png"
        }
    )
    $imageFileReferences = @(
        foreach ($scene in $storyboard.scenes) {
            "images/$($scene.scene_id).png"
        }
    )
    $tagsText = $tagLines -join "`n"
    $storyboardJson = $storyboard | ConvertTo-Json -Depth 20
    $manifest = [ordered]@{
        project_id = $projectId
        topic = $title
        target_duration_minutes = $targetMinutes
        script_file = $scriptName
        title_file = $titleName
        description_file = $descriptionName
        tags_file = $tagsName
        thumbnail_file = $thumbnailName
        storyboard_file = $storyboardName
        image_files = $imageFileReferences
    }
    $manifestText = ($manifest | ConvertTo-Json -Depth 4) + "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $script:Utf8NoBom = $utf8NoBom
    $expectedFiles = [ordered]@{
        $scriptName = $utf8NoBom.GetBytes($scriptText + "`n")
        $titleName = $utf8NoBom.GetBytes($title + "`n")
        $descriptionName = $utf8NoBom.GetBytes($descriptionText + "`n")
        $tagsName = $utf8NoBom.GetBytes($tagsText + "`n")
        $storyboardName = $utf8NoBom.GetBytes($storyboardJson + "`n")
        'project.json' = $utf8NoBom.GetBytes($manifestText)
    }

    Write-Stage '[3/7] Creating the per-project staging folder and named files...'
    if (-not (Test-Path -LiteralPath $projectDirectory)) {
        New-Item -ItemType Directory -Path $projectDirectory -Force | Out-Null
    }
    $expectedNames = @($expectedFiles.Keys) + $thumbnailName + 'creative-package.zip'
    $expectedTopLevelNames = @(
        $expectedNames | Where-Object { $_ -notmatch '[\\/]' }
    )
    $unexpectedFiles = @(
        Get-ChildItem -LiteralPath $projectDirectory -File -Force |
            Where-Object { $_.Name -notin $expectedTopLevelNames }
    )
    $unexpectedDirectories = @(
        Get-ChildItem -LiteralPath $projectDirectory -Directory -Force |
            Where-Object { $_.Name -cne 'images' }
    )
    if ($unexpectedFiles.Count -gt 0 -or $unexpectedDirectories.Count -gt 0) {
        throw "Project folder contains unrelated files or folders: $projectDirectory"
    }
    if (-not (Test-Path -LiteralPath $projectDirectory)) {
        New-Item -ItemType Directory -Path $projectDirectory | Out-Null
    }
    $imagesDirectory = Join-Path $projectDirectory 'images'
    if (-not (Test-Path -LiteralPath $imagesDirectory)) {
        New-Item -ItemType Directory -Path $imagesDirectory | Out-Null
    }
    $existingSceneFiles = @(
        Get-ChildItem -LiteralPath $imagesDirectory -File -Force |
            Select-Object -ExpandProperty Name
    )
    $unexpectedSceneFiles = @(
        $existingSceneFiles |
            Where-Object {
                $_ -notin @($sceneFileNames | ForEach-Object { Split-Path -Leaf $_ })
            }
    )
    if ($unexpectedSceneFiles.Count -gt 0) {
        throw "Images folder contains unrelated files: $($unexpectedSceneFiles -join ', ')."
    }

    $temporaryImageDirectory = Join-Path `
        ([System.IO.Path]::GetTempPath()) `
        ("ritzz_flow_images_{0}_{1}" -f $PID, [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporaryImageDirectory | Out-Null
    try {
        $thumbnailPng = Join-Path $temporaryImageDirectory $thumbnailName
        Assert-RitzzSourceImageSize `
            -Path $thumbnailSource.FullName `
            -MinimumWidth 1280 `
            -MinimumHeight 720
        Convert-RitzzImageToPng `
            -SourcePath $thumbnailSource.FullName `
            -DestinationPath $thumbnailPng `
            -Width 1280 `
            -Height 720
        $expectedFiles[$thumbnailName] = [System.IO.File]::ReadAllBytes($thumbnailPng)
        $expectedSceneFiles = New-Object 'System.Collections.Generic.List[string]'
        for ($index = 0; $index -lt $sceneImageFiles.Count; $index++) {
            $sceneFileName = Split-Path -Leaf $sceneFileNames[$index]
            $temporaryScene = Join-Path $temporaryImageDirectory $sceneFileName
            Assert-RitzzSourceImageSize `
                -Path $sceneImageFiles[$index].FullName `
                -MinimumWidth 1280 `
                -MinimumHeight 720
            Convert-RitzzImageToPng `
                -SourcePath $sceneImageFiles[$index].FullName `
                -DestinationPath $temporaryScene `
                -Width 1536 `
                -Height 864
            $destination = Join-Path $imagesDirectory $sceneFileName
            if (Test-Path -LiteralPath $destination -PathType Leaf) {
                $existingHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
                $expectedHash = (Get-FileHash -LiteralPath $temporaryScene -Algorithm SHA256).Hash
                if ($existingHash -cne $expectedHash) {
                    throw "Refusing to overwrite a different existing scene image: $destination"
                }
            }
            else {
                Copy-Item -LiteralPath $temporaryScene -Destination $destination
            }
            $expectedSceneFiles.Add($sceneFileName)
        }
    }
    finally {
        Remove-Item -LiteralPath $temporaryImageDirectory -Recurse -Force
    }

    foreach ($entry in $expectedFiles.GetEnumerator()) {
        $destination = Join-Path $projectDirectory $entry.Key
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            $existingBytes = [System.IO.File]::ReadAllBytes($destination)
            $existingEncoded = [Convert]::ToBase64String($existingBytes)
            $expectedEncoded = [Convert]::ToBase64String([byte[]]$entry.Value)
            if ($existingEncoded -cne $expectedEncoded) {
                throw "Refusing to overwrite a different existing project file: $destination"
            }
        }
        else {
            [System.IO.File]::WriteAllBytes($destination, [byte[]]$entry.Value)
        }
    }
    Write-Stage '[4/7] Validating the thumbnail and assembled project files...'
    foreach ($fileName in $expectedFiles.Keys) {
        $path = Join-Path $projectDirectory $fileName
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required project file is missing: $path"
        }
        if ((Get-Item -LiteralPath $path).Length -eq 0) {
            throw "Project file is empty: $path"
        }
    }
    $pythonCandidate = $PythonExecutable
    if ([string]::IsNullOrWhiteSpace($pythonCandidate)) {
        $pythonCandidate = Join-Path $RitzzStudioRoot '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $pythonCandidate -PathType Leaf)) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) {
            throw "Python was not found. Expected the repository venv at '$pythonCandidate'."
        }
        $pythonCandidate = $pythonCommand.Source
    }
    $script:PythonPath = $pythonCandidate

    $imageValidationCode = @'
import sys
from modules.video.image_asset_qa import inspect_image_asset

path = sys.argv[1]
image = inspect_image_asset(path)
if image.width < 1280 or image.height < 720 or abs(image.width * 9 - image.height * 16) > 16:
    raise SystemExit(
        f"Thumbnail must be readable RGB/RGBA PNG, at least 1280x720, and 16:9; "
        f"received {image.width}x{image.height}."
    )
print(f"Thumbnail PASS: {image.width}x{image.height} RGB/RGBA PNG")
'@
    Invoke-RitzzPythonValidation `
        -PythonCode $imageValidationCode `
        -Arguments @((Join-Path $projectDirectory $thumbnailName)) `
        -FailureMessage 'Thumbnail validation failed'

    $zipPath = Join-Path $projectDirectory 'creative-package.zip'
    if (Test-Path -LiteralPath $zipPath -PathType Leaf) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Write-Stage '[5/7] Creating and validating creative-package.zip...'
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $sourceFiles = @(
        Get-ChildItem -LiteralPath $projectDirectory -File -Recurse |
            Where-Object { $_.FullName -ine $zipPath }
    )
    $archive = [System.IO.Compression.ZipFile]::Open(
        $zipPath,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        foreach ($sourceFile in $sourceFiles) {
            $entryName = $sourceFile.FullName.Substring($projectDirectory.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
            if ([string]::IsNullOrWhiteSpace($entryName) -or $entryName.Contains('\')) {
                throw "Could not create a portable ZIP member name for '$($sourceFile.FullName)'."
            }
            $entry = $archive.CreateEntry(
                $entryName,
                [System.IO.Compression.CompressionLevel]::Optimal
            )
            $sourceStream = [System.IO.File]::OpenRead($sourceFile.FullName)
            try {
                $entryStream = $entry.Open()
                try {
                    $sourceStream.CopyTo($entryStream)
                }
                finally {
                    $entryStream.Dispose()
                }
            }
            finally {
                $sourceStream.Dispose()
            }
        }
    }
    finally {
        $archive.Dispose()
    }
    if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
        throw 'ZIP creation did not produce the requested archive.'
    }

    $packageValidationCode = @'
import sys
from modules.project.creative_package import load_creative_package

package = load_creative_package(sys.argv[1])
print(
    "Creative package PASS: "
    f"{package.manifest.project_id} | {package.manifest.topic} | "
    f"{len(package.tags)} tags | "
    f"{package.manifest.target_duration_minutes} minute(s)"
)
'@
    Invoke-RitzzPythonValidation `
        -PythonCode $packageValidationCode `
        -Arguments @($zipPath) `
        -FailureMessage 'Creative package ZIP validation failed'

    Write-Stage '[6/7] Replacing the output project folder from the validated staging package...'
    if (-not (Test-Path -LiteralPath $outputRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
    }
    $pendingProjectDirectory = Join-Path `
        $outputRoot `
        (".ritzz-package-{0}-{1}" -f $projectId, [guid]::NewGuid().ToString('N'))
    $destinationRemoved = $false
    try {
        New-Item -ItemType Directory -Path $pendingProjectDirectory | Out-Null
        Get-ChildItem -LiteralPath $projectDirectory -Force |
            ForEach-Object {
                Copy-Item `
                    -LiteralPath $_.FullName `
                    -Destination $pendingProjectDirectory `
                    -Recurse `
                    -Force
            }

        $pendingZipPath = Join-Path $pendingProjectDirectory 'creative-package.zip'
        if (
            -not (Test-Path -LiteralPath $pendingZipPath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $pendingZipPath -Algorithm SHA256).Hash -cne
                (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
        ) {
            throw 'The staged creative-package.zip did not copy intact to the output candidate.'
        }

        if (Test-Path -LiteralPath $finalProjectDirectory) {
            $existingProject = Get-Item -LiteralPath $finalProjectDirectory -Force
            if (-not $existingProject.PSIsContainer) {
                throw "The output project path exists but is not a folder: $finalProjectDirectory"
            }
            if (
                ($existingProject.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
            ) {
                throw "Refusing to replace an output project folder that is a reparse point: $finalProjectDirectory"
            }
            Remove-Item -LiteralPath $finalProjectDirectory -Recurse -Force
            $destinationRemoved = $true
        }

        Move-Item -LiteralPath $pendingProjectDirectory -Destination $finalProjectDirectory
    }
    catch {
        if (-not $destinationRemoved -and (Test-Path -LiteralPath $pendingProjectDirectory)) {
            Remove-Item -LiteralPath $pendingProjectDirectory -Recurse -Force
        }
        throw
    }
    $finalZipPath = Join-Path $finalProjectDirectory 'creative-package.zip'

    if ($SkipRelease) {
        Write-Stage '[7/7] Release upload skipped by -SkipRelease.' -Color Yellow
    }
    else {
        Write-Stage '[7/7] Creating the GitHub release and uploading the ZIP...'
        $ghCommand = Get-Command gh -ErrorAction SilentlyContinue
        if ($null -eq $ghCommand) {
            throw 'GitHub CLI (gh) was not found on PATH.'
        }
        & $ghCommand.Source auth status --hostname github.com
        if ($LASTEXITCODE -ne 0) {
            throw 'GitHub CLI authentication failed. Run gh auth login, then retry.'
        }

        $releaseJson = & $ghCommand.Source release list `
            --repo $GitHubRepository `
            --limit 1000 `
            --json tagName
        if ($LASTEXITCODE -ne 0) {
            throw "Could not check existing releases for $GitHubRepository."
        }
        $releaseList = @()
        if (-not [string]::IsNullOrWhiteSpace(($releaseJson -join ''))) {
            $releaseList = @($releaseJson -join "`n" | ConvertFrom-Json)
        }
        if ($releaseList | Where-Object { $_.tagName -ceq $projectId }) {
            throw "A GitHub release with tag '$projectId' already exists; no release was changed."
        }

        $assetArgument = "$finalZipPath#creative-package.zip"
        & $ghCommand.Source release create `
            $projectId `
            $assetArgument `
            --repo $GitHubRepository `
            --title "RITZZ Creative Package $projectId" `
            --notes "Validated creative package for project $projectId."
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub release creation or ZIP upload failed for tag '$projectId'."
        }
        Write-Host "Release created: $GitHubRepository/releases/tag/$projectId" -ForegroundColor Green
    }

    Write-Host "`nSUCCESS: project files and validated ZIP are at $finalProjectDirectory" -ForegroundColor Green
    Write-Host "Project ID: $projectId"
    Write-Host "Word count: $actualWordCount"
    Write-Host "Staging:    $projectDirectory"
    Write-Host "ZIP:        $finalZipPath"
    exit 0
}
catch {
    Write-Host "`nFAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
