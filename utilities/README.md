# Zendesk Utilities

This directory contains utility scripts for managing Zendesk data synchronization and maintenance tasks.

## Scripts Overview

### sync_customers_managed_support.py

**Purpose**: Synchronizes `customers.json` with Zendesk organizations that have managed support plans, ensuring authorized email lists are always up-to-date.

**Key Features**:
- **Persistent Cache Management**: Backs up all users and organizations to local cache
- **Managed Support Detection**: Identifies organizations with `managed_support` or `managed_support_premium` tags
- **Automatic Email Updates**: Maintains current authorized email lists for each organization
- **Incremental Updates**: Only updates customers when data has actually changed
- **Data Preservation**: Never overwrites custom fields or existing customer data

#### How It Works

1. **Authentication & Setup**
   - Uses Google Cloud Secret Manager for Zendesk API token
   - Sets up rate-limited API session (350 req/min limit)

2. **Data Backup Phase**
   - Downloads all users to `persistent_cache/users/`
   - Downloads all organizations to `persistent_cache/organizations/`
   - Stores each record as individual JSON files

3. **Data Processing Phase**
   - Scans organization tags for managed support indicators:
     - `managed_support` → "Essential Support Plan"
     - `managed_support_premium` → "Premium Support Plan"
   - Matches organizations to users via `organization_id`
   - Filters for active users with valid email addresses

4. **customers.json Updates**
   - **New Customers**: Adds organizations with managed support tags
   - **Email Updates**: Refreshes authorized_emails arrays
   - **Sorting**: Automatically sorts all customers alphabetically by name (case-insensitive)
   - **Metadata**: Adds timestamps and change tracking
   - **Preservation**: Maintains existing custom fields

#### Data Structure

The script expects `customers.json` with this structure:
```json
{
  "customers": [
    {
      "name": "Organization Name",
      "organization_id": 12345,
      "authorized_emails": ["user@domain.com", "admin@domain.com"],
      "domains": ["domain.com"],
      "plans": {
        "software": "Microsoft 365",
        "support": "Essential Support Plan"
      },
      "trading_names": ["Alternative Name"],
      "tags": ["managed_support"],
      "updated_at": "2024-01-15T10:30:00Z",
      "support_tag": "managed_support"
    }
  ],
  "last_updated": "2024-01-15T10:30:00Z",
  "total_customers": 15,
  "managed_support_summary": {
    "new_customers": 3,
    "updated_customers": 5,
    "total_organizations": 15
  }
}
```

#### Usage

```bash
# From the utilities directory
python sync_customers_managed_support.py

# Or from the project root
python utilities/sync_customers_managed_support.py
```

#### Requirements

- Python 3.7+
- Google Cloud SDK configured with Secret Manager access
- `customers.json` file located at: `C:\Users\AngusMcLauchlan\Projects\itsolver\gsuitedev\Prompting\Claude\IT Solver\customers.json`
- Zendesk API access with organization and user read permissions
- Persistent cache directory (auto-created)

#### Dependencies

- `requests` - HTTP client for Zendesk API
- `json` - JSON file handling
- `os` - File system operations
- `time` - Rate limiting delays
- `threading` - Thread-safe rate limiter
- `datetime` - Timestamp handling

#### Configuration

The script uses these configuration values (defined in the script):

```python
LOCAL_CACHE_PATH = os.environ.get("LOCAL_CACHE_PATH", r"C:\Users\...\Cache\Zendesk_backups")
CUSTOMERS_FILE = r"C:\Users\AngusMcLauchlan\Projects\itsolver\gsuitedev\Prompting\Claude\IT Solver\customers.json"
MAX_REQUESTS_PER_MINUTE = 350  # Zendesk API rate limit
```

#### Error Handling

- **Rate Limiting**: Automatic retry with exponential backoff for 429 responses
- **API Failures**: Detailed error logging with response preview
- **File I/O**: Graceful handling of file access issues
- **JSON Parsing**: Robust error handling for malformed data
- **Network Issues**: Retry logic for transient failures

#### Output & Logging

The script provides detailed console output:
- Progress indicators for each phase
- Summary statistics (users cached, organizations processed, etc.)
- Change tracking (new vs updated customers)
- Error messages with context
- Final completion summary with timing

#### Cache Structure

```
persistent_cache/
├── users/
│   ├── 123.json
│   ├── 124.json
│   └── ...
├── organizations/
│   ├── 456.json
│   ├── 457.json
│   └── ...
└── persistent_cache/  # Working directory
```

#### Troubleshooting

**Common Issues**:
1. **Authentication Failed**: Check Google Cloud credentials and Secret Manager access
2. **Rate Limited**: Script handles this automatically, but may take longer
3. **Permission Denied**: Ensure Zendesk API token has organization and user read permissions
4. **File Not Found**: Script will create cache directories automatically

**Debug Mode**: Add print statements or use a debugger to inspect API responses

#### Future Improvements

Potential enhancements for the script:
- Command-line arguments for custom file paths
- Dry-run mode to preview changes
- Email validation and duplicate detection
- Organization hierarchy support
- Integration with external user management systems
- Automated scheduling (cron/celery)
- Webhook integration for real-time updates
- Multi-threaded processing for large datasets
- Configuration file support
- Email notification on sync completion/errors

#### Integration Notes

This script is designed to work alongside the main `backup_zendesk_all.py` script:
- Uses the same cache directory structure
- Follows the same authentication pattern
- Implements compatible rate limiting
- Can be scheduled to run after full backups

#### Maintenance

**Regular Tasks**:
- Monitor cache directory size
- Review sync logs for errors
- Update managed support tag mappings as needed
- Validate customers.json integrity after changes

**Version History**:
- v1.0: Initial implementation with basic sync functionality
- Future: Enhanced error handling and performance optimizations

---

### delete_spam_users.py

**Purpose**: Identifies and optionally deletes spam users from Zendesk based on name patterns.

**Usage**: Run with `--live` flag to actually delete users, otherwise runs in dry-run mode.

### generate_filtered_tickets_report.py

**Purpose**: Generates CSV reports of tickets filtered by organization, date range, and tags.

**Usage**: Configure filters at the top of the script and run to generate reports.

### redact_email_footers.py

**Purpose**: Redacts email disclaimer text from Zendesk ticket comments using the Zendesk Comment Redaction API.

**Features**:
- Rate-limited API calls
- Multiple matching strategies for HTML content
- Dry-run mode for testing
- Configurable disclaimer text

---

## Directory Structure

```
utilities/
├── README.md                    # This documentation
├── sync_customers_managed_support.py
├── delete_spam_users.py
├── generate_filtered_tickets_report.py
├── redact_email_footers.py
└── enrich_org_ids.py
```

## Common Configuration

All scripts share these configuration requirements:
- Zendesk subdomain and user from `config.py`
- Google Cloud Secret Manager for API tokens
- Local cache directory for data storage
- Rate limiting to respect Zendesk API limits

## Best Practices

1. **Always test in dry-run mode first**
2. **Monitor API rate limits during bulk operations**
3. **Keep cache directories clean and monitored**
4. **Review script output for errors regularly**
5. **Maintain backups of critical data before bulk operations**
6. **Use version control for script modifications**
7. **Document any custom changes or configurations**
