import requests
import json
import os
import time
import csv
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version
from concurrent.futures import ThreadPoolExecutor


# Define ZENDESK URL, START_TIME, and other necessary variables
# to get epoch time on mac terminal use e.g. ``date -j -f "%d-%B-%y" 19-FEB-12 +%s``
START_TIME = "1329575862"
TICKETS_BACKUP_PATH = 'G:\\Shared drives\\Business\\Zendesk\\Backups\\support\\2023 August 18 161300\\tickets'
zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN",
                                       "latest")
# Check if the path exists, and create it if it doesn't
if not os.path.exists(TICKETS_BACKUP_PATH):
    os.makedirs(TICKETS_BACKUP_PATH)
session = requests.Session()  # Create session object before setting authentication
session.auth = (zendesk_user, zendesk_secret)
log = []

def download_ticket(single_ticket):  # Renamed parameter to avoid shadowing
    ticket_id = single_ticket['id']
    subject = single_ticket['subject']
    filename = str(ticket_id)+'.json'
    content = json.dumps(single_ticket, indent=2)
    with open(os.path.join(TICKETS_BACKUP_PATH, filename), mode='w', encoding='utf-8') as f:
        f.write(content)
    print(filename + ' - copied!')
    return (filename, subject, single_ticket['created_at'], single_ticket['updated_at'])


tickets_endpoint = "https://" + zendesk_subdomain + '/api/v2/incremental/tickets.json?start_time=' + START_TIME
previous_tickets_endpoint = None

while tickets_endpoint:
    response = session.get(tickets_endpoint)
    if response.status_code == 429:
        print('Rate limited! Please wait.')
        time.sleep(int(response.headers['retry-after']))
        continue
    if response.status_code != 200:
        print('Failed to retrieve tickets with error {}'.format(response.status_code))
        exit()
    data = response.json()

    with ThreadPoolExecutor() as executor:
        log += list(executor.map(download_ticket, data['tickets']))

    # Check if the next_page is the same as the current endpoint
    if tickets_endpoint == previous_tickets_endpoint:
        print('Reached the end of tickets.')
        break

    previous_tickets_endpoint = tickets_endpoint
    tickets_endpoint = data['next_page']


with open(os.path.join(TICKETS_BACKUP_PATH, '_log.csv'), mode='wt', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow(('File', 'Subject', 'Date Created', 'Date Updated'))
    for ticket in log:
        writer.writerow(ticket)
