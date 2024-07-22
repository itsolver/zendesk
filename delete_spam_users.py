import requests
import json
import re
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

# Function to check if a user is likely spam
def is_spam_user(user):
    spam_indicator = r"ETH_coins"
    
    name = user.get('name', '')
    
    if re.search(spam_indicator, name, re.IGNORECASE):
        return True
    
    return False

# Fetch and process users
def process_users():
    url = f"https://{zendesk_subdomain}/api/v2/users.json"
    spam_count = 0
    total_count = 0
    
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
                print(f"[DRY RUN] Would delete spam user: {user['name']} (ID: {user['id']})")
                simulate_delete_user(user['id'])
        
        url = data['next_page']
    
    print(f"\n[DRY RUN] Summary:")
    print(f"Total users processed: {total_count}")
    print(f"Spam users identified: {spam_count}")
    print(f"Percentage of spam users: {(spam_count / total_count) * 100:.2f}%")

# Run the script
process_users()