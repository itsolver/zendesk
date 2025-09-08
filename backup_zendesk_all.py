import requests
from requests.adapters import HTTPAdapter
import json
import os
import time
import csv
import shutil
import re
import unicodedata
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version, test_gcloud_access

# Configuration
LOCAL_CACHE_PATH = os.environ.get("LOCAL_CACHE_PATH", r"C:\Users\AngusMcLauchlan\AppData\Local\ITSolver\Cache\Zendesk_backups")
BACKUP_DESTINATION_PATH = os.environ.get("BACKUP_PATH", r"C:\Users\AngusMcLauchlan\IT Solver\IT Solver - Documents\Admin\Suppliers\Zendesk\Backups")
BATCH_SIZE = 100  # Process items in batches to reduce memory usage

# Rate Limiting Configuration for Zendesk Suite Professional
# Support API: 400 requests per minute = ~6.67 requests per second
# We'll use 350 req/min to stay safely under the limit
MAX_REQUESTS_PER_MINUTE = 350
MAX_REQUESTS_PER_SECOND = MAX_REQUESTS_PER_MINUTE / 60.0
REQUEST_INTERVAL = 1.0 / MAX_REQUESTS_PER_SECOND  # ~0.17 seconds between requests

# Thread pool sizes optimized for rate limits (override via env)
TICKET_WORKERS = int(os.environ.get("TICKET_WORKERS", "6"))
USER_WORKERS = int(os.environ.get("USER_WORKERS", "8"))
ORG_WORKERS = int(os.environ.get("ORG_WORKERS", "4"))  
ARTICLE_WORKERS = int(os.environ.get("ARTICLE_WORKERS", "4"))
ASSET_WORKERS = int(os.environ.get("ASSET_WORKERS", "5"))   # Support assets are typically fewer in number

# Note: We no longer use incremental backups based on last run time
# Instead, we always backup all tickets but use local caching to avoid re-downloading unchanged ones

class RateLimiter:
    """Thread-safe rate limiter for Zendesk API calls."""
    
    def __init__(self, max_requests_per_minute=MAX_REQUESTS_PER_MINUTE):
        self.max_requests_per_minute = max_requests_per_minute
        self.request_times = []
        self.lock = threading.Lock()
        self.total_requests = 0
        self.rate_limited_count = 0
        self.last_rate_limit_info = {}
        
    def wait_if_needed(self):
        """Wait if we're approaching rate limits."""
        with self.lock:
            now = datetime.now()
            
            # Remove requests older than 1 minute
            cutoff = now - timedelta(minutes=1)
            self.request_times = [req_time for req_time in self.request_times if req_time > cutoff]
            
            # Check if we need to wait
            if len(self.request_times) >= self.max_requests_per_minute:
                # Wait until the oldest request is more than 1 minute ago
                oldest_request = min(self.request_times)
                wait_time = 61 - (now - oldest_request).total_seconds()
                if wait_time > 0:
                    print(f"Rate limiting: waiting {wait_time:.1f}s to stay under {self.max_requests_per_minute} req/min")
                    time.sleep(wait_time)
            
            # Add current request time
            self.request_times.append(now)
            self.total_requests += 1
            
    def handle_rate_limit_response(self, response):
        """Handle 429 responses and update rate limit info."""
        with self.lock:
            if response.status_code == 429:
                self.rate_limited_count += 1
                retry_after = int(response.headers.get('retry-after', 60))
                
                # Update rate limit info from headers
                self.last_rate_limit_info = {
                    'limit': response.headers.get('X-Rate-Limit', 'unknown'),
                    'remaining': response.headers.get('X-Rate-Limit-Remaining', 'unknown'),
                    'retry_after': retry_after,
                    'timestamp': datetime.now()
                }
                
                print(f'Rate limited! Waiting {retry_after}s. Limit: {self.last_rate_limit_info["limit"]}, '
                      f'Remaining: {self.last_rate_limit_info["remaining"]}')
                time.sleep(retry_after)
                return True
            
            # Update rate limit info from successful responses
            if 'X-Rate-Limit' in response.headers:
                self.last_rate_limit_info.update({
                    'limit': response.headers.get('X-Rate-Limit'),
                    'remaining': response.headers.get('X-Rate-Limit-Remaining'),
                    'timestamp': datetime.now()
                })
                
            return False
    
    def get_stats(self):
        """Get current rate limiting statistics."""
        with self.lock:
            now = datetime.now()
            cutoff = now - timedelta(minutes=1)
            recent_requests = len([req_time for req_time in self.request_times if req_time > cutoff])
            
            return {
                'total_requests': self.total_requests,
                'requests_last_minute': recent_requests,
                'rate_limited_count': self.rate_limited_count,
                'last_rate_limit_info': self.last_rate_limit_info
            }

# Initialize global rate limiter
rate_limiter = RateLimiter()

# Initialize session
print("Config loaded!")

# Test Google Cloud access before attempting to use Secret Manager
if not test_gcloud_access():
    print("ERROR: Cannot access Google Cloud Secret Manager.")
    print("Please ensure:")
    print("1. GOOGLE_APPLICATION_CREDENTIALS environment variable is set")
    print("2. You have access to the 'billing-sync' project")
    print("3. You have Secret Manager permissions")
    print("   OR run interactive authentication when prompted")
    exit(1)

zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")
session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)
session.headers.update({
    'Connection': 'keep-alive',
    'Accept-Encoding': 'gzip, deflate',
    'User-Agent': 'itsolver-zendesk-backup/1.0'
})

# Increase HTTP connection pool for better concurrency across threads
_adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50)
session.mount('https://', _adapter)
session.mount('http://', _adapter)

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
    """Handle API rate limiting - now uses global rate limiter."""
    return rate_limiter.handle_rate_limit_response(response)

def fetch_data(endpoint):
    """Fetch data from API endpoint with proactive rate limiting."""
    while True:
        # Proactive rate limiting
        rate_limiter.wait_if_needed()
        
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
            raise requests.RequestException(
                f'Failed to retrieve data from {endpoint} with error {response.status_code}'
            )
        return response.json()

def fetch_data_with_retries(endpoint, max_retries=3):
    """Fetch data with exponential backoff on failures."""
    for attempt in range(max_retries):
        try:
            return fetch_data(endpoint)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            wait_time = (2 ** attempt) + 1  # Exponential backoff: 1s, 3s, 7s
            print(f"Request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {str(e)}")
            time.sleep(wait_time)

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
    
    # Use incremental tickets endpoint to get ALL tickets (including archived)
    # Start from beginning of time to get complete history
    START_TIME = "0"  # Epoch start to get all tickets ever created
    tickets_endpoint = f"https://{zendesk_subdomain}/api/v2/incremental/tickets.json?start_time={START_TIME}"
    log = []
    total_cached = 0
    total_downloaded = 0
    previous_end_time = None
    
    print("Starting complete ticket backup using incremental API (gets ALL tickets including archived)")
    
    def get_ticket_events(ticket_id):
        """Get all events for a ticket with improved rate limiting."""
        events_endpoint = f"https://{zendesk_subdomain}/api/v2/tickets/{ticket_id}/audits.json"
        events = []
        while events_endpoint:
            # Proactive rate limiting
            rate_limiter.wait_if_needed()
            
            response = session.get(events_endpoint)
            
            if handle_rate_limit(response):
                continue
                
            if response.status_code != 200:
                print(f"Failed to get events for ticket {ticket_id}: HTTP {response.status_code}")
                break
                
            data = response.json()
            events.extend(data["audits"])
            events_endpoint = data.get("next_page")
        return events
    
    def process_ticket(ticket):
        """Process and save a single ticket."""
        nonlocal total_cached, total_downloaded
        ticket_id = str(ticket["id"])
        
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
                json.dump(ticket, ticket_file, separators=(",", ":"))
            
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
        
        # Use improved fetch function with rate limiting
        try:
            data = fetch_data_with_retries(tickets_endpoint)
        except Exception as e:
            print(f"Failed to retrieve tickets page {page_count}: {e}")
            break
        
        if not data.get("tickets"):
            print(f"No tickets found on page {page_count}")
            break
        
        print(f"Processing tickets page {page_count}: {len(data['tickets'])} tickets")
        
        # Optimized thread pool size for rate limits
        with ThreadPoolExecutor(max_workers=TICKET_WORKERS) as executor:
            results = list(executor.map(process_ticket, data["tickets"]))
            log.extend([r for r in results if r is not None])
        
        # Print rate limiting stats every 5 pages
        if page_count % 5 == 0:
            stats = rate_limiter.get_stats()
            print(f"Rate limiter stats: {stats['requests_last_minute']}/min, "
                  f"total: {stats['total_requests']}, rate limited: {stats['rate_limited_count']}")
        
        # Update the start_time for the next API call using end_time
        end_time = data.get("end_time")
        if end_time == previous_end_time:
            print("No new tickets found. Ending the process.")
            break
        
        previous_end_time = end_time
        START_TIME = end_time
        
        tickets_endpoint = data.get("next_page")
        if not tickets_endpoint:
            print("Reached the end of tickets.")
            break
    
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
    
    users_endpoint = f"https://{zendesk_subdomain}/api/v2/users.json?per_page=100"
    log = []
    total_cached = 0
    total_downloaded = 0
    
    def process_user(user):
        """Process and save a single user."""
        nonlocal total_cached, total_downloaded
        user_id = str(user['id'])
        
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
                json.dump(user, f, separators=(",", ":"))
            
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
        data = fetch_data_with_retries(users_endpoint)
        
        print(f"Processing users page {page_count}: {len(data['users'])} users")
        
        # Optimized thread pool size for rate limits
        with ThreadPoolExecutor(max_workers=USER_WORKERS) as executor:
            results = list(executor.map(process_user, data['users']))
            # Filter out None results (deleted users)
            log.extend([r for r in results if r is not None])
        
        # Print rate limiting stats every 10 pages
        if page_count % 10 == 0:
            stats = rate_limiter.get_stats()
            print(f"Rate limiter stats: {stats['requests_last_minute']}/min, "
                  f"total: {stats['total_requests']}, rate limited: {stats['rate_limited_count']}")
        
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
    
    orgs_endpoint = f"https://{zendesk_subdomain}/api/v2/organizations.json?per_page=100"
    log = []
    total_cached = 0
    total_downloaded = 0
    
    def process_organization(org):
        """Process and save a single organization."""
        nonlocal total_cached, total_downloaded
        org_id = str(org['id'])
        
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
        data = fetch_data_with_retries(orgs_endpoint)
        
        print(f"Processing organizations page {page_count}: {len(data['organizations'])} organizations")
        
        # Optimized thread pool size for rate limits
        with ThreadPoolExecutor(max_workers=ORG_WORKERS) as executor:
            results = list(executor.map(process_organization, data['organizations']))
            # Filter out None results (deleted organizations)
            log.extend([r for r in results if r is not None])
        
        # Print rate limiting stats every 5 pages
        if page_count % 5 == 0:
            stats = rate_limiter.get_stats()
            print(f"Rate limiter stats: {stats['requests_last_minute']}/min, "
                  f"total: {stats['total_requests']}, rate limited: {stats['rate_limited_count']}")
        
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
    
    articles_endpoint = f"https://{zendesk_subdomain}/api/v2/help_center/articles.json?per_page=100"
    log = []
    total_cached = 0
    total_downloaded = 0
    
    def process_article(article):
        """Process and save a single article."""
        nonlocal total_cached, total_downloaded
        article_id = str(article['id'])
        
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
            
            # Use rate limiting for individual article requests
            rate_limiter.wait_if_needed()
            response = session.get(article_endpoint)
            
            if handle_rate_limit(response):
                # Retry after rate limit
                rate_limiter.wait_if_needed()
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
        data = fetch_data_with_retries(articles_endpoint)
        
        print(f"Processing articles page {page_count}: {len(data['articles'])} articles")
        
        # Optimized thread pool size for rate limits (articles make individual API calls)
        with ThreadPoolExecutor(max_workers=ARTICLE_WORKERS) as executor:
            results = list(executor.map(process_article, data['articles']))
            # Filter out None results (deleted articles)
            log.extend([r for r in results if r is not None])
        
        # Print rate limiting stats every 3 pages (articles are more API intensive)
        if page_count % 3 == 0:
            stats = rate_limiter.get_stats()
            print(f"Rate limiter stats: {stats['requests_last_minute']}/min, "
                  f"total: {stats['total_requests']}, rate limited: {stats['rate_limited_count']}")
        
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
         'ticket_forms': {'name': 'ticket_forms', 'response_key': 'ticket_forms'},
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
            title_key = 'name' if asset_type in ['triggers', 'automations', 'macros', 'ticket_forms', 'views'] else 'title'
            
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
            data = fetch_data_with_retries(endpoint_url)
            
            print(f"Processing {asset_name} page {page_count}: {len(data[response_key])} items")
            
            # Process assets in smaller batches to avoid overwhelming the rate limiter
            batch_size = min(20, len(data[response_key]))  # Process in smaller batches
            for i in range(0, len(data[response_key]), batch_size):
                batch = data[response_key][i:i + batch_size]
                
                # Process assets sequentially to be more conservative with rate limits
                batch_results = []
                for asset in batch:
                    try:
                        result = backup_asset(asset, asset_name, cache_asset_type_path, backup_asset_type_path)
                        batch_results.append(result)
                    except (IOError, OSError, json.JSONDecodeError) as e:
                        print(f"Error processing asset {asset.get('id', 'unknown')}: {str(e)}")
                        batch_results.append((f"error_{asset.get('id', 'unknown')}.json", f"ERROR: {str(e)}", False, None, None))
                log.extend(batch_results)
            
            # Print rate limiting stats every 2 pages for assets
            if page_count % 2 == 0:
                stats = rate_limiter.get_stats()
                print(f"Rate limiter stats: {stats['requests_last_minute']}/min, "
                      f"total: {stats['total_requests']}, rate limited: {stats['rate_limited_count']}")
            
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
    print(f"OneDrive sync directory: {BACKUP_DESTINATION_PATH}")
    
    # Backup all asset types using persistent local cache
    try:
        print("\n--- Using persistent local cache for improved performance ---")
        # Backup faster items first
        assets_log = backup_support_assets(backup_path, persistent_cache_path)
        articles_log = backup_guide_articles(backup_path, persistent_cache_path)

        # Backup longest-running items last
        orgs_log = backup_organizations(backup_path, persistent_cache_path)
        tickets_log = backup_tickets(backup_path, persistent_cache_path)
        users_log = backup_users(backup_path, persistent_cache_path)
        
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
            
            # Add rate limiting statistics to summary
            stats = rate_limiter.get_stats()
            avg_requests_per_min = stats['total_requests'] / (duration.total_seconds() / 60.0) if duration.total_seconds() > 0 else 0
            summary_file.write("\nAPI Performance:\n")
            summary_file.write(f"Total API requests: {stats['total_requests']}\n")
            summary_file.write(f"Average rate: {avg_requests_per_min:.1f} requests/minute (limit: {MAX_REQUESTS_PER_MINUTE}/min)\n")
            summary_file.write(f"Rate limited events: {stats['rate_limited_count']}\n")
            summary_file.write(f"Rate limit compliance: {'Yes' if avg_requests_per_min <= MAX_REQUESTS_PER_MINUTE else 'No'}\n")
            
            summary_file.write(f"\nBackup Duration: {duration}\n")
            summary_file.write(f"Backup Completed: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Create zip file in local cache first
        zip_filename = f"zendesk_backup_{current_date}.zip"
        local_zip_path = os.path.join(LOCAL_CACHE_PATH, zip_filename)
        create_backup_zip(backup_path, local_zip_path)
        
        # Copy zip file to OneDrive sync folder (only one file to sync)
        create_directory(BACKUP_DESTINATION_PATH)
        onedrive_zip_path = os.path.join(BACKUP_DESTINATION_PATH, zip_filename)
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
        
        # Get final rate limiting statistics
        final_stats = rate_limiter.get_stats()
        avg_requests_per_min = final_stats['total_requests'] / (duration.total_seconds() / 60.0) if duration.total_seconds() > 0 else 0
        
        print("\n=== Backup Complete ===")
        print(f"Duration: {duration}")
        print(f"Total items backed up: {total_items}")
        print(f"Cache efficiency: {cached_items} cached, {downloaded_items} downloaded ({cache_rate:.1f}% cache hit rate)")
        print("API Performance:")
        print(f"  - Total API requests: {final_stats['total_requests']}")
        print(f"  - Average rate: {avg_requests_per_min:.1f} requests/minute (limit: {MAX_REQUESTS_PER_MINUTE}/min)")
        print(f"  - Rate limited events: {final_stats['rate_limited_count']}")
        print(f"  - Rate limit compliance: {'✓' if avg_requests_per_min <= MAX_REQUESTS_PER_MINUTE else '✗'}")
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
