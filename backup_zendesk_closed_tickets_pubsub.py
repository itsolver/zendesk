import requests
import json
import os
import time
import csv
from google.cloud import pubsub_v1
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version
from concurrent.futures import ThreadPoolExecutor

# Initialize Pub/Sub publisher
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path('billing-sync', 'zendesk-tickets-closed')

# Define ZENDESK URL, START_TIME, and other necessary variables
START_TIME = "1693441920"  # Thursday, 31 August 2023 10:32:00 AM GMT+10:00
#START_TIME = "1329575862" # Sunday, 19 February 2012 12:37:42 AM GMT+10:00
TICKETS_BACKUP_PATH = 'G:\\Shared drives\\Business\\Zendesk\\Backups\\support\\2023 Sept 3\\tickets'
zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")

# Check if the path exists, and create it if it doesn't
if not os.path.exists(TICKETS_BACKUP_PATH):
    os.makedirs(TICKETS_BACKUP_PATH)

session = requests.Session()  # Create session object before setting authentication
session.auth = (zendesk_user, zendesk_secret)
log = []

def download_ticket(single_ticket):
    # Check if the ticket is closed
    if single_ticket['status'] != 'closed':
        return

    ticket_id = single_ticket['id']
    subject = single_ticket['subject']
    content = json.dumps(single_ticket, indent=2)
    
    # Publish to Pub/Sub
    future = publisher.publish(topic_path, content.encode('utf-8'))
    future.result()

    filename = str(ticket_id) + '.json'
    with open(os.path.join(TICKETS_BACKUP_PATH, filename), mode='w', encoding='utf-8') as f:
        f.write(content)
    
    print(filename + ' - copied and published to Pub/Sub!')
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
        print(f'Failed to retrieve tickets with error {response.status_code}')
        exit()
    data = response.json()

    with ThreadPoolExecutor() as executor:
        log += list(filter(None, executor.map(download_ticket, data['tickets'])))

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
