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
    # Determine the title key based on asset type
    title_key = 'name' if asset_type in ['triggers', 'automations', 'macros', 'views'] else 'title'
    safe_title = slugify(asset[title_key])
    filename = f"{safe_title}.json"
    content = json.dumps(asset, indent=2)
    
    with open(os.path.join(backup_path, filename), 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"{filename} - copied!")
    return (filename, asset[title_key], asset.get('active', True), asset.get('created_at'), asset.get('updated_at'))

def backup_assets(session, zendesk, endpoint, asset_name, backup_path, inactive_path):
    create_directory(backup_path)
    create_directory(inactive_path)
    
    endpoint_url = f"{zendesk}/api/v2/{endpoint}.json"
    log = []
    
    while endpoint_url:
        data = fetch_data(session, endpoint_url)
        # Use asset_name to get the list of assets from the response
        for asset in data[asset_name]:
            path = inactive_path if not asset.get('active', True) else backup_path
            log.append(backup_asset(asset, path, asset_name))
        
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
    
    # Dictionary of asset types to backup with their API endpoints
    assets = {
        'apps/installations': 'app_installations',
        'automations': 'automations',
        'macros': 'macros',
        'organization_fields': 'organization_fields',
        'organizations': 'organizations',
        'ticket_fields': 'ticket_fields',
        'tickets': 'tickets',
        'triggers': 'triggers',
        'user_fields': 'user_fields',
        'views': 'views'
    }
    
    for endpoint, asset_name in assets.items():
        asset_path = os.path.join(assets_base_path, asset_name)
        create_directory(asset_path)
        backup_path = os.path.join(asset_path, current_date)
        inactive_path = os.path.join(backup_path, "inactive")
        
        backup_assets(session, zendesk, endpoint, asset_name, backup_path, inactive_path)
        
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