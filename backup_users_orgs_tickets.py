import os
import csv
import re
import json
import requests
import time
import shutil
from config import zendesk_subdomain, zendesk_user, zendesk_secret, destination_folder, start_time

backup_date = time.strftime("%Y %B %e %H%M%S")
source_folder = os.path.join("support/" + backup_date)
session = requests.Session()
zendesk = 'https://' + zendesk_subdomain
session.auth = (zendesk_user, zendesk_secret)

# Organise Support backups into a directory named {date of backup} and in relevant sub directories.
base_backup_path = os.path.join("support/" + backup_date)
if not os.path.exists(base_backup_path):
    os.makedirs(base_backup_path)

users_backup_path = os.path.join("support/" + backup_date + "/users")
if not os.path.exists(users_backup_path):
    os.makedirs(users_backup_path)
    
suspended_users_backup_path = os.path.join(users_backup_path, "suspended/")
if not os.path.exists(suspended_users_backup_path):
    os.makedirs(suspended_users_backup_path)

organizations_backup_path = os.path.join("support/" + backup_date + "/organizations")
if not os.path.exists(organizations_backup_path):
    os.makedirs(organizations_backup_path)

tickets_backup_path = os.path.join("support/" + backup_date + "/tickets")
if not os.path.exists(tickets_backup_path):
    os.makedirs(tickets_backup_path)

log = []

users_endpoint = zendesk + '/api/v2/users.json'
while users_endpoint:
    response = session.get(users_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve users with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for user in data['users']:
        url = user['url']
        id = user['id']
        name = user['name']
        safe_name = re.sub('[/:\*\?\>\<\|\s_—]', '_', name)
        suspended = user['suspended']
        if not suspended:
            backup_path = users_backup_path
        else: 
            backup_path = suspended_users_backup_path
        filename = safe_name + '.json'
        created = user['created_at']
        updated = user['updated_at']
        content = json.dumps(user, indent=2)
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, name, suspended, created, updated))

    users_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Name', 'Suspended', 'Date Created', 'Date Updated') )
    for user in log:
        writer.writerow(user)

organizations_endpoint = zendesk + '/api/v2/organizations.json'
while organizations_endpoint:
    response = session.get(organizations_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve organizations with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for organization in data['organizations']:
        url = organization['url']
        id = organization['id']
        name = organization['name']
        safe_name = re.sub('[/:\*\?\>\<\|\s_—]', '_', name)
        filename = safe_name + '.json'
        created = organization['created_at']
        updated = organization['updated_at']
        content = json.dumps(organization, indent=2)
        backup_path = organizations_backup_path
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, name, created, updated))

    organizations_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Name', 'Date Created', 'Date Updated') )
    for organization in log:
        writer.writerow(organization)

tickets_endpoint = zendesk + '/api/v2/incremental/tickets.json?start_time=' + start_time
while tickets_endpoint:
    response = session.get(tickets_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve tickets with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for ticket in data['tickets']:
        url = ticket['url']
        id = ticket['id']
        subject = ticket['subject']
        safe_subject = re.sub('[/:\*\?\>\<\|\s_—]', '_', subject)
        filename = str(id) + '.json'
        created = ticket['created_at']
        updated = ticket['updated_at']
        content = json.dumps(ticket, indent=2)
        backup_path = tickets_backup_path
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, subject, created, updated))

    tickets_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Subject', 'Date Created', 'Date Updated') )
    for ticket in log:
        writer.writerow(ticket)