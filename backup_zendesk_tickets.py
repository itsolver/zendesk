import requests
import json
import os
import time
import csv
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# Define ZENDESK URL, START_TIME, and other necessary variables
# to get epoch time on mac terminal use e.g. ``date -j -f "%d-%B-%y" 19-FEB-12 +%s``
# First ticket date in IT Solver Zendesk is 2013-04-24 16:00:00 (Epoch time: 1366783200)
START_TIME = "1366783200"
TICKETS_BACKUP_PATH = f'G:\\Shared drives\\Business\\Zendesk\\tickets'
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
            return (filename, subject, single_ticket['created_at'], single_ticket['updated_at'])
    
    # Fetch events and comments
    events = get_ticket_events(ticket_id)
    single_ticket['events'] = events
    
    content = json.dumps(single_ticket, indent=2)
    with open(full_path, mode='w', encoding='utf-8') as f:
        f.write(content)
    print(f"{filename} - copied with {len(events)} events!")
    return (filename, subject, single_ticket['created_at'], single_ticket['updated_at'])

tickets_endpoint = f"https://{zendesk_subdomain}/api/v2/incremental/tickets.json?start_time={START_TIME}"
previous_tickets_endpoint = None

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
        log += list(executor.map(download_ticket, data['tickets']))

    # Update the start_time for the next API call
    if data['tickets']:
        latest_ticket = max(data['tickets'], key=lambda x: x['updated_at'])
        START_TIME = int(datetime.fromisoformat(latest_ticket['updated_at'].replace('Z', '+00:00')).timestamp())
    
    tickets_endpoint = data.get('next_page')
    if not tickets_endpoint:
        print('Reached the end of tickets.')
        break

with open(os.path.join(TICKETS_BACKUP_PATH, '_log.csv'), mode='wt', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow(('File', 'Subject', 'Date Created', 'Date Updated'))
    for ticket in log:
        writer.writerow(ticket)