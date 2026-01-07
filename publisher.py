import requests
import time
import re
import sys
import os
from datetime import datetime, timedelta
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version, test_gcloud_access

# Initialize secrets and session
print("Setting up Zendesk API session in publisher...")

if not test_gcloud_access():
    print("ERROR: Cannot access Google Cloud Secret Manager.")
    sys.exit(1)

zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")
grok_api_key = access_secret_version("billing-sync", "ZENDESK_GROK_API_KEY", "latest")

session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)
session.headers.update({
    'Connection': 'keep-alive',
    'Accept-Encoding': 'gzip, deflate',
    'User-Agent': 'itsolver-zendesk-publisher/1.0'
})

from requests.adapters import HTTPAdapter
_adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50)
session.mount('https://', _adapter)
session.mount('http://', _adapter)

def determine_best_section(article_html, search_query):
    """Use Grok AI to analyze the article content and determine the most relevant section."""
    print("Analyzing article content with AI to determine best section...")

    # Extract clean text content from HTML (remove HTML tags)
    clean_text = re.sub(r'<[^>]+>', '', article_html)
    # Remove extra whitespace
    clean_text = ' '.join(clean_text.split())

    analysis_prompt = f"""
Based on the following knowledge base article content and the context "{search_query}",
determine which Zendesk Help Center section would be most appropriate:

Available sections:
1. Solutions (ID: 200392289) - General solutions for various technical issues, system problems, troubleshooting guides
2. Tips & Tricks (ID: 200392299) - Productivity tips, shortcuts, best practices, efficiency improvements
3. Microsoft 365 (ID: 115001399286) - Microsoft 365, Office 365, Outlook, Exchange, Teams, SharePoint, OneDrive, Windows, Azure, Intune, etc.
4. Google Workspace (ID: 115001312963) - Google Workspace, Gmail, Google Docs, Google Sheets, Google Drive, Google Calendar, etc.

Article Title and Content:
{clean_text[:2000]}... (truncated for analysis)

Respond with ONLY the section number (1-4) and a brief explanation (max 50 words) why this section is most appropriate.
Format: "SECTION_NUMBER: explanation"
"""

    try:
        grok_api_url = "https://api.x.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {grok_api_key}"
        }

        payload = {
            "model": "grok-4-fast-non-reasoning",
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert at categorizing technical content for knowledge bases. Analyze the provided article and determine the most appropriate section based on content, technical focus, and user intent."
                },
                {
                    "role": "user",
                    "content": analysis_prompt
                }
            ],
            "max_tokens": 100,
            "temperature": 0.3
        }

        response = requests.post(grok_api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        grok_response = response.json()
        analysis_result = grok_response['choices'][0]['message']['content'].strip()

        # Parse the result - should be in format "SECTION_NUMBER: explanation"
        if ':' in analysis_result:
            section_num = analysis_result.split(':')[0].strip()
            explanation = analysis_result.split(':', 1)[1].strip()
        else:
            # Fallback if format is unexpected
            section_num = analysis_result.strip()
            explanation = "AI-determined section"

        # Map section number to actual section info
        section_mapping = {
            "1": ("200392289", "Solutions (general area for solutions)"),
            "2": ("200392299", "Tips & Tricks"),
            "3": ("115001399286", "Microsoft 365"),
            "4": ("115001312963", "Google Workspace")
        }

        if section_num in section_mapping:
            section_id, section_name = section_mapping[section_num]
            print(f"AI Analysis: {explanation}")
            return section_id, section_name
        else:
            print(f"Unexpected AI response: {analysis_result}, using Solutions as default")
            return "200392289", "Solutions (general area for solutions)"

    except Exception as e:
        print(f"AI section analysis failed: {e}, using keyword-based fallback")
        # Fallback to simple keyword matching
        content_lower = article_html.lower()
        query_lower = search_query.lower()

        microsoft_keywords = ['microsoft', 'office', 'outlook', 'exchange', 'windows', 'azure', 'teams', 'sharepoint', 'onedrive']
        google_keywords = ['google', 'gmail', 'docs', 'sheets', 'drive', 'workspace', 'gsuite']

        microsoft_score = sum(1 for keyword in microsoft_keywords if keyword in content_lower or keyword in query_lower)
        google_score = sum(1 for keyword in google_keywords if keyword in content_lower or keyword in query_lower)

        if microsoft_score > google_score:
            return "115001399286", "Microsoft 365"
        elif google_score > microsoft_score:
            return "115001312963", "Google Workspace"
        else:
            return "200392289", "Solutions (general area for solutions)"

def generate_content_tags_and_labels(article_html, title, search_query):
    """Generate appropriate content tags and labels based on article content."""
    content_lower = article_html.lower()
    title_lower = title.lower()
    query_lower = search_query.lower()

    # Content tags - these should be existing tag IDs in Zendesk
    # For now, we'll use descriptive names that could match existing tags
    content_tags = []

    # Labels - visible in search results for better ranking
    labels = []

    # Analyze content for relevant tags and labels
    if any(keyword in content_lower or keyword in title_lower or keyword in query_lower
           for keyword in ['windows', 'microsoft', 'office', 'outlook', 'search', 'ctfmon']):
        labels.extend(['windows', 'microsoft', 'troubleshooting', 'search'])
        content_tags.extend(['microsoft', 'windows'])

    if any(keyword in content_lower or keyword in title_lower or keyword in query_lower
           for keyword in ['search', 'taskbar', 'input', 'language']):
        labels.extend(['search', 'taskbar', 'input', 'language'])
        content_tags.extend(['search', 'input'])

    if any(keyword in content_lower or keyword in title_lower or keyword in query_lower
           for keyword in ['update', 'configuration', 'service', 'restart']):
        labels.extend(['updates', 'configuration', 'services'])
        content_tags.extend(['configuration', 'services'])

    if any(keyword in content_lower or keyword in title_lower or keyword in query_lower
           for keyword in ['google', 'workspace', 'gmail', 'docs', 'sheets']):
        labels.extend(['google', 'workspace', 'gmail'])
        content_tags.extend(['google', 'workspace'])

    if any(keyword in content_lower or keyword in title_lower or keyword in query_lower
           for keyword in ['email', 'exchange', '365', 'office']):
        labels.extend(['email', 'exchange', 'office365'])
        content_tags.extend(['email', 'microsoft365'])

    # Remove duplicates and limit to reasonable number
    labels = list(set(labels))[:8]  # Max 8 labels for good SEO
    content_tags = list(set(content_tags))[:5]  # Reasonable limit for content tags

    return content_tags, labels

def upload_to_zendesk_help_center(article_html, title, section_id, search_query):
    """Upload the generated article to Zendesk Help Center."""
    print(f"\nUploading article to Zendesk Help Center section {section_id}...")

    # Get permission_group_id from examples (48395 appears most common)
    permission_group_id = 48395  # From recent examples

    # Generate content tags and labels based on article content
    content_tags, labels = generate_content_tags_and_labels(article_html, title, search_query)

    print(f"Content tags: {', '.join(content_tags)}")
    print(f"Labels: {', '.join(labels)}")

    article_data = {
        "article": {
            "title": title,
            "body": article_html,
            "locale": "en-au",  # Based on subdomain and examples
            "permission_group_id": permission_group_id,
            "user_segment_id": None,  # null in examples
            "draft": True,  # Start as draft for review
            "label_names": labels  # Labels for search ranking (content tags require existing tag IDs)
        },
        "notify_subscribers": False
    }

    url = f"https://{zendesk_subdomain}/api/v2/help_center/sections/{section_id}/articles"

    try:
        response = session.post(url, json=article_data)
        response.raise_for_status()

        result = response.json()
        article_id = result['article']['id']
        print(f"Article uploaded successfully! Article ID: {article_id}")
        print(f"Article URL: https://support.itsolver.net/hc/en-au/articles/{article_id}")

        return article_id

    except requests.RequestException as e:
        print(f"Failed to upload article: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"Response: {e.response.text}")
        return None

def publish_file(file_path):
    """Read a file and publish it to Zendesk."""
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        return

    print(f"Reading file: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract Title
    title_match = re.search(r'<h1>(.*?)</h1>', content, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
        # Remove the <h1> from the body because Zendesk adds the title automatically
        body = re.sub(r'<h1>.*?</h1>\s*', '', content, count=1, flags=re.IGNORECASE)
    else:
        # Fallback: Use filename as title if no H1 found
        title = os.path.splitext(os.path.basename(file_path))[0].replace('-', ' ')
        body = content

    print(f"Detected Title: {title}")

    # Determine Section
    print("Determining best section...")
    section_id, section_name = determine_best_section(body, title)
    print(f"Selected Section: {section_name} ({section_id})")

    # Upload
    print("Uploading...")
    upload_to_zendesk_help_center(body, title, section_id, title)

def get_section_choice(article_html, search_query):
    """Wrapper for determine_best_section that aligns with the old script's call signature, if needed."""
    auto_section_id, auto_section_name = determine_best_section(article_html, search_query)
    print(f"\nAutomatically selected section: {auto_section_name} (ID: {auto_section_id})")
    return auto_section_id

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python publisher.py <path_to_html_file>")
        sys.exit(1)
    
    # Handle paths with spaces or quotes
    file_path = sys.argv[1].strip('"').strip("'")
    publish_file(file_path)
