import os
import csv
import re
import json
import requests
import time
import shutil
from datetime import datetime
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version
import unicodedata

def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD',
                                      value).encode('ascii',
                                                    'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')

def create_directory(path):
    os.makedirs(path, exist_ok=True)

def get_zendesk_session():
    session = requests.Session()
    zendesk = f'https://{zendesk_subdomain}'
    zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")
    session.auth = (zendesk_user, zendesk_secret)
    return session, zendesk

def handle_rate_limit(response):
    if response.status_code == 429:
        retry_after = int(response.headers.get('retry-after', 60))
        print(f'Rate limited. Waiting for {retry_after} seconds.')
        time.sleep(retry_after)
        return True
    return False

def fetch_data(session, endpoint):
    while True:
        response = session.get(endpoint)
        if handle_rate_limit(response):
            continue
        if response.status_code != 200:
            raise Exception(f'Failed to retrieve data with error {response.status_code}')
        return response.json()

def backup_asset(asset, backup_path, asset_type):
    # Determine the title key based on asset type and check for existence
    title_key = 'name' if asset_type in ['triggers', 'automations', 'macros', 'views'] else 'title'
    
    # Try to find a valid title from multiple possible keys
    title = None
    for key in [title_key, 'name', 'title', 'label', 'id']:
        if key in asset and asset[key]:
            title = str(asset[key])
            break
    
    # If no title found, use a fallback
    if not title:
        title = f"untitled_{asset.get('id', 'unknown')}"
    
    safe_title = slugify(title)
    filename = f"{safe_title}.json"
    content = json.dumps(asset, indent=2)
    
    with open(os.path.join(backup_path, filename), 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"{filename} - copied!")
    return (filename, title, asset.get('active', True), asset.get('created_at'), asset.get('updated_at'))

def backup_assets(session, zendesk, endpoint, asset_name, response_key, backup_path, inactive_path):
    create_directory(backup_path)
    create_directory(inactive_path)
    
    endpoint_url = f"{zendesk}/api/v2/{endpoint}.json"
    log = []
    
    while endpoint_url:
        data = fetch_data(session, endpoint_url)
        # Use response_key to get the list of assets from the response
        for asset in data[response_key]:
            try:
                path = inactive_path if not asset.get('active', True) else backup_path
                log.append(backup_asset(asset, path, asset_name))
            except Exception as e:
                print(f"Error processing asset {asset.get('id', 'unknown')}: {str(e)}")
                print(f"Asset keys: {list(asset.keys())}")
                # Add a placeholder entry to maintain log consistency
                log.append((f"error_{asset.get('id', 'unknown')}.json", f"ERROR: {str(e)}", False, None, None))
                continue
        
        endpoint_url = data.get('next_page')
    
    write_log(backup_path, log)

def write_log(path, log):
    with open(os.path.join(path, '_log.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(('File', 'Title', 'Active', 'Date Created', 'Date Updated'))
        writer.writerows(log)

def compress_folder(folder_path, output_filename):
    shutil.make_archive(output_filename, 'zip', folder_path)
    print(f"Compressed {folder_path} to {output_filename}.zip")

def main():
    session, zendesk = get_zendesk_session()
    current_date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    assets_base_path = r"C:\Users\AngusMcLauchlan\IT Solver\IT Solver - Documents\Admin\Business\Zendesk\Support"
    
    # Dictionary of asset types to backup with their API endpoints and response keys
    assets = {
        'apps/installations': {'name': 'app_installations', 'response_key': 'installations'},
        'automations': {'name': 'automations', 'response_key': 'automations'},
        'macros': {'name': 'macros', 'response_key': 'macros'},
        'organization_fields': {'name': 'organization_fields', 'response_key': 'organization_fields'},
        'organizations': {'name': 'organizations', 'response_key': 'organizations'},
        'ticket_fields': {'name': 'ticket_fields', 'response_key': 'ticket_fields'},
        'tickets': {'name': 'tickets', 'response_key': 'tickets'},
        'triggers': {'name': 'triggers', 'response_key': 'triggers'},
        'user_fields': {'name': 'user_fields', 'response_key': 'user_fields'},
        'views': {'name': 'views', 'response_key': 'views'}
    }
    
    for endpoint, config in assets.items():
        asset_name = config['name']
        response_key = config['response_key']
        asset_path = os.path.join(assets_base_path, asset_name)
        create_directory(asset_path)
        backup_path = os.path.join(asset_path, current_date)
        inactive_path = os.path.join(backup_path, "inactive")
        
        backup_assets(session, zendesk, endpoint, asset_name, response_key, backup_path, inactive_path)
        
        # Compress the asset folder
        zip_filename = f"{asset_name}_{current_date}"
        compress_folder(backup_path, os.path.join(asset_path, zip_filename))
        
        # Delete the uncompressed folder after successful compression
        if os.path.exists(os.path.join(asset_path, f"{zip_filename}.zip")):
            shutil.rmtree(backup_path)
            print(f"Deleted uncompressed folder: {backup_path}")
        else:
            print(f"Compression failed for {asset_name}. Uncompressed folder not deleted.")

if __name__ == "__main__":
    main()