import requests
import json
import os
import time
import csv
import shutil
import re
import unicodedata
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version, test_gcloud_access

# Configuration
LOCAL_CACHE_PATH = os.environ.get("LOCAL_CACHE_PATH", r"C:\Users\AngusMcLauchlan\AppData\Local\ITSolver\Cache\Zendesk_backups")
ONEDRIVE_BACKUP_PATH = os.environ.get("BACKUP_PATH", r"C:\Users\AngusMcLauchlan\IT Solver\IT Solver - Documents\Admin\Suppliers\Zendesk\Backups")
# Note: We no longer use START_TIME since we don't do incremental backups
BATCH_SIZE = 100  # Process items in batches to reduce memory usage

# Note: We no longer use incremental backups based on last run time
# Instead, we always backup all tickets but use local caching to avoid re-downloading unchanged ones

# Initialize session
print("Config loaded!")

# Test Google Cloud access before attempting to use Secret Manager
if not test_gcloud_access():
    print("ERROR: Cannot access Google Cloud Secret Manager.")
    print("Please ensure:")
    print("1. GOOGLE_APPLICATION_CREDENTIALS environment variable is set")
    print("2. You have access to the 'billing-sync' project")
    print("3. You have Secret Manager permissions")
    exit(1)

zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")
session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)

def slugify(value, allow_unicode=False):
    """Convert to filename-safe string."""
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')

def create_directory(path):
    """Create directory if it doesn't exist."""
    os.makedirs(path, exist_ok=True)

# Note: backup state functions removed since we no longer use incremental backups

def is_item_cached_and_current(file_path, updated_at):
    """Check if an item is cached locally and up to date."""
    if not os.path.exists(file_path):
        return False
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            cached_item = json.load(f)
            
            # If the ticket is closed, it will not be updated further.
            if cached_item.get('status') == 'closed':
                return True
                
            cached_updated_at = cached_item.get('updated_at', '')
            return cached_updated_at == updated_at
    except (json.JSONDecodeError, IOError, KeyError):
        return False

def handle_rate_limit(response):
    """Handle API rate limiting."""
    if response.status_code == 429:
        retry_after = int(response.headers.get('retry-after', 60))
        print(f'Rate limited. Waiting for {retry_after} seconds.')
        time.sleep(retry_after)
        return True
    return False

def fetch_data(endpoint):
    """Fetch data from API endpoint with rate limiting."""
    while True:
        response = session.get(endpoint)
        if handle_rate_limit(response):
            continue
        if response.status_code != 200:
            # Print first 500 chars of response for debugging
            resp_preview = response.text[:500] if response.text else ''
            print(
                f"[DEBUG] Non-200 from {endpoint} → {response.status_code}\n"
                f"Headers: {dict(response.headers)}\n"
                f"Body preview: {resp_preview}"
            )
            raise Exception(
                f'Failed to retrieve data from {endpoint} with error {response.status_code}'
            )
        return response.json()

def write_log(path, log_data, headers):
    """Write CSV log file."""
    with open(os.path.join(path, '_log.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(('Backup Date', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        writer.writerow(headers)
        writer.writerows(log_data)

def backup_tickets(backup_path, cache_path):
    """Backup all tickets with events using persistent local cache."""
    print("=== Backing up Tickets ===")
    
    # Set up directories
    cache_tickets_path = os.path.join(cache_path, "tickets")
    backup_tickets_path = os.path.join(backup_path, "tickets")
    create_directory(cache_tickets_path)
    create_directory(backup_tickets_path)
    
    # Get current ticket IDs and clean cache
    current_ticket_ids = get_all_ticket_ids()
    clean_cache_directory(cache_tickets_path, current_ticket_ids, 'tickets')
    
    # Always backup all tickets, but use caching to avoid re-downloading unchanged ones
    tickets_endpoint = f"https://{zendesk_subdomain}/api/v2/tickets.json?include=comment_count&per_page=100"
    log = []
    total_cached = 0
    total_downloaded = 0
    
    print("Starting complete ticket backup (using cache for unchanged tickets)")
    
    def get_ticket_events(ticket_id):
        """Get all events for a ticket."""
        events_endpoint = f"https://{zendesk_subdomain}/api/v2/tickets/{ticket_id}/audits.json"
        events = []
        while events_endpoint:
            response = session.get(events_endpoint)
            if response.status_code == 429:
                time.sleep(int(response.headers.get("retry-after", 60)))
                continue
            if response.status_code != 200:
                print(f"Failed to get events for ticket {ticket_id}")
                break
            data = response.json()
            events.extend(data["audits"])
            events_endpoint = data.get("next_page")
        return events
    
    def process_ticket(ticket):
        """Process and save a single ticket."""
        nonlocal total_cached, total_downloaded
        ticket_id = str(ticket["id"])
        
        # Skip if ticket was deleted in Zendesk
        if ticket_id not in current_ticket_ids:
            return None
            
        filename = f"{ticket_id}.json"
        cache_file_path = os.path.join(cache_tickets_path, filename)
        backup_file_path = os.path.join(backup_tickets_path, filename)
        
        updated_at = ticket.get("updated_at", "")
        
        # Check if ticket is already cached and current
        if is_item_cached_and_current(cache_file_path, updated_at):
            # Copy from cache to backup
            try:
                shutil.copy2(cache_file_path, backup_file_path)
                total_cached += 1
                if total_cached % 100 == 0:
                    print(f"Cached tickets: {total_cached}")
                return (filename, ticket.get("subject", ""), ticket.get("created_at"), updated_at, "cached")
            except (IOError, OSError) as e:
                print(f"Failed to copy cached {filename}: {e}")
        
        # Fetch events and download
        try:
            events = get_ticket_events(ticket_id)
            ticket["events"] = events
            
            # Save to cache
            with open(cache_file_path, "w", encoding="utf-8") as ticket_file:
                json.dump(ticket, ticket_file, indent=2)
            
            # Copy to backup
            shutil.copy2(cache_file_path, backup_file_path)
            
            total_downloaded += 1
            if total_downloaded % 25 == 0:
                print(f"Downloaded tickets: {total_downloaded}, Cached: {total_cached}")
            
            return (filename, ticket.get("subject", ""), ticket.get("created_at"), updated_at, "downloaded")
        except (IOError, OSError) as e:
            print(f"Failed to save {filename}: {e}")
            return (filename, ticket.get("subject", ""), ticket.get("created_at"), updated_at, "error")
    
    page_count = 0
    while tickets_endpoint:
        page_count += 1
        response = session.get(tickets_endpoint)
        if response.status_code == 429:
            time.sleep(int(response.headers.get("retry-after", 60)))
            continue
        if response.status_code != 200:
            print(f"Failed to retrieve tickets with error {response.status_code}")
            break
        
        data = response.json()
        if not data["tickets"]:
            print(f"No tickets found on page {page_count}")
            break
        
        print(f"Processing tickets page {page_count}: {len(data['tickets'])} tickets")
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(process_ticket, data["tickets"]))
            # Filter out None results (deleted tickets)
            log.extend([r for r in results if r is not None])
        
        tickets_endpoint = data.get("next_page")
        if tickets_endpoint:
            print(f"Moving to next page: {page_count + 1}")
    
    # Write log to backup directory
    write_log(backup_tickets_path, log, ("File", "Subject", "Date Created", "Date Updated", "Status"))
    print(f"Tickets backup completed: {len(log)} tickets processed ({total_downloaded} downloaded, {total_cached} cached)")
    return log

def backup_users(backup_path, cache_path):
    """Backup all users using persistent local cache."""
    print("=== Backing up Users ===")
    
    # Set up directories
    cache_users_path = os.path.join(cache_path, "users")
    backup_users_path = os.path.join(backup_path, "users")
    create_directory(cache_users_path)
    create_directory(backup_users_path)
    
    # Get current user IDs and clean cache
    current_user_ids = get_current_item_ids('users')
    clean_cache_directory(cache_users_path, current_user_ids, 'users')
    
    users_endpoint = f"https://{zendesk_subdomain}/api/v2/users.json?per_page=100"
    log = []
    total_cached = 0
    total_downloaded = 0
    
    def process_user(user):
        """Process and save a single user."""
        nonlocal total_cached, total_downloaded
        user_id = str(user['id'])
        
        # Skip if user was deleted in Zendesk
        if user_id not in current_user_ids:
            return None
            
        filename = f"{user_id}.json"
        cache_file_path = os.path.join(cache_users_path, filename)
        backup_file_path = os.path.join(backup_users_path, filename)
        
        # Check if file exists in cache and is up to date
        if os.path.exists(cache_file_path):
            try:
                with open(cache_file_path, 'r', encoding='utf-8') as f:
                    existing_user = json.load(f)
                existing_updated_at = datetime.fromisoformat(existing_user['updated_at'].rstrip('Z'))
                current_updated_at = datetime.fromisoformat(user['updated_at'].rstrip('Z'))
                
                if existing_updated_at >= current_updated_at:
                    # Copy from cache to backup
                    try:
                        shutil.copy2(cache_file_path, backup_file_path)
                        total_cached += 1
                        if total_cached % 50 == 0:
                            print(f"Cached users: {total_cached}")
                        return (filename, user['name'], user['created_at'], user['updated_at'], 'cached')
                    except (IOError, OSError) as e:
                        print(f"Failed to copy cached {filename}: {e}")
            except Exception as e:
                print(f"Error reading cached {filename}: {e}")
        
        # Save user to cache and backup
        try:
            # Save to cache
            with open(cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(user, f, indent=2)
            
            # Copy to backup
            shutil.copy2(cache_file_path, backup_file_path)
            
            total_downloaded += 1
            if total_downloaded % 25 == 0:
                print(f"Downloaded users: {total_downloaded}, Cached: {total_cached}")
            
            return (filename, user['name'], user['created_at'], user['updated_at'], 'downloaded')
        except Exception as e:
            print(f"Failed to save {filename}: {e}")
            return (filename, user['name'], user['created_at'], user['updated_at'], 'error')
    
    page_count = 0
    while users_endpoint:
        page_count += 1
        data = fetch_data(users_endpoint)
        
        print(f"Processing users page {page_count}: {len(data['users'])} users")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_user, data['users']))
            # Filter out None results (deleted users)
            log.extend([r for r in results if r is not None])
        
        users_endpoint = data.get('next_page')
        if users_endpoint:
            print(f"Moving to next users page: {page_count + 1}")
    
    write_log(backup_users_path, log, ("File", "Name", "Date Created", "Date Updated", "Status"))
    print(f"Users backup completed: {len(log)} users processed ({total_downloaded} downloaded, {total_cached} cached)")
    return log

def backup_organizations(backup_path, cache_path):
    """Backup all organizations using persistent local cache."""
    print("=== Backing up Organizations ===")
    
    # Set up directories
    cache_orgs_path = os.path.join(cache_path, "organizations")
    backup_orgs_path = os.path.join(backup_path, "organizations")
    create_directory(cache_orgs_path)
    create_directory(backup_orgs_path)
    
    # Get current organization IDs and clean cache
    current_org_ids = get_current_item_ids('organizations')
    clean_cache_directory(cache_orgs_path, current_org_ids, 'organizations')
    
    orgs_endpoint = f"https://{zendesk_subdomain}/api/v2/organizations.json?per_page=100"
    log = []
    total_cached = 0
    total_downloaded = 0
    
    def process_organization(org):
        """Process and save a single organization."""
        nonlocal total_cached, total_downloaded
        org_id = str(org['id'])
        
        # Skip if organization was deleted in Zendesk
        if org_id not in current_org_ids:
            return None
            
        filename = f"{org_id}.json"
        cache_file_path = os.path.join(cache_orgs_path, filename)
        backup_file_path = os.path.join(backup_orgs_path, filename)
        
        # Check if file exists in cache and is up to date
        if os.path.exists(cache_file_path):
            try:
                with open(cache_file_path, 'r', encoding='utf-8') as f:
                    existing_org = json.load(f)
                existing_updated_at = datetime.fromisoformat(existing_org['updated_at'].rstrip('Z'))
                current_updated_at = datetime.fromisoformat(org['updated_at'].rstrip('Z'))
                
                if existing_updated_at >= current_updated_at:
                    # Copy from cache to backup
                    try:
                        shutil.copy2(cache_file_path, backup_file_path)
                        total_cached += 1
                        if total_cached % 25 == 0:
                            print(f"Cached organizations: {total_cached}")
                        return (filename, org['name'], org['created_at'], org['updated_at'], 'cached')
                    except (IOError, OSError) as e:
                        print(f"Failed to copy cached {filename}: {e}")
            except Exception as e:
                print(f"Error reading cached {filename}: {e}")
        
        # Save organization to cache and backup
        try:
            # Save to cache
            with open(cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(org, f, indent=2)
            
            # Copy to backup
            shutil.copy2(cache_file_path, backup_file_path)
            
            total_downloaded += 1
            if total_downloaded % 10 == 0:
                print(f"Downloaded organizations: {total_downloaded}, Cached: {total_cached}")
            
            return (filename, org['name'], org['created_at'], org['updated_at'], 'downloaded')
        except Exception as e:
            print(f"Failed to save {filename}: {e}")
            return (filename, org['name'], org['updated_at'], org['updated_at'], 'error')
    
    page_count = 0
    while orgs_endpoint:
        page_count += 1
        data = fetch_data(orgs_endpoint)
        
        print(f"Processing organizations page {page_count}: {len(data['organizations'])} organizations")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_organization, data['organizations']))
            # Filter out None results (deleted organizations)
            log.extend([r for r in results if r is not None])
        
        orgs_endpoint = data.get('next_page')
        if orgs_endpoint:
            print(f"Moving to next organizations page: {page_count + 1}")
    
    write_log(backup_orgs_path, log, ("File", "Name", "Date Created", "Date Updated", "Status"))
    print(f"Organizations backup completed: {len(log)} organizations processed ({total_downloaded} downloaded, {total_cached} cached)")
    return log

def backup_guide_articles(backup_path, cache_path):
    """Backup all Guide articles using persistent local cache."""
    print("=== Backing up Guide Articles ===")
    
    # Set up directories
    cache_articles_path = os.path.join(cache_path, "guide_articles")
    backup_articles_path = os.path.join(backup_path, "guide_articles")
    create_directory(cache_articles_path)
    create_directory(backup_articles_path)
    
    # Get current article IDs and clean cache
    current_article_ids = get_current_item_ids('articles')
    clean_cache_directory(cache_articles_path, current_article_ids, 'articles')
    
    articles_endpoint = f"https://{zendesk_subdomain}/api/v2/help_center/articles.json?per_page=100"
    log = []
    total_cached = 0
    total_downloaded = 0
    
    def process_article(article):
        """Process and save a single article."""
        nonlocal total_cached, total_downloaded
        article_id = str(article['id'])
        
        # Skip if article was deleted in Zendesk
        if article_id not in current_article_ids:
            return None
            
        filename = f"{article_id}.json"
        cache_file_path = os.path.join(cache_articles_path, filename)
        backup_file_path = os.path.join(backup_articles_path, filename)
        
        # Check if file exists in cache and is up to date
        if os.path.exists(cache_file_path):
            try:
                with open(cache_file_path, 'r', encoding='utf-8') as f:
                    existing_article = json.load(f)
                existing_updated_at = datetime.fromisoformat(existing_article['updated_at'].rstrip('Z'))
                current_updated_at = datetime.fromisoformat(article['updated_at'].rstrip('Z'))
                
                if existing_updated_at >= current_updated_at:
                    # Copy from cache to backup
                    try:
                        shutil.copy2(cache_file_path, backup_file_path)
                        total_cached += 1
                        if total_cached % 10 == 0:
                            print(f"Cached articles: {total_cached}")
                        return (filename, article['title'], article['created_at'], article['updated_at'], 'cached')
                    except (IOError, OSError) as e:
                        print(f"Failed to copy cached {filename}: {e}")
            except Exception as e:
                print(f"Error reading cached {filename}: {e}")
        
        # Fetch full article details and save to cache and backup
        try:
            article_endpoint = f"https://{zendesk_subdomain}/api/v2/help_center/articles/{article_id}.json"
            response = session.get(article_endpoint)
            if response.status_code != 200:
                print(f'Failed to retrieve article {article_id} with error {response.status_code}')
                return (filename, article['title'], article['created_at'], article['updated_at'], 'error')
            
            full_article = response.json()['article']
            
            # Save to cache
            with open(cache_file_path, 'w', encoding='utf-8') as article_file:
                json.dump(full_article, article_file, indent=2)
            
            # Copy to backup
            shutil.copy2(cache_file_path, backup_file_path)
            
            total_downloaded += 1
            if total_downloaded % 5 == 0:
                print(f"Downloaded articles: {total_downloaded}, Cached: {total_cached}")
            
            return (filename, full_article['title'], full_article['created_at'], full_article['updated_at'], 'downloaded')
        except (IOError, OSError, requests.RequestException) as e:
            print(f"Failed to save {filename}: {e}")
            return (filename, article['title'], article['created_at'], article['updated_at'], 'error')
    
    page_count = 0
    while articles_endpoint:
        page_count += 1
        data = fetch_data(articles_endpoint)
        
        print(f"Processing articles page {page_count}: {len(data['articles'])} articles")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_article, data['articles']))
            # Filter out None results (deleted articles)
            log.extend([r for r in results if r is not None])
        
        articles_endpoint = data.get('next_page')
        if articles_endpoint:
            print(f"Moving to next articles page: {page_count + 1}")
    
    write_log(backup_articles_path, log, ("File", "Title", "Date Created", "Date Updated", "Status"))
    print(f"Guide articles backup completed: {len(log)} articles processed ({total_downloaded} downloaded, {total_cached} cached)")
    return log

def backup_support_assets(backup_path, cache_path):
    """Backup all support assets (triggers, automations, macros, etc.) using persistent local cache."""
    print("=== Backing up Support Assets ===")
    
    # Set up directories  
    cache_assets_path = os.path.join(cache_path, "support_assets")
    backup_assets_path = os.path.join(backup_path, "support_assets")
    create_directory(cache_assets_path)
    create_directory(backup_assets_path)
    
    # Define asset types with their API endpoints and response keys
    asset_types = {
        'apps/installations': {'name': 'app_installations', 'response_key': 'installations'},
        'automations': {'name': 'automations', 'response_key': 'automations'},
        'macros': {'name': 'macros', 'response_key': 'macros'},
        'organization_fields': {'name': 'organization_fields', 'response_key': 'organization_fields'},
        'ticket_fields': {'name': 'ticket_fields', 'response_key': 'ticket_fields'},
        'triggers': {'name': 'triggers', 'response_key': 'triggers'},
        'user_fields': {'name': 'user_fields', 'response_key': 'user_fields'},
        'views': {'name': 'views', 'response_key': 'views'}
    }
    
    all_logs = []
    
    for endpoint, config in asset_types.items():
        asset_name = config['name']
        response_key = config['response_key']
        cache_asset_type_path = os.path.join(cache_assets_path, asset_name)
        backup_asset_type_path = os.path.join(backup_assets_path, asset_name)
        create_directory(cache_asset_type_path)
        create_directory(backup_asset_type_path)
        
        print(f"Backing up {asset_name}...")
        endpoint_url = f"https://{zendesk_subdomain}/api/v2/{endpoint}.json?per_page=100"
        log = []
        
        def backup_asset(asset, asset_type, cache_path, backup_path):
            """Backup a single asset."""
            # Determine the title key based on asset type
            title_key = 'name' if asset_type in ['triggers', 'automations', 'macros', 'views'] else 'title'
            
            # Try to find a valid title
            title = None
            for key in [title_key, 'name', 'title', 'label', 'id']:
                if key in asset and asset[key]:
                    title = str(asset[key])
                    break
            
            if not title:
                title = f"untitled_{asset.get('id', 'unknown')}"
            
            safe_title = slugify(title)
            filename = f"{safe_title}.json"
            cache_file_path = os.path.join(cache_path, filename)
            backup_file_path = os.path.join(backup_path, filename)
            
            try:
                # Save to cache
                with open(cache_file_path, 'w', encoding='utf-8') as f:
                    json.dump(asset, f, indent=2)
                
                # Copy to backup
                shutil.copy2(cache_file_path, backup_file_path)
                
                return (filename, title, asset.get('active', True), asset.get('created_at'), asset.get('updated_at'))
            except Exception as e:
                print(f"Error saving {filename}: {e}")
                return (f"error_{asset.get('id', 'unknown')}.json", f"ERROR: {str(e)}", False, None, None)
        
        page_count = 0
        while endpoint_url:
            page_count += 1
            data = fetch_data(endpoint_url)
            
            print(f"Processing {asset_name} page {page_count}: {len(data[response_key])} items")
            
            for asset in data[response_key]:
                try:
                    result = backup_asset(asset, asset_name, cache_asset_type_path, backup_asset_type_path)
                    log.append(result)
                except (IOError, OSError, json.JSONDecodeError) as e:
                    print(f"Error processing asset {asset.get('id', 'unknown')}: {str(e)}")
                    log.append((f"error_{asset.get('id', 'unknown')}.json", f"ERROR: {str(e)}", False, None, None))
            
            endpoint_url = data.get('next_page')
            if endpoint_url:
                print(f"Moving to next {asset_name} page: {page_count + 1}")
        
        write_log(backup_asset_type_path, log, ("File", "Title", "Active", "Date Created", "Date Updated"))
        all_logs.extend([(asset_name, *entry) for entry in log])
        print(f"{asset_name} backup completed: {len(log)} items processed")
    
    # Write master log for all support assets
    master_log_path = os.path.join(backup_assets_path, '_master_log.csv')
    with open(master_log_path, 'w', newline='', encoding='utf-8') as master_file:
        writer = csv.writer(master_file)
        writer.writerow(('Backup Date', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        writer.writerow(('Asset Type', 'File', 'Title', 'Active', 'Date Created', 'Date Updated'))
        writer.writerows(all_logs)
    
    print(f"Support assets backup completed: {len(all_logs)} total items processed")
    return all_logs

def create_backup_zip(backup_path, zip_path):
    """Create a zip file of the backup directory."""
    print(f"Creating zip file: {zip_path}")
    shutil.make_archive(zip_path.replace('.zip', ''), 'zip', backup_path)
    print(f"Zip file created successfully: {zip_path}")

def get_current_item_ids(endpoint_type):
    """Get list of current item IDs from Zendesk API (without full data)."""
    print(f"Getting current {endpoint_type} IDs from Zendesk...")
    
    # Use per_page=100 to maximize items per request and reduce API calls
    endpoints = {
        'tickets': f"https://{zendesk_subdomain}/api/v2/tickets.json?include=comment_count&per_page=100",
        'users': f"https://{zendesk_subdomain}/api/v2/users.json?per_page=100", 
        'organizations': f"https://{zendesk_subdomain}/api/v2/organizations.json?per_page=100",
        'articles': f"https://{zendesk_subdomain}/api/v2/help_center/articles.json?per_page=100"
    }
    
    if endpoint_type not in endpoints:
        return set()
    
    current_ids = set()
    endpoint = endpoints[endpoint_type]
    page_count = 0
    
    while endpoint:
        page_count += 1
        response = session.get(endpoint)
        if response.status_code == 429:
            time.sleep(int(response.headers.get("retry-after", 60)))
            continue
        if response.status_code != 200:
            print(f"Failed to get {endpoint_type} IDs: {response.status_code}")
            break
            
        data = response.json()
        items = data.get(endpoint_type, [])
        
        if not items:
            print(f"No items found on page {page_count}")
            break
            
        for item in items:
            current_ids.add(str(item['id']))
        
        print(f"Page {page_count}: Found {len(items)} {endpoint_type} (Total so far: {len(current_ids)})")
            
        endpoint = data.get('next_page')
    
    print(f"Found {len(current_ids)} current {endpoint_type} across {page_count} pages")
    return current_ids

# ---------------------------------------------------------------------------
# Ticket archive handling
# ---------------------------------------------------------------------------

def get_all_ticket_ids():
    """Return *all* ticket IDs (including archived ones) using Incremental Cursor Export.

    Zendesk moves closed-for-120-days tickets into the *archive*. These tickets
    never appear in the regular /tickets.json collection.  The incremental
    export endpoints are the only supported way to fetch them.  We iterate over
    the cursor-based export until `meta.has_more` is False.
    """

    # Max 1000 tickets per page – recommended by Zendesk docs
    url = (
        f"https://{zendesk_subdomain}/api/v2/incremental/tickets/"
        f"cursor.json?start_time=0&page[size]=1000"
    )

    all_ids: set[str] = set()
    page = 0

    tried_cursor = True
    while url:
        page += 1
        response = session.get(url)

        if response.status_code == 429:
            # Rate-limit – respect Retry-After header
            retry_after = int(response.headers.get("retry-after", 60))
            print(f"[tickets-export] Rate limited. Sleeping {retry_after}s …")
            time.sleep(retry_after)
            continue

        if response.status_code != 200:
            print(
                f"[tickets-export] Cursor export failed (status {response.status_code})."
            )
            # fallback to classic incremental export one time
            if tried_cursor:
                tried_cursor = False
                url = (
                    f"https://{zendesk_subdomain}/api/v2/incremental/tickets.json?start_time=0"
                )
                print("[tickets-export] Falling back to incremental export …")
                page = 0
                continue
            else:
                break

        data = response.json()
        tickets = data.get("tickets", [])

        for t in tickets:
            all_ids.add(str(t["id"]))

        print(
            f"[tickets-export] Page {page}: got {len(tickets)} tickets – total so far {len(all_ids)}"
        )

        if tried_cursor:
            url = (
                data.get("links", {}).get("next")
                if data.get("meta", {}).get("has_more")
                else None
            )
        else:
            url = data.get("next_page")

    print(f"[tickets-export] Total tickets collected: {len(all_ids)}")
    return all_ids

def clean_cache_directory(cache_dir, current_ids, item_type):
    """Remove cached items that no longer exist in Zendesk."""
    if not os.path.exists(cache_dir):
        return 0
        
    removed_count = 0
    print(f"Cleaning {item_type} cache directory...")
    
    for filename in os.listdir(cache_dir):
        if filename.endswith('.json') and not filename.startswith('_'):
            # Extract ID from filename (e.g., "12345.json" -> "12345")
            item_id = filename.replace('.json', '')
            
            if item_id not in current_ids:
                file_path = os.path.join(cache_dir, filename)
                try:
                    os.remove(file_path)
                    removed_count += 1
                    print(f"Removed deleted {item_type} from cache: {filename}")
                except OSError as e:
                    print(f"Failed to remove {filename}: {e}")
    
    print(f"Removed {removed_count} stale {item_type} from cache")
    return removed_count

def main():
    """Main backup function with persistent local caching."""
    print("=== Starting Zendesk Complete Backup ===")
    start_time = datetime.now()
    current_date = start_time.strftime("%Y-%m-%d_%H-%M-%S")
    
    # Create persistent cache directory (no date in name)
    persistent_cache_path = os.path.join(LOCAL_CACHE_PATH, "persistent_cache")
    create_directory(persistent_cache_path)
    
    # Create dated backup directory for the final backup
    backup_dir_name = f"zendesk_backup_{current_date}"
    backup_path = os.path.join(LOCAL_CACHE_PATH, backup_dir_name)
    create_directory(backup_path)
    
    print(f"Persistent cache directory: {persistent_cache_path}")
    print(f"Current backup directory: {backup_path}")
    print(f"OneDrive sync directory: {ONEDRIVE_BACKUP_PATH}")
    
    # Backup all asset types using persistent local cache
    try:
        print("\n--- Using persistent local cache for improved performance ---")
        tickets_log = backup_tickets(backup_path, persistent_cache_path)
        
        users_log = backup_users(backup_path, persistent_cache_path)
        orgs_log = backup_organizations(backup_path, persistent_cache_path)
        articles_log = backup_guide_articles(backup_path, persistent_cache_path)
        assets_log = backup_support_assets(backup_path, persistent_cache_path)
        
        # Create summary log
        summary_path = os.path.join(backup_path, '_backup_summary.txt')
        with open(summary_path, 'w', encoding='utf-8') as summary_file:
            summary_file.write("Zendesk Complete Backup Summary\n")
            summary_file.write(f"Backup Date: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            summary_file.write(f"Zendesk Subdomain: {zendesk_subdomain}\n\n")
            
            # Count cache vs download stats from logs
            total_items = len(tickets_log) + len(users_log) + len(orgs_log) + len(articles_log) + len(assets_log)
            cached_items = sum(1 for log in [tickets_log, users_log, orgs_log, articles_log] for item in log if len(item) > 4 and item[4] == 'cached')
            downloaded_items = sum(1 for log in [tickets_log, users_log, orgs_log, articles_log] for item in log if len(item) > 4 and item[4] == 'downloaded')
            
            summary_file.write(f"Tickets: {len(tickets_log)} processed\n")
            summary_file.write(f"Users: {len(users_log)} processed\n")
            summary_file.write(f"Organizations: {len(orgs_log)} processed\n")
            summary_file.write(f"Guide Articles: {len(articles_log)} processed\n")
            summary_file.write(f"Support Assets: {len(assets_log)} processed\n\n")
            summary_file.write(f"Total items: {total_items}\n")
            summary_file.write(f"Cache efficiency: {cached_items} cached, {downloaded_items} downloaded\n")
            if total_items > 0:
                cache_rate = (cached_items / (cached_items + downloaded_items)) * 100 if (cached_items + downloaded_items) > 0 else 0
                summary_file.write(f"Cache hit rate: {cache_rate:.1f}%\n")
            
            end_time = datetime.now()
            duration = end_time - start_time
            summary_file.write(f"Backup Duration: {duration}\n")
            summary_file.write(f"Backup Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Create zip file in local cache first
        zip_filename = f"zendesk_backup_{current_date}.zip"
        local_zip_path = os.path.join(LOCAL_CACHE_PATH, zip_filename)
        create_backup_zip(backup_path, local_zip_path)
        
        # Copy zip file to OneDrive sync folder (only one file to sync)
        create_directory(ONEDRIVE_BACKUP_PATH)
        onedrive_zip_path = os.path.join(ONEDRIVE_BACKUP_PATH, zip_filename)
        shutil.copy2(local_zip_path, onedrive_zip_path)
        print(f"Copied zip file to OneDrive sync folder: {onedrive_zip_path}")
        
        # Clean up working directory
        if os.path.exists(local_zip_path):
            shutil.rmtree(backup_path)
            print(f"Cleaned up temporary directory: {backup_path}")
            print(f"Local zip file retained: {local_zip_path}")
        
        # Print final summary
        end_time = datetime.now()
        duration = end_time - start_time
        
        # Calculate cache efficiency
        total_items = len(tickets_log) + len(users_log) + len(orgs_log) + len(articles_log) + len(assets_log)
        cached_items = sum(1 for log in [tickets_log, users_log, orgs_log, articles_log] for item in log if len(item) > 4 and item[4] == 'cached')
        downloaded_items = sum(1 for log in [tickets_log, users_log, orgs_log, articles_log] for item in log if len(item) > 4 and item[4] == 'downloaded')
        cache_rate = (cached_items / (cached_items + downloaded_items)) * 100 if (cached_items + downloaded_items) > 0 else 0
        
        print("\n=== Backup Complete ===")
        print(f"Duration: {duration}")
        print(f"Total items backed up: {total_items}")
        print(f"Cache efficiency: {cached_items} cached, {downloaded_items} downloaded ({cache_rate:.1f}% cache hit rate)")
        print(f"Local zip file: {local_zip_path}")
        print(f"OneDrive zip file: {onedrive_zip_path}")
        print(f"Persistent cache directory: {persistent_cache_path}")
        
        return True
        
    except (IOError, OSError, requests.RequestException, json.JSONDecodeError) as e:
        print(f"Backup failed: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
