import os
import csv
import re
import json
import requests
import getpass
import time
import shutil
from config import *

backup_date = time.strftime("%Y %B %e")
source_folder = os.path.join("support/" + backup_date)
session = requests.Session()
zendesk = 'https://' + zendesk_subdomain
session.auth = (zendesk_user, zendesk_secret)

# Organise Support backups into a directory named {date of backup} and in relevant sub directories.
triggers_backup_path = os.path.join("support/" + backup_date + "/triggers")
if not os.path.exists(triggers_backup_path):
    os.makedirs(triggers_backup_path)
    
inactive_triggers_backup_path = os.path.join(triggers_backup_path, "inactive/")
if not os.path.exists(inactive_triggers_backup_path):
    os.makedirs(inactive_triggers_backup_path)

automations_backup_path = os.path.join("support/" + backup_date + "/automations")
if not os.path.exists(automations_backup_path):
    os.makedirs(automations_backup_path)
    
inactive_automations_backup_path = os.path.join(automations_backup_path, "inactive/")
if not os.path.exists(inactive_automations_backup_path):
    os.makedirs(inactive_automations_backup_path)

macros_backup_path = os.path.join("support/" + backup_date + "/macros")
if not os.path.exists(macros_backup_path):
    os.makedirs(macros_backup_path)
    
inactive_macros_backup_path = os.path.join(macros_backup_path, "inactive/")
if not os.path.exists(inactive_macros_backup_path):
    os.makedirs(inactive_macros_backup_path)

views_backup_path = os.path.join("support/" + backup_date + "/views")
if not os.path.exists(views_backup_path):
    os.makedirs(views_backup_path)
    
inactive_views_backup_path = os.path.join(views_backup_path, "inactive/")
if not os.path.exists(inactive_views_backup_path):
    os.makedirs(inactive_views_backup_path)

ticket_fields_backup_path = os.path.join("support/" + backup_date + "/ticket_fields")
if not os.path.exists(ticket_fields_backup_path):
    os.makedirs(ticket_fields_backup_path)
    
inactive_ticket_fields_backup_path = os.path.join(ticket_fields_backup_path, "inactive/")
if not os.path.exists(inactive_ticket_fields_backup_path):
    os.makedirs(inactive_ticket_fields_backup_path)

user_fields_backup_path = os.path.join("support/" + backup_date + "/user_fields")
if not os.path.exists(user_fields_backup_path):
    os.makedirs(user_fields_backup_path)
    
inactive_user_fields_backup_path = os.path.join(user_fields_backup_path, "inactive/")
if not os.path.exists(inactive_user_fields_backup_path):
    os.makedirs(inactive_user_fields_backup_path)

organization_fields_backup_path = os.path.join("support/" + backup_date + "/organization_fields")
if not os.path.exists(organization_fields_backup_path):
    os.makedirs(organization_fields_backup_path)
    
inactive_organization_fields_backup_path = os.path.join(organization_fields_backup_path, "inactive/")
if not os.path.exists(inactive_organization_fields_backup_path):
    os.makedirs(inactive_organization_fields_backup_path)

app_installations_backup_path = os.path.join("support/" + backup_date + "/app_installations")
if not os.path.exists(app_installations_backup_path):
    os.makedirs(app_installations_backup_path)
    
inactive_app_installations_backup_path = os.path.join(app_installations_backup_path, "inactive/")
if not os.path.exists(inactive_app_installations_backup_path):
    os.makedirs(inactive_app_installations_backup_path)

log = []

triggers_endpoint = zendesk + '/api/v2/triggers.json'
while triggers_endpoint:
    response = session.get(triggers_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve triggers with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for trigger in data['triggers']:
        url = trigger['url']
        id = trigger['id']
        title = trigger['title']
        safe_title = re.sub('[/:\*\?\>\<\|\s_—]', '_', title)
        active = trigger['active']
        if active:
            backup_path = triggers_backup_path
        else: 
            backup_path = inactive_triggers_backup_path
        filename = safe_title + '.json'
        created = trigger['created_at']
        updated = trigger['updated_at']
        content = json.dumps(trigger, indent=2)
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, title, active, created, updated))

    triggers_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Active', 'Date Created', 'Date Updated') )
    for trigger in log:
        writer.writerow(trigger)

automations_endpoint = zendesk + '/api/v2/automations.json'
while automations_endpoint:
    response = session.get(automations_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve automations with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for automation in data['automations']:
        url = automation['url']
        id = automation['id']
        title = automation['title']
        safe_title = re.sub('[/:\*\?\>\<\|\s_—]', '_', title)
        active = automation['active']
        if active:
            backup_path = automations_backup_path
        else: 
            backup_path = inactive_automations_backup_path
        filename = safe_title + '.json'
        created = automation['created_at']
        updated = automation['updated_at']
        content = json.dumps(automation, indent=2)
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, title, active, created, updated))

    automations_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Active', 'Date Created', 'Date Updated') )
    for automation in log:
        writer.writerow(automation)

macros_endpoint = zendesk + '/api/v2/macros.json'
while macros_endpoint:
    response = session.get(macros_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve macros with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for macro in data['macros']:
        url = macro['url']
        id = macro['id']
        title = macro['title']
        safe_title = re.sub('[/:\*\?\>\<\|\s_—]', '_', title)
        active = macro['active']
        if active:
            backup_path = macros_backup_path
        else: 
            backup_path = inactive_macros_backup_path
        filename = safe_title + '.json'
        created = macro['created_at']
        updated = macro['updated_at']
        content = json.dumps(macro, indent=2)
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, title, active, created, updated))

    macros_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Active', 'Date Created', 'Date Updated') )
    for macro in log:
        writer.writerow(macro)

views_endpoint = zendesk + '/api/v2/views.json'
while views_endpoint:
    response = session.get(views_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve views with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for view in data['views']:
        url = view['url']
        id = view['id']
        title = view['title']
        safe_title = re.sub('[/:\*\?\>\<\|\s_—]', '_', title)
        active = view['active']
        if active:
            backup_path = views_backup_path
        else: 
            backup_path = inactive_views_backup_path
        filename = safe_title + '.json'
        created = view['created_at']
        updated = view['updated_at']
        content = json.dumps(view, indent=2)
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, title, active, created, updated))

    views_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Active', 'Date Created', 'Date Updated') )
    for view in log:
        writer.writerow(view)

ticket_fields_endpoint = zendesk + '/api/v2/ticket_fields.json'
while ticket_fields_endpoint:
    response = session.get(ticket_fields_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve ticket_fields with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for ticket_field in data['ticket_fields']:
        url = ticket_field['url']
        id = ticket_field['id']
        title = ticket_field['title']
        safe_title = re.sub('[/:\*\?\>\<\|\s_—]', '_', title)
        active = ticket_field['active']
        if active:
            backup_path = ticket_fields_backup_path
        else: 
            backup_path = inactive_ticket_fields_backup_path
        filename = safe_title + '.json'
        created = ticket_field['created_at']
        updated = ticket_field['updated_at']
        content = json.dumps(ticket_field, indent=2)
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, title, active, created, updated))

    ticket_fields_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Active', 'Date Created', 'Date Updated') )
    for ticket_field in log:
        writer.writerow(ticket_field)


user_fields_endpoint = zendesk + '/api/v2/user_fields.json'
while user_fields_endpoint:
    response = session.get(user_fields_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve user_fields with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for user_field in data['user_fields']:
        url = user_field['url']
        id = user_field['id']
        title = user_field['title']
        safe_title = re.sub('[/:\*\?\>\<\|\s_—]', '_', title)
        active = user_field['active']
        if active:
            backup_path = user_fields_backup_path
        else: 
            backup_path = inactive_user_fields_backup_path
        filename = safe_title + '.json'
        created = user_field['created_at']
        updated = user_field['updated_at']
        content = json.dumps(user_field, indent=2)
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, title, active, created, updated))

    user_fields_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Active', 'Date Created', 'Date Updated') )
    for user_field in log:
        writer.writerow(user_field)

organization_fields_endpoint = zendesk + '/api/v2/organization_fields.json'
while organization_fields_endpoint:
    response = session.get(organization_fields_endpoint)
    if response.status_code != 200:
        print('Failed to retrieve organization_fields with error {}'.format(response.status_code))
        exit()
    data = response.json()

    for organization_field in data['organization_fields']:
        url = organization_field['url']
        id = organization_field['id']
        title = organization_field['title']
        safe_title = re.sub('[/:\*\?\>\<\|\s_—]', '_', title)
        active = organization_field['active']
        if active:
            backup_path = organization_fields_backup_path
        else: 
            backup_path = inactive_organization_fields_backup_path
        filename = safe_title + '.json'
        created = organization_field['created_at']
        updated = organization_field['updated_at']
        content = json.dumps(organization_field, indent=2)
        with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
           f.write(content) 
        print(filename + ' - copied!')
        log.append((filename, title, active, created, updated))

    organization_fields_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Active', 'Date Created', 'Date Updated') )
    for organization_field in log:
        writer.writerow(organization_field)

app_installations_endpoint = zendesk + '/api/v2/apps/installations.json'
response = session.get(app_installations_endpoint)
if response.status_code != 200:
    print('Failed to retrieve app_installations with error {}'.format(response.status_code))
    exit()
data = response.json()

for app_installation in data['installations']:
    id = app_installation['id']
    app_id = id = app_installation['app_id']
    title = app_installation['settings']['title']
    safe_title = re.sub('[/:\*\?\>\<\|\s_—]', '_', title)
    active = app_installation['enabled']
    if active:
        backup_path = app_installations_backup_path
    else: 
        backup_path = inactive_app_installations_backup_path
    filename = safe_title + '.json'
    content = json.dumps(app_installation, indent=2)
    with open(os.path.join(backup_path, filename), mode='w', encoding='utf-8') as f:
        f.write(content) 
    print(filename + ' - copied!')
    log.append((filename, title, id, app_id, active))

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'ID', 'App ID', 'Active') )
    for app_installation in log:
        writer.writerow(app_installation)

# Get a copy of everything into a private backup folder

# def copyrecursively(source_folder, destination_folder):
# for root, dirs, files in os.walk(source_folder):
#     for item in files:
#         src_path = os.path.join(root, item)
#         dst_path = os.path.join(destination_folder, src_path.replace(source_folder, ""))
#         if os.path.exists(dst_path):
#             if os.stat(src_path).st_mtime > os.stat(dst_path).st_mtime:
#                 shutil.copy2(src_path, dst_path)
#         else:
#             shutil.copy2(src_path, dst_path)
#     for item in dirs:
#         src_path = os.path.join(root, item)
#         dst_path = os.path.join(destination_folder, src_path.replace(source_folder, ""))
#         if not os.path.exists(dst_path):
#             os.mkdir(dst_path)