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
from secret_manager import access_secret_version

# Configuration
LOCAL_CACHE_PATH = os.environ.get("LOCAL_CACHE_PATH", r"C:\Users\AngusMcLauchlan\AppData\Local\ITSolver\Cache\Zendesk_backups")
ONEDRIVE_BACKUP_PATH = os.environ.get("BACKUP_PATH", r"C:\Users\AngusMcLauchlan\IT Solver\IT Solver - Documents\Admin\Business\Zendesk\Backups")
# Note: We no longer use START_TIME since we don't do incremental backups
BATCH_SIZE = 100  # Process items in batches to reduce memory usage

# Note: We no longer use incremental backups based on last run time
# Instead, we always backup all tickets but use local caching to avoid re-downloading unchanged ones

# Initialize session
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
            raise Exception(f'Failed to retrieve data from {endpoint} with error {response.status_code}')
        return response.json()

def write_log(path, log_data, headers):
    """Write CSV log file."""
    with open(os.path.join(path, '_log.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(('Backup Date', datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        writer.writerow(headers)
        writer.writerows(log_data)

def backup_tickets(backup_path):
    """Backup all tickets with events using local cache."""
    print("=== Backing up Tickets ===")
    tickets_path = os.path.join(backup_path, "tickets")
    create_directory(tickets_path)
    
    # Always backup all tickets, but use caching to avoid re-downloading unchanged ones
    tickets_endpoint = f"https://{zendesk_subdomain}/api/v2/tickets.json"
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
        ticket_id = ticket["id"]
        filename = f"{ticket_id}.json"
        file_path = os.path.join(tickets_path, filename)
        
        updated_at = ticket.get("updated_at", "")
        
        # Check if ticket is already cached and current
        if is_item_cached_and_current(file_path, updated_at):
            total_cached += 1
            if total_cached % 100 == 0:
                print(f"Cached tickets: {total_cached}")
            return (filename, ticket.get("subject", ""), ticket.get("created_at"), updated_at, "cached")
        
        # Note: We no longer track completed tickets in backup state
        # Instead, we rely on is_item_cached_and_current for all caching decisions
        
        # Fetch events
        events = get_ticket_events(ticket_id)
        ticket["events"] = events
        
        # Fetch events and download
        try:
            # Save ticket to cache
            with open(file_path, "w", encoding="utf-8") as ticket_file:
                json.dump(ticket, ticket_file, indent=2)
            
            # Note: We no longer track completed tickets in backup state
            total_downloaded += 1
            
            if total_downloaded % 25 == 0:
                print(f"Downloaded tickets: {total_downloaded}, Cached: {total_cached}")
            
            return (filename, ticket.get("subject", ""), ticket.get("created_at"), updated_at, "downloaded")
        except (IOError, OSError) as e:
            print(f"Failed to save {filename}: {e}")
            return (filename, ticket.get("subject", ""), ticket.get("created_at"), updated_at, "error")
    
    while tickets_endpoint:
        response = session.get(tickets_endpoint)
        if response.status_code == 429:
            time.sleep(int(response.headers.get("retry-after", 60)))
            continue
        if response.status_code != 200:
            print(f"Failed to retrieve tickets with error {response.status_code}")
            break
        
        data = response.json()
        if not data["tickets"]:
            break
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(process_ticket, data["tickets"]))
            log.extend(results)
        
        tickets_endpoint = data.get("next_page")
    
    # Write log
    write_log(tickets_path, log, ("File", "Subject", "Date Created", "Date Updated", "Status"))
    print(f"Tickets backup completed: {len(log)} tickets processed ({total_downloaded} downloaded, {total_cached} cached)")
    return log

def backup_users(backup_path):
    """Backup all users."""
    print("=== Backing up Users ===")
    users_path = os.path.join(backup_path, "users")
    create_directory(users_path)
    
    users_endpoint = f"https://{zendesk_subdomain}/api/v2/users.json"
    log = []
    
    def process_user(user):
        """Process and save a single user."""
        user_id = user['id']
        filename = f"{user_id}.json"
        file_path = os.path.join(users_path, filename)
        
        # Check if file exists and is up to date
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    existing_user = json.load(f)
                existing_updated_at = datetime.fromisoformat(existing_user['updated_at'].rstrip('Z'))
                current_updated_at = datetime.fromisoformat(user['updated_at'].rstrip('Z'))
                
                if existing_updated_at >= current_updated_at:
                    print(f"{filename} is up to date, skipping.")
                    return (filename, user['name'], user['created_at'], user['updated_at'], 'skipped')
            except Exception as e:
                print(f"Error reading {filename}: {e}")
        
        # Save user
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(user, f, indent=2)
            print(f"{filename} - saved!")
            return (filename, user['name'], user['created_at'], user['updated_at'], 'backed_up')
        except Exception as e:
            print(f"Failed to save {filename}: {e}")
            return (filename, user['name'], user['created_at'], user['updated_at'], 'error')
    
    while users_endpoint:
        data = fetch_data(users_endpoint)
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_user, data['users']))
            log.extend(results)
        
        users_endpoint = data.get('next_page')
    
    write_log(users_path, log, ("File", "Name", "Date Created", "Date Updated", "Status"))
    print(f"Users backup completed: {len(log)} users processed")
    return log

def backup_organizations(backup_path):
    """Backup all organizations."""
    print("=== Backing up Organizations ===")
    orgs_path = os.path.join(backup_path, "organizations")
    create_directory(orgs_path)
    
    orgs_endpoint = f"https://{zendesk_subdomain}/api/v2/organizations.json"
    log = []
    
    def process_organization(org):
        """Process and save a single organization."""
        org_id = org['id']
        filename = f"{org_id}.json"
        file_path = os.path.join(orgs_path, filename)
        
        # Check if file exists and is up to date
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    existing_org = json.load(f)
                existing_updated_at = datetime.fromisoformat(existing_org['updated_at'].rstrip('Z'))
                current_updated_at = datetime.fromisoformat(org['updated_at'].rstrip('Z'))
                
                if existing_updated_at >= current_updated_at:
                    print(f"{filename} is up to date, skipping.")
                    return (filename, org['name'], org['created_at'], org['updated_at'], 'skipped')
            except Exception as e:
                print(f"Error reading {filename}: {e}")
        
        # Save organization
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(org, f, indent=2)
            print(f"{filename} - saved!")
            return (filename, org['name'], org['created_at'], org['updated_at'], 'backed_up')
        except Exception as e:
            print(f"Failed to save {filename}: {e}")
            return (filename, org['name'], org['created_at'], org['updated_at'], 'error')
    
    while orgs_endpoint:
        data = fetch_data(orgs_endpoint)
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_organization, data['organizations']))
            log.extend(results)
        
        orgs_endpoint = data.get('next_page')
    
    write_log(orgs_path, log, ("File", "Name", "Date Created", "Date Updated", "Status"))
    print(f"Organizations backup completed: {len(log)} organizations processed")
    return log

def backup_guide_articles(backup_path):
    """Backup all Guide articles."""
    print("=== Backing up Guide Articles ===")
    articles_path = os.path.join(backup_path, "guide_articles")
    create_directory(articles_path)
    
    articles_endpoint = f"https://{zendesk_subdomain}/api/v2/help_center/articles.json"
    log = []
    
    def process_article(article):
        """Process and save a single article."""
        article_id = article['id']
        filename = f"{article_id}.json"
        file_path = os.path.join(articles_path, filename)
        
        # Check if file exists and is up to date
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    existing_article = json.load(f)
                existing_updated_at = datetime.fromisoformat(existing_article['updated_at'].rstrip('Z'))
                current_updated_at = datetime.fromisoformat(article['updated_at'].rstrip('Z'))
                
                if existing_updated_at >= current_updated_at:
                    print(f"{filename} is up to date, skipping.")
                    return (filename, article['title'], article['created_at'], article['updated_at'], 'skipped')
            except Exception as e:
                print(f"Error reading {filename}: {e}")
        
        # Fetch full article details
        try:
            article_endpoint = f"https://{zendesk_subdomain}/api/v2/help_center/articles/{article_id}.json"
            response = session.get(article_endpoint)
            if response.status_code != 200:
                print(f'Failed to retrieve article {article_id} with error {response.status_code}')
                return (filename, article['title'], article['created_at'], article['updated_at'], 'error')
            
            full_article = response.json()['article']
            
            with open(file_path, 'w', encoding='utf-8') as article_file:
                json.dump(full_article, article_file, indent=2)
            print(f"{filename} - saved!")
            return (filename, full_article['title'], full_article['created_at'], full_article['updated_at'], 'backed_up')
        except (IOError, OSError, requests.RequestException) as e:
            print(f"Failed to save {filename}: {e}")
            return (filename, article['title'], article['created_at'], article['updated_at'], 'error')
    
    while articles_endpoint:
        data = fetch_data(articles_endpoint)
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(process_article, data['articles']))
            log.extend([r for r in results if r is not None])
        
        articles_endpoint = data.get('next_page')
    
    write_log(articles_path, log, ("File", "Title", "Date Created", "Date Updated", "Status"))
    print(f"Guide articles backup completed: {len(log)} articles processed")
    return log

def backup_support_assets(backup_path):
    """Backup all support assets (triggers, automations, macros, etc.)."""
    print("=== Backing up Support Assets ===")
    assets_path = os.path.join(backup_path, "support_assets")
    create_directory(assets_path)
    
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
        asset_type_path = os.path.join(assets_path, asset_name)
        create_directory(asset_type_path)
        
        print(f"Backing up {asset_name}...")
        endpoint_url = f"https://{zendesk_subdomain}/api/v2/{endpoint}.json"
        log = []
        
        def backup_asset(asset, asset_type):
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
            file_path = os.path.join(asset_type_path, filename)
            
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(asset, f, indent=2)
                print(f"{filename} - saved!")
                return (filename, title, asset.get('active', True), asset.get('created_at'), asset.get('updated_at'))
            except Exception as e:
                print(f"Error saving {filename}: {e}")
                return (f"error_{asset.get('id', 'unknown')}.json", f"ERROR: {str(e)}", False, None, None)
        
        while endpoint_url:
            data = fetch_data(endpoint_url)
            
            for asset in data[response_key]:
                try:
                    result = backup_asset(asset, asset_name)
                    log.append(result)
                except (IOError, OSError, json.JSONDecodeError) as e:
                    print(f"Error processing asset {asset.get('id', 'unknown')}: {str(e)}")
                    log.append((f"error_{asset.get('id', 'unknown')}.json", f"ERROR: {str(e)}", False, None, None))
            
            endpoint_url = data.get('next_page')
        
        write_log(asset_type_path, log, ("File", "Title", "Active", "Date Created", "Date Updated"))
        all_logs.extend([(asset_name, *entry) for entry in log])
        print(f"{asset_name} backup completed: {len(log)} items processed")
    
    # Write master log for all support assets
    master_log_path = os.path.join(assets_path, '_master_log.csv')
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

def main():
    """Main backup function with local caching."""
    print("=== Starting Zendesk Complete Backup ===")
    start_time = datetime.now()
    current_date = start_time.strftime("%Y-%m-%d_%H-%M-%S")
    
    # Create local cache directory
    create_directory(LOCAL_CACHE_PATH)
    
    # Create working directory in local cache
    backup_dir_name = f"zendesk_backup_{current_date}"
    backup_path = os.path.join(LOCAL_CACHE_PATH, backup_dir_name)
    create_directory(backup_path)
    
    print(f"Local cache directory: {backup_path}")
    print(f"OneDrive sync directory: {ONEDRIVE_BACKUP_PATH}")
    
    # Backup all asset types using local cache
    try:
        print("\n--- Using local cache for improved performance ---")
        tickets_log = backup_tickets(backup_path)
        
        users_log = backup_users(backup_path)
        orgs_log = backup_organizations(backup_path)
        articles_log = backup_guide_articles(backup_path)
        assets_log = backup_support_assets(backup_path)
        
        # Create summary log
        summary_path = os.path.join(backup_path, '_backup_summary.txt')
        with open(summary_path, 'w', encoding='utf-8') as summary_file:
            summary_file.write("Zendesk Complete Backup Summary\n")
            summary_file.write(f"Backup Date: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            summary_file.write(f"Zendesk Subdomain: {zendesk_subdomain}\n\n")
            summary_file.write(f"Tickets: {len(tickets_log)} processed\n")
            summary_file.write(f"Users: {len(users_log)} processed\n")
            summary_file.write(f"Organizations: {len(orgs_log)} processed\n")
            summary_file.write(f"Guide Articles: {len(articles_log)} processed\n")
            summary_file.write(f"Support Assets: {len(assets_log)} processed\n\n")
            summary_file.write(f"Total items: {len(tickets_log) + len(users_log) + len(orgs_log) + len(articles_log) + len(assets_log)}\n")
            
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
        print("\n=== Backup Complete ===")
        print(f"Duration: {duration}")
        print(f"Local zip file: {local_zip_path}")
        print(f"OneDrive zip file: {onedrive_zip_path}")
        print(f"Cache directory: {LOCAL_CACHE_PATH}")
        print(f"Total items backed up: {len(tickets_log) + len(users_log) + len(orgs_log) + len(articles_log) + len(assets_log)}")
        
        return True
        
    except (IOError, OSError, requests.RequestException, json.JSONDecodeError) as e:
        print(f"Backup failed: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
