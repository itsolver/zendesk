import requests
import json
import os
import time
import csv
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import shutil

# Define necessary variables
USERS_BACKUP_PATH = f'G:\\Shared drives\\Business\\Zendesk\\Support\\users'
zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN",
                                       "latest")
# Check if the path exists, and create it if it doesn't
if not os.path.exists(USERS_BACKUP_PATH):
    os.makedirs(USERS_BACKUP_PATH)
session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)
log = []

def download_user(single_user):
    user_id = single_user['id']
    name = single_user['name']
    filename = f"{user_id}.json"
    full_path = os.path.join(USERS_BACKUP_PATH, filename)
    
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            existing_user = json.load(f)
        existing_updated_at = datetime.fromisoformat(existing_user['updated_at'].rstrip('Z'))
        current_updated_at = datetime.fromisoformat(single_user['updated_at'].rstrip('Z'))
        
        if existing_updated_at >= current_updated_at:
            print(f"{filename} is up to date, skipping.")
            return (filename, name, single_user['created_at'], single_user['updated_at'], 'skipped')
    
    content = json.dumps(single_user, indent=2)
    with open(full_path, mode='w', encoding='utf-8') as f:
        f.write(content)
    print(f"{filename} - copied!")
    return (filename, name, single_user['created_at'], single_user['updated_at'], 'backed_up')

# Update these constants at the top of your script
LOG_FILE_BASE = '_log'
LOG_FILE_EXT = '.csv'
MAX_LOG_FILES = 5  # Adjust this number to keep more or fewer log files

def rotate_log_files():
    log_dir = USERS_BACKUP_PATH
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_log_file = f"{LOG_FILE_BASE}_{current_date}{LOG_FILE_EXT}"
    log_path = os.path.join(log_dir, current_log_file)
    
    # If the log file for today doesn't exist, no need to rotate
    if not os.path.exists(log_path):
        return current_log_file
    
    # Rotate existing log files
    for i in range(MAX_LOG_FILES - 1, 0, -1):
        old_log = os.path.join(log_dir, f"{LOG_FILE_BASE}_{current_date}_{i}{LOG_FILE_EXT}")
        new_log = os.path.join(log_dir, f"{LOG_FILE_BASE}_{current_date}_{i+1}{LOG_FILE_EXT}")
        if os.path.exists(old_log):
            shutil.move(old_log, new_log)
    
    # Move the current log file
    shutil.move(log_path, os.path.join(log_dir, f"{LOG_FILE_BASE}_{current_date}_1{LOG_FILE_EXT}"))
    
    return current_log_file

users_endpoint = f"https://{zendesk_subdomain}/api/v2/users.json"
total_backed_up = 0
total_skipped = 0

while users_endpoint:
    response = session.get(users_endpoint)
    if response.status_code == 429:
        print('Rate limited! Please wait.')
        time.sleep(int(response.headers['retry-after']))
        continue
    if response.status_code != 200:
        print(f'Failed to retrieve users with error {response.status_code}')
        exit()
    data = response.json()

    with ThreadPoolExecutor() as executor:
        results = list(executor.map(download_user, data['users']))
        log += results
        total_backed_up += sum(1 for r in results if r[4] == 'backed_up')
        total_skipped += sum(1 for r in results if r[4] == 'skipped')

    users_endpoint = data.get('next_page')
    if not users_endpoint:
        print('Reached the end of users.')
        break

# At the end of your script, before writing the new log file:
current_log_file = rotate_log_files()

# Get the current timestamp
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Write the new log file with a timestamp in the header
with open(os.path.join(USERS_BACKUP_PATH, current_log_file), mode='wt', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow(('Backup Date', current_time))
    writer.writerow(('File', 'Name', 'Date Created', 'Date Updated', 'Status'))
    for user in log:
        writer.writerow(user)

print(f"\nLog file updated: {os.path.join(USERS_BACKUP_PATH, current_log_file)}")
print("\nBackup Summary:")
print(f"Total users backed up: {total_backed_up}")
print(f"Total users skipped: {total_skipped}")
print(f"Total users processed: {total_backed_up + total_skipped}")