# Remove Inactive JSON Files Scripts

This repository contains two scripts to automatically identify and remove JSON files where the `active` field is set to `false` in the Zendesk support assets directory.

## Scripts Available

### 1. PowerShell Script (`remove_inactive_json.ps1`)
- **Platform**: Windows (PowerShell)
- **Recommended for**: Windows environments

### 2. Node.js Script (`remove_inactive_json.js`)
- **Platform**: Cross-platform (requires Node.js)
- **Recommended for**: Linux, macOS, or when Node.js is preferred

## Usage

### PowerShell Script

```powershell
# Basic usage (scans ./zendesk-support-assets by default)
.\remove_inactive_json.ps1

# Specify a custom path
.\remove_inactive_json.ps1 "C:\path\to\your\json\files"

# Dry run - see what would be deleted without actually deleting
.\remove_inactive_json.ps1 -WhatIf

# Show detailed output during processing
.\remove_inactive_json.ps1 -ShowDetails

# Combine options
.\remove_inactive_json.ps1 ".\zendesk-support-assets" -WhatIf -ShowDetails
```

### Node.js Script

```bash
# Basic usage (scans ./zendesk-support-assets by default)
node remove_inactive_json.js

# Specify a custom path
node remove_inactive_json.js /path/to/your/json/files

# Dry run - see what would be deleted without actually deleting
node remove_inactive_json.js --dry-run

# Show detailed output during processing
node remove_inactive_json.js --verbose

# Combine options
node remove_inactive_json.js ./zendesk-support-assets --dry-run --verbose
```

## Features

- **Safe Operation**: Both scripts require user confirmation before deleting files (unless in dry-run mode)
- **Dry Run Mode**: Test the scripts without making any changes
- **Detailed Logging**: See exactly which files are being processed
- **Error Handling**: Gracefully handles malformed JSON files and permission errors
- **Recursive Search**: Automatically scans all subdirectories
- **Cross-Platform**: Node.js version works on Windows, Linux, and macOS

## What the Scripts Do

1. **Scan** all JSON files recursively in the specified directory
2. **Parse** each JSON file to check for an `active` field
3. **Identify** files where `active: false`
4. **List** all matching files for review
5. **Prompt** for confirmation before deletion
6. **Delete** confirmed files and report results

## Example Output

```
Scanning for JSON files with active: false in path: ./zendesk-support-assets
Found 550 JSON files to check...

Found 140 files with active: false:
  - zendesk-support-assets\support_assets\views\jake-recently-updated.json
  - zendesk-support-assets\support_assets\ticket_fields\customer-segment.json
  - zendesk-support-assets\support_assets\macros\quick-acknowledgement.json
  ...

Proceed with deletion? (y/N):
```

## Safety Considerations

- **Always run with dry-run mode first** (`-WhatIf` or `--dry-run`) to preview changes
- **Backup your data** before running the deletion
- The scripts only delete files where `active` is explicitly set to `false`
- Malformed JSON files are skipped with warnings (in verbose mode)

## Requirements

### PowerShell Script
- Windows PowerShell 5.1+ or PowerShell Core 6.0+
- No additional dependencies

### Node.js Script
- Node.js 12.0+ (uses built-in modules only)
- No additional npm packages required

## Error Handling

Both scripts handle common errors gracefully:
- **Invalid JSON**: Skips files that can't be parsed as JSON
- **Permission errors**: Reports files that can't be deleted due to permissions
- **Missing directories**: Validates paths before processing
- **Network drives**: Works with local and network paths

## Git Integration

After running the scripts, you can commit the changes using:

```bash
git add .
git commit -m "Remove inactive JSON files from zendesk support assets"
```

## Support

These scripts were generated for the IT Solver customer support project. For issues or modifications, review the script code or regenerate as needed.
