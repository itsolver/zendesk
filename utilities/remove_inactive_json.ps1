# PowerShell script to remove JSON files where "active" field is false
# Author: Generated for IT Solver customer support project
# Usage: .\remove_inactive_json.ps1 [path] [-WhatIf] [-ShowDetails]

param(
    [Parameter(Position=0)]
    [string]$Path = ".\zendesk-support-assets\support_assets",
    
    [Parameter()]
    [switch]$WhatIf,
    
    [Parameter()]
    [switch]$ShowDetails
)

# Function to check if a JSON file has active: false
function Test-InactiveJsonFile {
    param([string]$FilePath)
    
    try {
        $content = Get-Content -Path $FilePath -Raw -ErrorAction Stop
        $json = $content | ConvertFrom-Json -ErrorAction Stop
        
        # Check if the JSON object has an "active" property set to false
        if ($json.PSObject.Properties.Name -contains "active" -and $json.active -eq $false) {
            return $true
        }
        return $false
    }
    catch {
        if ($ShowDetails) {
            Write-Warning "Failed to parse JSON file: $FilePath - $($_.Exception.Message)"
        }
        return $false
    }
}

# Main script
Write-Host "Scanning for JSON files with active: false in path: $Path" -ForegroundColor Green

if (-not (Test-Path $Path)) {
    Write-Error "Path does not exist: $Path"
    exit 1
}

# Get all JSON files recursively
$jsonFiles = Get-ChildItem -Path $Path -Filter "*.json" -Recurse -File

if ($jsonFiles.Count -eq 0) {
    Write-Host "No JSON files found in the specified path." -ForegroundColor Yellow
    exit 0
}

Write-Host "Found $($jsonFiles.Count) JSON files to check..." -ForegroundColor Cyan

$inactiveFiles = @()

# Check each JSON file
foreach ($file in $jsonFiles) {
    if ($ShowDetails) {
        Write-Host "Checking: $($file.FullName)" -ForegroundColor Gray
    }
    
    if (Test-InactiveJsonFile -FilePath $file.FullName) {
        $inactiveFiles += $file
        if ($ShowDetails) {
            Write-Host "  → Found inactive file: $($file.Name)" -ForegroundColor Yellow
        }
    }
}

if ($inactiveFiles.Count -eq 0) {
    Write-Host "No JSON files with active: false found." -ForegroundColor Green
    exit 0
}

Write-Host "`nFound $($inactiveFiles.Count) files with active: false:" -ForegroundColor Red
foreach ($file in $inactiveFiles) {
    Write-Host "  - $($file.FullName)" -ForegroundColor Red
}

if ($WhatIf) {
    Write-Host "`n[WHAT-IF] Would delete $($inactiveFiles.Count) files" -ForegroundColor Magenta
    Write-Host "Run without -WhatIf to actually delete the files." -ForegroundColor Magenta
} else {
    Write-Host "`nProceed with deletion? (y/N): " -ForegroundColor Yellow -NoNewline
    $confirmation = Read-Host
    
    if ($confirmation -eq 'y' -or $confirmation -eq 'Y') {
        $deletedCount = 0
        foreach ($file in $inactiveFiles) {
            try {
                Remove-Item -Path $file.FullName -Force
                Write-Host "Deleted: $($file.Name)" -ForegroundColor Green
                $deletedCount++
            }
            catch {
                Write-Error "Failed to delete $($file.FullName): $($_.Exception.Message)"
            }
        }
        Write-Host "`nSuccessfully deleted $deletedCount files." -ForegroundColor Green
    } else {
        Write-Host "Operation cancelled." -ForegroundColor Yellow
    }
}
