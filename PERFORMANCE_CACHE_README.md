# Zendesk Backup Performance Improvements

## Overview

The consolidated backup script now includes significant performance improvements designed to handle large datasets (25,000+ tickets) efficiently while optimizing OneDrive sync performance.

## Key Performance Features

### 1. Local Caching System
- **Cache Location**: `C:\Users\AngusMcLauchlan\AppData\Local\ITSolver\Cache\Zendesk_backups\`
- **Purpose**: Store all working files locally to avoid OneDrive sync bottlenecks
- **Benefits**: 
  - Faster file operations (no cloud sync delays)
  - Reduced OneDrive file count (better sync performance)
  - Resumable backups using cached data

### 2. OneDrive Optimization
- **Single File Sync**: Only the final compressed zip file is copied to OneDrive
- **Working Files**: All intermediate files remain in local cache
- **Sync Performance**: Optimized for OneDrive's < 100,000 file limitation

### 3. Smart Incremental Backups
- **State Tracking**: Backup state saved in `backup_state.json`
- **Resume Capability**: Can resume interrupted backups from last processed item
- **Duplicate Detection**: Skips unchanged items using timestamp comparison
- **Progress Reporting**: Real-time progress updates for large datasets

### 4. Batch Processing
- **Batch Size**: Configurable batch processing (default: 100 items)
- **Memory Efficiency**: Processes items in chunks to reduce memory usage
- **Rate Limiting**: Built-in API rate limiting with retry logic

## Directory Structure

```
Local Cache (C:\Users\AngusMcLauchlan\AppData\Local\ITSolver\Cache\Zendesk_backups\):
├── backup_state.json                    # Resumable backup state
├── zendesk_backup_2024-01-15.zip       # Local copy of backup
├── zendesk_backup_2024-01-15_14-30-25/ # Working directory (deleted after zip)
│   ├── tickets/
│   ├── users/
│   ├── organizations/
│   ├── guide_articles/
│   └── support_assets/

OneDrive Sync (C:\Users\...\IT Solver - Documents\Admin\Business\Zendesk\Backups\):
└── zendesk_backup_2024-01-15.zip       # Single file for OneDrive sync
```

## Performance Improvements

### Before (Individual Scripts)
- ❌ 7 separate scripts to manage
- ❌ Files directly created in OneDrive sync folder
- ❌ No resumable backup capability
- ❌ Thousands of files syncing to OneDrive
- ❌ Slow performance with large datasets

### After (Consolidated with Cache)
- ✅ Single unified script
- ✅ Local cache for fast operations
- ✅ Resumable backups with state tracking
- ✅ Only final zip file synced to OneDrive
- ✅ Optimized for 25,000+ tickets

## Configuration

### Environment Variables
```bash
# Optional: Override default cache location
set LOCAL_CACHE_PATH=D:\MyCache\Zendesk

# Optional: Override OneDrive backup location
set BACKUP_PATH=D:\OneDrive\Business\Zendesk\Backups
```

### Batch Processing
```python
BATCH_SIZE = 100  # Adjust for memory/performance balance
```

## Usage

### Normal Backup
```bash
python backup_zendesk_all.py
```

### Resume Interrupted Backup
The script automatically detects and resumes interrupted backups using the state file.

### Clean Cache (if needed)
```bash
# Manually clean cache if needed
rmdir /s "C:\Users\AngusMcLauchlan\AppData\Local\ITSolver\Cache\Zendesk_backups"
```

## Monitoring Progress

The script provides detailed progress information:
- Real-time counts of cached vs downloaded items
- Batch progress updates
- Final summary with performance metrics
- Separate logs for each asset type

## Troubleshooting

### Large Dataset Performance
- Monitor memory usage during large ticket downloads
- Adjust `BATCH_SIZE` if needed
- Ensure sufficient disk space in cache directory

### OneDrive Sync Issues
- Only the final zip file should appear in OneDrive
- If sync is slow, check OneDrive file count limits
- Cache directory is not synced (by design)

### Resume Failed Backup
- State file automatically tracks progress
- Delete `backup_state.json` to force full restart
- Check cache directory for partial data

## Benefits Summary

1. **Speed**: Local cache eliminates OneDrive sync delays during backup
2. **Reliability**: Resumable backups handle interruptions gracefully  
3. **Efficiency**: Only final zip file synced to cloud
4. **Scalability**: Handles 25,000+ tickets efficiently
5. **Maintainability**: Single script replaces 7 individual scripts
