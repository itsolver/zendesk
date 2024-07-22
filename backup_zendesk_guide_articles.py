import requests
import json
import os
import time
import csv
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# Define necessary variables
ARTICLES_BACKUP_PATH = f'G:\\Shared drives\\Business\\Zendesk\\Guide\\articles'
zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")

# Check if the path exists, and create it if it doesn't
if not os.path.exists(ARTICLES_BACKUP_PATH):
    os.makedirs(ARTICLES_BACKUP_PATH)

session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)
log = []

def download_article(article):
    article_id = article['id']
    title = article['title']
    filename = f"{article_id}.json"
    full_path = os.path.join(ARTICLES_BACKUP_PATH, filename)
    
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            existing_article = json.load(f)
        existing_updated_at = datetime.fromisoformat(existing_article['updated_at'].rstrip('Z'))
        current_updated_at = datetime.fromisoformat(article['updated_at'].rstrip('Z'))
        
        if existing_updated_at >= current_updated_at:
            print(f"{filename} is up to date, skipping.")
            return (filename, title, article['created_at'], article['updated_at'])
    
    # Fetch full article details
    article_endpoint = f"https://{zendesk_subdomain}/api/v2/help_center/articles/{article_id}.json"
    response = session.get(article_endpoint)
    if response.status_code != 200:
        print(f'Failed to retrieve article {article_id} with error {response.status_code}')
        return None
    
    full_article = response.json()['article']
    
    content = json.dumps(full_article, indent=2)
    with open(full_path, mode='w', encoding='utf-8') as f:
        f.write(content)
    print(f"{filename} - copied!")
    return (filename, title, full_article['created_at'], full_article['updated_at'])

articles_endpoint = f"https://{zendesk_subdomain}/api/v2/help_center/articles.json"

while articles_endpoint:
    response = session.get(articles_endpoint)
    if response.status_code == 429:
        print('Rate limited! Please wait.')
        time.sleep(int(response.headers['retry-after']))
        continue
    if response.status_code != 200:
        print(f'Failed to retrieve articles with error {response.status_code}')
        exit()
    data = response.json()

    with ThreadPoolExecutor() as executor:
        results = list(executor.map(download_article, data['articles']))
        log.extend([result for result in results if result is not None])

    articles_endpoint = data['next_page']
    if not articles_endpoint:
        print('Reached the end of articles.')
        break

with open(os.path.join(ARTICLES_BACKUP_PATH, '_log.csv'), mode='wt', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow(('File', 'Title', 'Date Created', 'Date Updated'))
    for article in log:
        writer.writerow(article)
