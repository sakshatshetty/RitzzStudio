# ==========================================================
# Ritzz Studio - Workspace Setup
# Version: 1.0
# ==========================================================

$Root = "D:\AIStudio"
$Project = "$Root\RitzzStudio"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "   Creating Ritzz Studio Workspace"
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# ==========================================================
# Directory Structure
# ==========================================================

$folders = @(

    # Root
    $Root,

    # ------------------------------------------------------
    # Main Project
    # ------------------------------------------------------
    $Project,

    # Documentation
    "$Project\docs",

    # Application Source
    "$Project\modules",
    "$Project\config",
    "$Project\prompts",
    "$Project\schemas",
    "$Project\tests",

    # Project Resources
    "$Project\resources",
    "$Project\resources\icons",
    "$Project\resources\logos",

    # Shared Assets
    "$Project\assets",
    "$Project\assets\branding",
    "$Project\assets\fonts",
    "$Project\assets\music",
    "$Project\assets\overlays",
    "$Project\assets\sfx",

    # Runtime
    "$Project\cache",
    "$Project\logs",
    "$Project\output",

    # Video Projects
    "$Project\projects",

    # Templates
    "$Project\templates",
    "$Project\templates\json",
    "$Project\templates\prompts",

    # Utility Scripts
    "$Project\scripts",

    # Sample Files
    "$Project\examples",

    # Future Storage
    "$Project\storage",

    # VS Code
    "$Project\.vscode",

    # ------------------------------------------------------
    # Shared Workspace
    # ------------------------------------------------------
    "$Root\Assets",
    "$Root\Videos",
    "$Root\Exports",
    "$Root\Archive",

    # ------------------------------------------------------
    # Third Party Tools
    # ------------------------------------------------------
    "$Root\Tools",
    "$Root\Tools\ffmpeg",
    "$Root\Tools\models",
    "$Root\Tools\whisper"
)

foreach ($folder in $folders) {
    if (!(Test-Path $folder)) {
        New-Item -ItemType Directory -Path $folder | Out-Null
        Write-Host "[Created] $folder" -ForegroundColor Green
    }
    else {
        Write-Host "[Exists ] $folder" -ForegroundColor Yellow
    }
}

# ==========================================================
# Files
# ==========================================================

$files = @(

    # Root
    "$Project\README.md",
    "$Project\requirements.txt",
    "$Project\.gitignore",
    "$Project\.env",
    "$Project\.env.example",

    "$Project\app.py",
    "$Project\config.py",

    # Documentation
    "$Project\docs\Architecture.md",
    "$Project\docs\Environment Setup.md",
    "$Project\docs\Milestones.md",

    # VS Code
    "$Project\.vscode\settings.json",

    # Package Initializers
    "$Project\modules\__init__.py",
    "$Project\config\__init__.py",
    "$Project\tests\__init__.py"
)

foreach ($file in $files) {
    if (!(Test-Path $file)) {
        New-Item -ItemType File -Path $file | Out-Null
        Write-Host "[Created] $file" -ForegroundColor Cyan
    }
    else {
        Write-Host "[Exists ] $file" -ForegroundColor Yellow
    }
}

# ==========================================================
# Git Ignore
# ==========================================================

$gitignore = @"
# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd

# Virtual Environment
.venv/
venv/

# Environment Variables
.env

# Logs
logs/
*.log

# Cache
cache/

# Runtime Output
output/

# Video Projects
projects/

# VS Code
.vscode/

# macOS
.DS_Store

# Windows
Thumbs.db

# Pytest
.pytest_cache/

# Mypy
.mypy_cache/

# Ruff
.ruff_cache/

# Coverage
.coverage
htmlcov/
"@

Set-Content -Path "$Project\.gitignore" -Value $gitignore

# ==========================================================
# Environment Template
# ==========================================================

$env = @"
OPENAI_API_KEY=

ELEVENLABS_API_KEY=

PROJECT_ENV=development

LOG_LEVEL=INFO
"@

Set-Content "$Project\.env.example" $env

# ==========================================================
# VS Code Settings
# ==========================================================

$vscode = @"
{
    "editor.formatOnSave": true,
    "python.analysis.typeCheckingMode": "basic",
    "files.trimTrailingWhitespace": true,
    "editor.rulers": [100]
}
"@

Set-Content "$Project\.vscode\settings.json" $vscode

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host " Workspace Created Successfully!"
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""

Write-Host "Project Location :" -ForegroundColor Cyan
Write-Host "$Project"

Write-Host ""
Write-Host "Next Steps"
Write-Host "----------"
Write-Host "1. Open VS Code"
Write-Host "2. Open RitzzStudio folder"
Write-Host "3. Create Python virtual environment"
Write-Host "4. Initialize Git"
Write-Host "5. Install dependencies"
Write-Host ""s