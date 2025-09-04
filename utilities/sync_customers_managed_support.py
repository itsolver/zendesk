#!/usr/bin/env python3
"""
Zendesk Customers Managed Support Sync Utility

This script synchronizes customers.json with organizations that have managed support plans.
It backs up users and organizations to persistent cache, then updates customers.json with:
- Organizations tagged with "managed_support" or "managed_support_premium"
- Latest authorized_emails from users in each organization
- Current organization details from Zendesk

Usage:
    python utilities/sync_customers_managed_support.py

Requirements:
    - Google Cloud Secret Manager access for Zendesk API token
    - customers.json file in the project root
    - Persistent cache directory for storing backups
"""

import requests
import json
import os
import time
import threading
from datetime import datetime, timedelta

# Add parent directory to path for imports
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version, test_gcloud_access

# Configuration
LOCAL_CACHE_PATH = os.environ.get("LOCAL_CACHE_PATH", r"C:\Users\AngusMcLauchlan\AppData\Local\ITSolver\Cache\Zendesk_backups")
CUSTOMERS_FILE = r"C:\Users\AngusMcLauchlan\Projects\itsolver\gsuitedev\Prompting\Claude\IT Solver\customers.json"

# Rate Limiting Configuration for Zendesk Suite Professional
MAX_REQUESTS_PER_MINUTE = 350
MAX_REQUESTS_PER_SECOND = MAX_REQUESTS_PER_MINUTE / 60.0
REQUEST_INTERVAL = 1.0 / MAX_REQUESTS_PER_SECOND

# Thread pool sizes optimized for rate limits
USER_WORKERS = 4
ORG_WORKERS = 4

# Managed support tags
MANAGED_SUPPORT_TAGS = {
    "managed_support": "Essential Support Plan",
    "managed_support_premium": "Premium Support Plan"
}


class RateLimiter:
    """Thread-safe rate limiter for Zendesk API calls."""

    def __init__(self, max_requests_per_minute=MAX_REQUESTS_PER_MINUTE):
        self.max_requests_per_minute = max_requests_per_minute
        self.request_times = []
        self.lock = threading.Lock()
        self.total_requests = 0
        self.rate_limited_count = 0

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

def create_directory(path):
    """Create directory if it doesn't exist."""
    os.makedirs(path, exist_ok=True)

def setup_zendesk_session():
    """Set up authenticated Zendesk API session."""
    print("Setting up Zendesk API session...")

    # Test Google Cloud access
    if not test_gcloud_access():
        print("ERROR: Cannot access Google Cloud Secret Manager.")
        print("Please ensure:")
        print("1. GOOGLE_APPLICATION_CREDENTIALS environment variable is set")
        print("2. You have access to the 'billing-sync' project")
        print("3. You have Secret Manager permissions")
        exit(1)

    # Get Zendesk API token
    zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")

    # Create session with authentication
    session = requests.Session()
    session.auth = (zendesk_user, zendesk_secret)
    session.headers.update({
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    })

    return session

def fetch_data(session, endpoint, rate_limiter):
    """Fetch data from API endpoint with rate limiting."""
    rate_limiter.wait_if_needed()

    response = session.get(endpoint)

    if response.status_code == 429:
        # Handle rate limiting
        retry_after = int(response.headers.get('retry-after', 60))
        print(f'Rate limited! Waiting {retry_after}s')
        time.sleep(retry_after)
        # Retry the request
        rate_limiter.wait_if_needed()
        response = session.get(endpoint)

    if response.status_code != 200:
        print(f"Failed to fetch data from {endpoint}: HTTP {response.status_code}")
        print(f"Response: {response.text}")
        raise requests.RequestException(f"API request failed: {response.status_code}")

    return response.json()

def backup_users_to_cache(session, cache_path, rate_limiter):
    """Backup all users to persistent cache."""
    print("=== Backing up Users to Cache ===")

    cache_users_path = os.path.join(cache_path, "users")
    create_directory(cache_users_path)

    users_endpoint = f"https://{zendesk_subdomain}/api/v2/users.json?per_page=100"
    total_users = 0

    while users_endpoint:
        data = fetch_data(session, users_endpoint, rate_limiter)
        users = data.get('users', [])

        print(f"Processing {len(users)} users...")

        for user in users:
            filename = f"{user['id']}.json"
            cache_file_path = os.path.join(cache_users_path, filename)

            try:
                with open(cache_file_path, 'w', encoding='utf-8') as f:
                    json.dump(user, f, indent=2)
                total_users += 1
            except (IOError, OSError, json.JSONDecodeError) as e:
                print(f"Error saving user {user['id']}: {e}")

        users_endpoint = data.get('next_page')

    print(f"Users backup completed: {total_users} users cached")
    return total_users

def backup_organizations_to_cache(session, cache_path, rate_limiter):
    """Backup all organizations to persistent cache."""
    print("=== Backing up Organizations to Cache ===")

    cache_orgs_path = os.path.join(cache_path, "organizations")
    create_directory(cache_orgs_path)

    orgs_endpoint = f"https://{zendesk_subdomain}/api/v2/organizations.json?per_page=100"
    total_orgs = 0

    while orgs_endpoint:
        data = fetch_data(session, orgs_endpoint, rate_limiter)
        organizations = data.get('organizations', [])

        print(f"Processing {len(organizations)} organizations...")

        for org in organizations:
            filename = f"{org['id']}.json"
            cache_file_path = os.path.join(cache_orgs_path, filename)

            try:
                with open(cache_file_path, 'w', encoding='utf-8') as f:
                    json.dump(org, f, indent=2)
                total_orgs += 1
            except (IOError, OSError, json.JSONDecodeError) as e:
                print(f"Error saving organization {org['id']}: {e}")

        orgs_endpoint = data.get('next_page')

    print(f"Organizations backup completed: {total_orgs} organizations cached")
    return total_orgs

def load_cached_organizations(cache_path):
    """Load all organizations from cache."""
    cache_orgs_path = os.path.join(cache_path, "organizations")
    organizations = {}

    if not os.path.exists(cache_orgs_path):
        print("Warning: Organizations cache not found")
        return organizations

    for filename in os.listdir(cache_orgs_path):
        if filename.endswith('.json'):
            try:
                with open(os.path.join(cache_orgs_path, filename), 'r', encoding='utf-8') as f:
                    org = json.load(f)
                    organizations[org['id']] = org
            except (IOError, OSError, json.JSONDecodeError, KeyError) as e:
                print(f"Error loading cached organization {filename}: {e}")

    return organizations

def load_cached_users(cache_path):
    """Load all users from cache."""
    cache_users_path = os.path.join(cache_path, "users")
    users = {}

    if not os.path.exists(cache_users_path):
        print("Warning: Users cache not found")
        return users

    for filename in os.listdir(cache_users_path):
        if filename.endswith('.json'):
            try:
                with open(os.path.join(cache_users_path, filename), 'r', encoding='utf-8') as f:
                    user = json.load(f)
                    users[user['id']] = user
            except (IOError, OSError, json.JSONDecodeError, KeyError) as e:
                print(f"Error loading cached user {filename}: {e}")

    return users

def get_managed_support_organizations(organizations):
    """Identify organizations with managed support tags."""
    managed_support_orgs = {}

    for org_id, org in organizations.items():
        tags = org.get('tags', [])

        for tag in tags:
            if tag in MANAGED_SUPPORT_TAGS:
                support_plan = MANAGED_SUPPORT_TAGS[tag]
                managed_support_orgs[org_id] = {
                    'organization': org,
                    'support_plan': support_plan,
                    'support_tag': tag
                }
                break  # Use first matching tag

    return managed_support_orgs

def get_organization_users(org_id, users):
    """Get all users for an organization."""
    org_users = []
    for user in users.values():
        if user.get('organization_id') == org_id:
            # Only include users with valid email addresses
            if user.get('email') and user.get('active', True):
                org_users.append(user['email'])

    return sorted(org_users)  # Sort for consistency

def update_customers_json(managed_support_orgs, users):
    """Update customers.json with managed support organizations."""
    print("=== Updating customers.json ===")

    # Load existing customers
    customers_data = {"customers": []}
    if os.path.exists(CUSTOMERS_FILE):
        try:
            with open(CUSTOMERS_FILE, 'r', encoding='utf-8') as f:
                customers_data = json.load(f)
        except (IOError, OSError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load existing {CUSTOMERS_FILE}: {e}")
            print("Creating new customers file...")

    existing_customers = {cust.get('organization_id'): cust for cust in customers_data.get('customers', []) if cust.get('organization_id')}

    updated_customers = []
    new_customers = 0
    updated_customers_count = 0

    for org_id, data in managed_support_orgs.items():
        org = data['organization']
        support_plan = data['support_plan']
        support_tag = data['support_tag']

        # Get authorized emails for this organization
        authorized_emails = get_organization_users(org_id, users)

        customer_data = {
            "name": org.get('name', ''),
            "organization_id": org_id,
            "authorized_emails": authorized_emails,
            "domains": org.get('domain_names', []),
            "plans": {
                "software": "Microsoft 365",  # Default assumption
                "support": support_plan
            },
            "trading_names": org.get('trading_names', []),
            "tags": org.get('tags', []),
            "updated_at": datetime.now().isoformat(),
            "support_tag": support_tag
        }

        # Check if customer already exists
        if org_id in existing_customers:
            # Update existing customer
            existing = existing_customers[org_id]
            # Preserve any custom fields that might exist
            for key, value in existing.items():
                if key not in customer_data:
                    customer_data[key] = value

            # Check if emails have changed
            if set(customer_data['authorized_emails']) != set(existing.get('authorized_emails', [])):
                updated_customers_count += 1
                print(f"Updated authorized_emails for {org.get('name', '')} ({len(authorized_emails)} users)")

            updated_customers.append(customer_data)
        else:
            # Add new customer
            updated_customers.append(customer_data)
            new_customers += 1
            print(f"Added new customer: {org.get('name', '')} ({len(authorized_emails)} users)")

    # Update the customers data
    customers_data['customers'] = updated_customers

    # Add metadata
    customers_data['last_updated'] = datetime.now().isoformat()
    customers_data['total_customers'] = len(updated_customers)
    customers_data['managed_support_summary'] = {
        'new_customers': new_customers,
        'updated_customers': updated_customers_count,
        'total_organizations': len(managed_support_orgs)
    }

    # Sort customers by name before saving
    updated_customers.sort(key=lambda x: x.get('name', '').lower())

    # Save updated customers file
    try:
        with open(CUSTOMERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(customers_data, f, indent=2, ensure_ascii=False)
        print(f"✓ Successfully updated {CUSTOMERS_FILE}")
        print(f"  - Total customers: {len(updated_customers)}")
        print(f"  - New customers added: {new_customers}")
        print(f"  - Customers with email updates: {updated_customers_count}")
        print("  - Customers sorted alphabetically by name")
    except (IOError, OSError, json.JSONDecodeError) as e:
        print(f"✗ Error saving {CUSTOMERS_FILE}: {e}")
        return False

    return True

def main():
    """Main function to sync customers with managed support organizations."""
    print("=" * 60)
    print("Zendesk Customers Managed Support Sync Utility")
    print("=" * 60)

    start_time = datetime.now()

    try:
        # Initialize rate limiter
        rate_limiter_instance = RateLimiter()

        # Setup Zendesk session
        session = setup_zendesk_session()

        # Create persistent cache directory
        persistent_cache_path = os.path.join(LOCAL_CACHE_PATH, "persistent_cache")
        create_directory(persistent_cache_path)

        print(f"Cache directory: {persistent_cache_path}")
        print(f"Customers file: {CUSTOMERS_FILE}")
        print()

        # Step 1: Backup users and organizations to cache
        print("Step 1: Backing up users and organizations...")
        users_count = backup_users_to_cache(session, persistent_cache_path, rate_limiter_instance)
        orgs_count = backup_organizations_to_cache(session, persistent_cache_path, rate_limiter_instance)
        print()

        # Step 2: Load cached data
        print("Step 2: Loading cached data...")
        organizations = load_cached_organizations(persistent_cache_path)
        users = load_cached_users(persistent_cache_path)
        print(f"Loaded {len(organizations)} organizations and {len(users)} users from cache")
        print()

        # Step 3: Identify managed support organizations
        print("Step 3: Identifying managed support organizations...")
        managed_support_orgs = get_managed_support_organizations(organizations)

        print(f"Found {len(managed_support_orgs)} organizations with managed support:")
        for org_id, data in managed_support_orgs.items():
            org = data['organization']
            support_plan = data['support_plan']
            user_count = len(get_organization_users(org_id, users))
            print(f"  - {org.get('name', '')}: {support_plan} ({user_count} users)")
        print()

        # Step 4: Update customers.json
        print("Step 4: Updating customers.json...")
        update_success = update_customers_json(managed_support_orgs, users)

        if update_success:
            # Calculate duration
            end_time = datetime.now()
            duration = end_time - start_time

            print()
            print("=" * 60)
            print("SYNC COMPLETE")
            print("=" * 60)
            print(f"Duration: {duration}")
            print(f"Users cached: {users_count}")
            print(f"Organizations cached: {orgs_count}")
            print(f"Managed support organizations: {len(managed_support_orgs)}")
            print(f"Customers file updated: {CUSTOMERS_FILE}")
            print("=" * 60)

            return True
        else:
            print("✗ Sync failed")
            return False

    except (requests.RequestException, IOError, OSError, json.JSONDecodeError, KeyError) as e:
        print(f"✗ Error during sync: {e}")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
