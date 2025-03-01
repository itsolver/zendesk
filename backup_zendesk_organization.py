import requests
import json
import os
import time
from datetime import datetime
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version

# Define necessary variables
ORG_ID = "7340900208399"
ORG_BACKUP_PATH = '/Users/angusmclauchlan/Library/CloudStorage/GoogleDrive-angus@itsolver.net/Shared drives/Business/Zendesk/Support/organizations'
zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN",
                                       "latest")

# Check if the path exists, and create it if it doesn't
if not os.path.exists(ORG_BACKUP_PATH):
    os.makedirs(ORG_BACKUP_PATH)

# Setup the session with authentication
session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)
session.headers.update({"Content-Type": "application/json"})

def backup_organization(org_id):
    """Backup a specific organization by ID"""
    print(f"Backing up organization with ID: {org_id}")
    
    # Construct the URL for the organization endpoint
    org_endpoint = f"https://{zendesk_subdomain}/api/v2/organizations/{org_id}"
    
    # Make the API request
    response = session.get(org_endpoint)
    
    # Handle rate limiting
    if response.status_code == 429:
        print('Rate limited! Please wait.')
        time.sleep(int(response.headers.get('retry-after', 60)))
        return backup_organization(org_id)  # Retry after waiting
    
    # Check for success
    if response.status_code != 200:
        print(f'Failed to retrieve organization with error {response.status_code}')
        print(response.text)
        return False
    
    # Parse the response data
    data = response.json()
    
    # Create the filename based on the organization ID
    filename = f"{org_id}.json"
    full_path = os.path.join(ORG_BACKUP_PATH, filename)
    
    # Check if file exists and compare updated_at timestamps
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            existing_org = json.load(f)
        
        existing_updated_at = datetime.fromisoformat(existing_org['organization']['updated_at'].rstrip('Z'))
        current_updated_at = datetime.fromisoformat(data['organization']['updated_at'].rstrip('Z'))
        
        if existing_updated_at >= current_updated_at:
            print(f"{filename} is up to date, skipping.")
            return (filename, data['organization']['name'], data['organization']['created_at'], 
                   data['organization']['updated_at'], 'skipped')
    
    # Save the organization data to a file
    content = json.dumps(data, indent=2)
    with open(full_path, mode='w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"{filename} - backed up successfully!")
    return (filename, data['organization']['name'], data['organization']['created_at'], 
           data['organization']['updated_at'], 'backed_up')

def backup_organization_users(org_id):
    """Backup all users belonging to the organization"""
    print(f"Backing up users for organization with ID: {org_id}")
    
    # Create a directory for the organization's users
    org_users_path = os.path.join(ORG_BACKUP_PATH, f"{org_id}_users")
    if not os.path.exists(org_users_path):
        os.makedirs(org_users_path)
    
    # Construct the URL for the organization membership endpoint
    users_endpoint = f"https://{zendesk_subdomain}/api/v2/organizations/{org_id}/users.json"
    
    user_count = 0
    backed_up_count = 0
    skipped_count = 0
    
    while users_endpoint:
        # Make the API request
        response = session.get(users_endpoint)
        
        # Handle rate limiting
        if response.status_code == 429:
            print('Rate limited! Please wait.')
            time.sleep(int(response.headers.get('retry-after', 60)))
            continue
        
        # Check for success
        if response.status_code != 200:
            print(f'Failed to retrieve users with error {response.status_code}')
            print(response.text)
            return False
        
        # Parse the response data
        data = response.json()
        
        # Process each user
        for user in data['users']:
            user_id = user['id']
            filename = f"{user_id}.json"
            full_path = os.path.join(org_users_path, filename)
            
            # Check if file exists and compare updated_at timestamps
            if os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    existing_user = json.load(f)
                
                existing_updated_at = datetime.fromisoformat(existing_user['updated_at'].rstrip('Z'))
                current_updated_at = datetime.fromisoformat(user['updated_at'].rstrip('Z'))
                
                if existing_updated_at >= current_updated_at:
                    print(f"{filename} is up to date, skipping.")
                    skipped_count += 1
                    continue
            
            # Save the user data to a file
            content = json.dumps(user, indent=2)
            with open(full_path, mode='w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"{filename} - backed up successfully!")
            backed_up_count += 1
            
        user_count += len(data['users'])
        
        # Get the next page URL if it exists
        users_endpoint = data.get('next_page')
    
    print(f"\nUser Backup Summary:")
    print(f"Total users found: {user_count}")
    print(f"Users backed up: {backed_up_count}")
    print(f"Users skipped: {skipped_count}")
    
    return (user_count, backed_up_count, skipped_count)

# Main execution
if __name__ == "__main__":
    # Get the current timestamp
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Starting backup at {current_time}")
    
    try:
        # Backup the organization data
        org_result = backup_organization(ORG_ID)
        
        if org_result and org_result[4] != 'error':
            print(f"Organization '{org_result[1]}' backed up successfully")
            
            # Backup the organization's users
            user_result = backup_organization_users(ORG_ID)
            
            if user_result:
                print("\nBackup Summary:")
                print(f"Organization: {org_result[1]} (ID: {ORG_ID})")
                print(f"Organization file: {org_result[0]}")
                print(f"Organization created: {org_result[2]}")
                print(f"Organization last updated: {org_result[3]}")
                print(f"Organization backup status: {org_result[4]}")
                print(f"Total users: {user_result[0]}")
                print(f"Users backed up: {user_result[1]}")
                print(f"Users skipped: {user_result[2]}")
        else:
            print(f"Failed to backup organization with ID {ORG_ID}")
    
    except Exception as e:
        print(f"Error during backup: {str(e)}")
    
    # Get the end timestamp
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\nBackup completed at {end_time}") 