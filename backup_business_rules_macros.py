import os
import csv
import re
import json
import requests
import getpass

session = requests.Session()
zendesk_subdomain = input('Zendesk subdomain: ')
zendesk_user = input('Zendesk username/token or username: ')
zendesk_secret = getpass.getpass('Zendesk api_token or password: ')
session.auth = (zendesk_user, zendesk_secret)
zendesk = 'https://' + zendesk_subdomain + '.zendesk.com'

triggers_backup_path = os.path.join("triggers")
if not os.path.exists(triggers_backup_path):
    os.makedirs(triggers_backup_path)
    
inactive_triggers_backup_path = os.path.join(triggers_backup_path, "inactive/")
if not os.path.exists(inactive_triggers_backup_path):
    os.makedirs(inactive_triggers_backup_path)

automations_backup_path = os.path.join("automations")
if not os.path.exists(automations_backup_path):
    os.makedirs(automations_backup_path)
    
inactive_automations_backup_path = os.path.join(automations_backup_path, "inactive/")
if not os.path.exists(inactive_automations_backup_path):
    os.makedirs(inactive_automations_backup_path)

macros_backup_path = os.path.join("macros")
if not os.path.exists(macros_backup_path):
    os.makedirs(macros_backup_path)
    
inactive_macros_backup_path = os.path.join(macros_backup_path, "inactive/")
if not os.path.exists(inactive_macros_backup_path):
    os.makedirs(inactive_macros_backup_path)

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
        log.append((filename, title, created, updated))

    triggers_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Date Created', 'Date Updated') )
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
        log.append((filename, title, created, updated))

    automations_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Date Created', 'Date Updated') )
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
        log.append((filename, title, created, updated))

    macros_endpoint = data['next_page']

with open(os.path.join(backup_path, '_log.csv'), mode='wt', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow( ('File', 'Title', 'Date Created', 'Date Updated') )
    for macro in log:
        writer.writerow(macro)