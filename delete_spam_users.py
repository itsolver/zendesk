import requests
import json
import re
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import csv
from datetime import datetime
import os
import argparse

from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version

# Zendesk API credentials
api_token = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")

# Configure retry strategy
retry_strategy = Retry(
    total=3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"],
    backoff_factor=1
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session = requests.Session()
session.mount("https://", adapter)
session.auth = (f"{zendesk_user}", api_token)

# Function to simulate deleting a user (dry run)
def simulate_delete_user(user_id):
    print(f"[DRY RUN] Would delete user with ID: {user_id}")
    return True

# Function to delete a user
def delete_user(user_id):
    url = f"https://{zendesk_subdomain}/api/v2/users/{user_id}.json"
    try:
        response = session.delete(url)
        response.raise_for_status()
        print(f"Deleted user with ID: {user_id}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error deleting user {user_id}: {e}")
        return False

# Function to check if a user is likely spam
def is_spam_user(user):
    spam_indicator = r"ETH_coins"
    
    name = user.get('name', '')
    
    if re.search(spam_indicator, name, re.IGNORECASE):
        return True
    
    return False

# Fetch and process users
def process_users(dry_run=True):
    url = f"https://{zendesk_subdomain}/api/v2/users.json"
    spam_count = 0
    total_count = 0
    spam_users = []
    
    while url:
        try:
            response = session.get(url)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching users: {e}")
            print(f"Response content: {response.text if response else 'No response'}")
            break

        try:
            data = response.json()
        except json.JSONDecodeError:
            print("Error: Unable to parse JSON response")
            print(f"Response content: {response.text}")
            break
        response = requests.get(url, auth=(f"{zendesk_user}", api_token))
        data = response.json()
        
        for user in data['users']:
            total_count += 1
            if is_spam_user(user):
                spam_count += 1
                if dry_run:
                    print(f"[DRY RUN] Would delete spam user: {user['name']} (ID: {user['id']})")
                    simulate_delete_user(user['id'])
                else:
                    print(f"Deleting spam user: {user['name']} (ID: {user['id']})")
                    delete_user(user['id'])
                spam_users.append({'id': user['id'], 'name': user['name']})
        
        url = data['next_page']
    
    print(f"{'[DRY RUN] ' if dry_run else ''}Summary:")
    print(f"Total users processed: {total_count}")
    print(f"Spam users identified: {spam_count}")
    print(f"Percentage of spam users: {(spam_count / total_count) * 100:.2f}%")

    # Write results to CSV
    output_dir = r"G:\Shared drives\Business\Zendesk\Support\users"
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = os.path.join(output_dir, f"spam_users_{timestamp}.csv")
    
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['id', 'name']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for user in spam_users:
            writer.writerow(user)
    
    print(f"CSV log file created: {csv_filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete spam users from Zendesk")
    parser.add_argument("--live", action="store_true", help="Run in live mode (actually delete users)")
    args = parser.parse_args()

    if args.live:
        print("Running in LIVE mode. Users will be deleted!")
    else:
        print("Running in DRY RUN mode. No users will be deleted.")
    
    process_users(dry_run=not args.live)