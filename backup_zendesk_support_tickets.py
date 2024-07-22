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

# Define ZENDESK URL, START_TIME, and other necessary variables
# to get epoch time on mac terminal use e.g. ``date -j -f "%d-%B-%y" 19-FEB-12 +%s``
# First ticket date in IT Solver Zendesk is 2013-04-24 16:00:00 (Epoch time: 1366783200)
START_TIME = "1721314861"
TICKETS_BACKUP_PATH = f'G:\\Shared drives\\Business\\Zendesk\\Support\\tickets'
zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN",
                                       "latest")
# Check if the path exists, and create it if it doesn't
if not os.path.exists(TICKETS_BACKUP_PATH):
    os.makedirs(TICKETS_BACKUP_PATH)
session = requests.Session()  # Create session object before setting authentication
session.auth = (zendesk_user, zendesk_secret)
log = []

def get_ticket_events(ticket_id):
    events_endpoint = f"https://{zendesk_subdomain}/api/v2/tickets/{ticket_id}/audits.json"
    events = []
    while events_endpoint:
        response = session.get(events_endpoint)
        if response.status_code == 429:
            print('Rate limited! Please wait.')
            time.sleep(int(response.headers['retry-after']))
            continue
        if response.status_code != 200:
            print(f'Failed to retrieve events for ticket {ticket_id} with error {response.status_code}')
            return events
        data = response.json()
        events.extend(data['audits'])
        events_endpoint = data.get('next_page')
    return events

def download_ticket(single_ticket):
    ticket_id = single_ticket['id']
    subject = single_ticket['subject']
    filename = f"{ticket_id}.json"
    full_path = os.path.join(TICKETS_BACKUP_PATH, filename)
    
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            existing_ticket = json.load(f)
        existing_updated_at = datetime.fromisoformat(existing_ticket['updated_at'].rstrip('Z'))
        current_updated_at = datetime.fromisoformat(single_ticket['updated_at'].rstrip('Z'))
        
        if existing_updated_at >= current_updated_at:
            print(f"{filename} is up to date, skipping.")
            return (filename, subject, single_ticket['created_at'], single_ticket['updated_at'], 'skipped')
    
    # Fetch events and comments
    events = get_ticket_events(ticket_id)
    single_ticket['events'] = events
    
    content = json.dumps(single_ticket, indent=2)
    with open(full_path, mode='w', encoding='utf-8') as f:
        f.write(content)
    print(f"{filename} - copied with {len(events)} events!")
    return (filename, subject, single_ticket['created_at'], single_ticket['updated_at'], 'backed_up')

# Update these constants at the top of your script
LOG_FILE_BASE = '_log'
LOG_FILE_EXT = '.csv'
MAX_LOG_FILES = 5  # Adjust this number to keep more or fewer log files

def rotate_log_files():
    log_dir = TICKETS_BACKUP_PATH
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

tickets_endpoint = f"https://{zendesk_subdomain}/api/v2/incremental/tickets.json?start_time={START_TIME}"
previous_end_time = None
total_backed_up = 0
total_skipped = 0

while tickets_endpoint:
    response = session.get(tickets_endpoint)
    if response.status_code == 429:
        print('Rate limited! Please wait.')
        time.sleep(int(response.headers['retry-after']))
        continue
    if response.status_code != 200:
        print(f'Failed to retrieve tickets with error {response.status_code}')
        exit()
    data = response.json()

    with ThreadPoolExecutor() as executor:
        results = list(executor.map(download_ticket, data['tickets']))
        log += results
        total_backed_up += sum(1 for r in results if r[4] == 'backed_up')
        total_skipped += sum(1 for r in results if r[4] == 'skipped')

    # Update the start_time for the next API call
    end_time = data['end_time']
    if end_time == previous_end_time:
        print('No new tickets found. Ending the process.')
        break
    
    previous_end_time = end_time
    START_TIME = end_time
    
    tickets_endpoint = data.get('next_page')
    if not tickets_endpoint:
        print('Reached the end of tickets.')
        break

# At the end of your script, before writing the new log file:
current_log_file = rotate_log_files()

# Get the current timestamp
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Write the new log file with a timestamp in the header
with open(os.path.join(TICKETS_BACKUP_PATH, current_log_file), mode='wt', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow(('Backup Date', current_time))
    writer.writerow(('File', 'Subject', 'Date Created', 'Date Updated', 'Status'))
    for ticket in log:
        writer.writerow(ticket)

print(f"\nLog file updated: {os.path.join(TICKETS_BACKUP_PATH, current_log_file)}")
print("\nBackup Summary:")
print(f"Total tickets backed up: {total_backed_up}")
print(f"Total tickets skipped: {total_skipped}")
print(f"Total tickets processed: {total_backed_up + total_skipped}")