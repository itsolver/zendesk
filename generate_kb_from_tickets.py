import requests
import time
import re
import threading
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version, test_gcloud_access
from typing import List, Dict
from publisher import upload_to_zendesk_help_center, get_section_choice

# Configuration
BATCH_SIZE = 100
MAX_WORKERS = 4

# Rate Limiting Configuration
MAX_REQUESTS_PER_MINUTE = 350
MAX_REQUESTS_PER_SECOND = MAX_REQUESTS_PER_MINUTE / 60.0
REQUEST_INTERVAL = 1.0 / MAX_REQUESTS_PER_SECOND

class RateLimiter:
    """Thread-safe rate limiter for Zendesk API calls."""

    def __init__(self, max_requests_per_minute=MAX_REQUESTS_PER_MINUTE):
        self.max_requests_per_minute = max_requests_per_minute
        self.request_times = []
        self.lock = threading.Lock()
        self.total_requests = 0
        self.rate_limited_count = 0

    def wait_if_needed(self):
        """Wait if we're approaching rate limits."""
        with self.lock:
            now = datetime.now()
            cutoff = now - timedelta(minutes=1)
            self.request_times = [req_time for req_time in self.request_times if req_time > cutoff]

            if len(self.request_times) >= self.max_requests_per_minute:
                oldest_request = min(self.request_times)
                wait_time = 61 - (now - oldest_request).total_seconds()
                if wait_time > 0:
                    print(f"Rate limiting: waiting {wait_time:.1f}s")
                    time.sleep(wait_time)

            self.request_times.append(now)
            self.total_requests += 1

    def handle_rate_limit_response(self, response):
        """Handle 429 responses."""
        with self.lock:
            if response.status_code == 429:
                self.rate_limited_count += 1
                retry_after = int(response.headers.get('retry-after', 60))
                print(f'Rate limited! Waiting {retry_after}s')
                time.sleep(retry_after)
                return True
            return False

    def get_stats(self):
        """Get current rate limiting statistics."""
        with self.lock:
            now = datetime.now()
            cutoff = now - timedelta(minutes=1)
            recent_requests = len([req_time for req_time in self.request_times if req_time > cutoff])

            return {
                'total_requests': self.total_requests,
                'requests_last_minute': recent_requests,
                'rate_limited_count': self.rate_limited_count
            }

# Initialize rate limiter
rate_limiter = RateLimiter()

# Initialize session
print("Setting up Zendesk API session...")

# Test Google Cloud access
if not test_gcloud_access():
    print("ERROR: Cannot access Google Cloud Secret Manager.")
    exit(1)

zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")
grok_api_key = access_secret_version("billing-sync", "ZENDESK_GROK_API_KEY", "latest")
session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)
session.headers.update({
    'Connection': 'keep-alive',
    'Accept-Encoding': 'gzip, deflate',
    'User-Agent': 'itsolver-zendesk-kb-generator/1.0'
})

# Increase HTTP connection pool
from requests.adapters import HTTPAdapter
_adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50)
session.mount('https://', _adapter)
session.mount('http://', _adapter)

def handle_rate_limit(response):
    """Handle API rate limiting."""
    return rate_limiter.handle_rate_limit_response(response)

def fetch_data(endpoint):
    """Fetch data from API endpoint with rate limiting."""
    while True:
        rate_limiter.wait_if_needed()
        response = session.get(endpoint)

        if handle_rate_limit(response):
            continue

        if response.status_code != 200:
            print(f"[DEBUG] Non-200 from {endpoint} → {response.status_code}")
            raise requests.RequestException(f'Failed to retrieve data from {endpoint} with error {response.status_code}')

        return response.json()

def fetch_data_with_retries(endpoint, max_retries=3):
    """Fetch data with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return fetch_data(endpoint)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            wait_time = (2 ** attempt) + 1
            print(f"Request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {str(e)}")
            time.sleep(wait_time)

def search_tickets(query: str, max_results: int = 100) -> List[Dict]:
    """Search Zendesk tickets using the search API."""
    print(f"Searching tickets for: '{query}'")

    # Use Zendesk search API
    search_endpoint = f"https://{zendesk_subdomain}/api/v2/search.json?query={requests.utils.quote(query)}&sort_by=created_at&sort_order=desc"

    tickets = []
    page_count = 0

    while search_endpoint and len(tickets) < max_results:
        page_count += 1
        print(f"Fetching search results page {page_count}...")

        try:
            data = fetch_data_with_retries(search_endpoint)
        except Exception as e:
            print(f"Failed to fetch search results page {page_count}: {e}")
            break

        if not data.get('results'):
            print("No more search results found.")
            break

        # Filter to only tickets (search API returns mixed results)
        page_tickets = [result for result in data['results'] if result.get('result_type') == 'ticket']

        # Limit to max_results
        remaining_slots = max_results - len(tickets)
        tickets_to_add = page_tickets[:remaining_slots]
        tickets.extend(tickets_to_add)

        print(f"Found {len(page_tickets)} tickets on page {page_count}, added {len(tickets_to_add)} to results")

        if len(tickets) >= max_results:
            print(f"Reached maximum results limit of {max_results}")
            break

        # Get next page
        search_endpoint = data.get('next_page')

    print(f"Search completed. Found {len(tickets)} tickets matching the query.")
    return tickets

def get_ticket_audits(ticket_id: int) -> List[Dict]:
    """Get all audit events for a ticket."""
    audits_endpoint = f"https://{zendesk_subdomain}/api/v2/tickets/{ticket_id}/audits.json"
    audits = []

    while audits_endpoint:
        rate_limiter.wait_if_needed()
        response = session.get(audits_endpoint)

        if handle_rate_limit(response):
            continue

        if response.status_code != 200:
            print(f"Failed to get audits for ticket {ticket_id}: HTTP {response.status_code}")
            break

        data = response.json()
        audits.extend(data["audits"])
        audits_endpoint = data.get("next_page")

    return audits

def sanitize_ticket_data(ticket: Dict, audits: List[Dict]) -> Dict:
    """Remove personal information from ticket and audit data."""
    # Create a copy to avoid modifying original
    sanitized = {
        'ticket_id': ticket.get('id'),
        'subject': ticket.get('subject', ''),
        'description': ticket.get('description', ''),
        'status': ticket.get('status'),
        'priority': ticket.get('priority'),
        'type': ticket.get('type'),
        'tags': ticket.get('tags', []),
        'created_at': ticket.get('created_at'),
        'updated_at': ticket.get('updated_at'),
        'solved_at': ticket.get('solved_at'),
        'audits': []
    }

    # Sanitize description - remove emails, phone numbers, names, etc.
    if sanitized['description']:
        sanitized['description'] = sanitize_text(sanitized['description'])

    # Sanitize subject
    if sanitized['subject']:
        sanitized['subject'] = sanitize_text(sanitized['subject'])

    # Process audits
    for audit in audits:
        sanitized_audit = {
            'id': audit.get('id'),
            'created_at': audit.get('created_at'),
            'events': []
        }

        for event in audit.get('events', []):
            sanitized_event = {
                'type': event.get('type'),
                'field_name': event.get('field_name'),
                'value': event.get('value'),
                'previous_value': event.get('previous_value')
            }

            # Sanitize text values
            if isinstance(sanitized_event['value'], str):
                sanitized_event['value'] = sanitize_text(sanitized_event['value'])
            if isinstance(sanitized_event['previous_value'], str):
                sanitized_event['previous_value'] = sanitize_text(sanitized_event['previous_value'])

            # Handle comment events specially
            if event.get('type') == 'Comment':
                comment_data = event.get('body', '')
                if isinstance(comment_data, str):
                    sanitized_event['body'] = sanitize_text(comment_data)
                else:
                    sanitized_event['body'] = comment_data

            sanitized_audit['events'].append(sanitized_event)

        sanitized['audits'].append(sanitized_audit)

    return sanitized

def sanitize_text(text: str) -> str:
    """Remove personal information from text while preserving technical content."""
    if not text:
        return text

    # Define common technical terms and service names to preserve
    # These are IT/technical terms that should NOT be redacted
    technical_terms = {
        # Microsoft services and products
        'Windows', 'Microsoft', 'Office', 'Outlook', 'Excel', 'Word', 'PowerPoint',
        'OneDrive', 'SharePoint', 'Teams', 'Exchange', 'Azure', 'ActiveDirectory',
        'Intune', 'Defender', 'BitLocker', 'Hyper-V', 'PowerShell',
        # Google services
        'Google', 'Gmail', 'Chrome', 'Drive', 'Docs', 'Sheets', 'Workspace',
        # Common software and technical terms
        'Windows Search', 'CtfMon', 'Ctfmon.exe', 'System32', 'Registry',
        'TaskManager', 'EventViewer', 'Services.msc', 'Regedit',
        # File systems and protocols
        'NTFS', 'FAT32', 'HTTP', 'HTTPS', 'DNS', 'DHCP', 'TCP', 'IP',
        # Error types
        'Error', 'Warning', 'Exception', 'Timeout', 'Failed',
    }

    # Remove email addresses (but preserve [context])
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL_REDACTED]', text)

    # Remove phone numbers (various formats)
    text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE_REDACTED]', text)
    text = re.sub(r'\(\d{3}\)\s*\d{3}[-.]?\d{4}', '[PHONE_REDACTED]', text)

    # Remove URLs that might contain personal/organization info, but preserve the domain type
    def redact_url(match):
        url = match.group(0)
        # Preserve common public domains that are technical
        if any(domain in url.lower() for domain in ['microsoft.com', 'google.com', 'github.com', 'stackoverflow.com']):
            return url
        return '[URL_REDACTED]'
    
    text = re.sub(r'https?://[^\s]+', redact_url, text)

    # Intelligently handle names - only redact if it's clearly a person name, not a technical term
    words = text.split()
    for i, word in enumerate(words):
        # Skip if it's a known technical term
        if word in technical_terms or word.lower() in [t.lower() for t in technical_terms]:
            continue
        
        # Skip single capital letters (likely acronyms like "I" or variables)
        if len(word) <= 1:
            continue
        
        # Skip if it looks like a file path or command
        if '\\' in word or '/' in word or '.' in word and word.endswith(('.exe', '.dll', '.sys', '.log', '.txt', '.bat', '.ps1', '.msc')):
            continue
        
        # Skip if it's all caps (likely an acronym like API, DNS, HTTP)
        if word.isupper() and len(word) > 1:
            continue
        
        # Skip error codes and hex values
        if word.startswith('0x') or (word.startswith('ERR') or word.startswith('HR')):
            continue
        
        # Only redact if it's a capitalized word followed by another capitalized word (likely person name)
        # AND not at start of sentence
        if i > 0 and len(word) > 2 and word[0].isupper() and word[1:].islower():
            # Check if next word is also capitalized (FirstName LastName pattern)
            if i + 1 < len(words):
                next_word = words[i + 1]
                if len(next_word) > 2 and next_word[0].isupper() and next_word[1:].islower():
                    # Likely a person name
                    words[i] = '[NAME_REDACTED]'
                    words[i + 1] = '[NAME_REDACTED]'
    
    text = ' '.join(words)
    
    # Clean up multiple consecutive redactions
    text = re.sub(r'\[NAME_REDACTED\](\s+\[NAME_REDACTED\])+', '[NAME_REDACTED]', text)

    return text

def generate_kb_article_with_grok(ticket_data: List[Dict], search_query: str) -> str:
    """Use Grok API to generate a knowledge base article from ticket data."""

    # Prepare the data for Grok
    context = f"""
Based on analyzing {len(ticket_data)} Zendesk support tickets related to: "{search_query}"

Here are the key patterns and solutions extracted from the tickets:

"""

    # Summarize common issues and solutions
    issues = []
    solutions = []
    subjects = []

    for ticket in ticket_data:
        if ticket.get('subject'):
            subjects.append(ticket['subject'])
        if ticket.get('description'):
            issues.append(ticket['description'])

        # Extract solutions from audit comments
        for audit in ticket.get('audits', []):
            for event in audit.get('events', []):
                if event.get('type') == 'Comment' and event.get('body'):
                    body = event['body']
                    # Filter out very short comments (likely just "thanks" or single words)
                    if len(body.strip()) > 20:
                        solutions.append(body)

    # Quality check: ensure we have enough content to generate a good article
    total_content_length = sum(len(s) for s in subjects) + sum(len(i) for i in issues) + sum(len(s) for s in solutions)
    
    print("Data quality check:")
    print(f"  - Subjects: {len(subjects)}")
    print(f"  - Issue descriptions: {len(issues)}")
    print(f"  - Solution comments: {len(solutions)}")
    print(f"  - Total content length: {total_content_length} characters")
    
    if total_content_length < 200:
        print(f"⚠ WARNING: Very little content available ({total_content_length} chars). Article quality may be poor.")
    
    if not solutions:
        print("⚠ WARNING: No solution comments found. Article will lack specific troubleshooting steps.")

    context += f"""
Ticket Subjects (what users reported):
{chr(10).join(f"- {subject}" for subject in subjects[:10])}

Common Issues Identified (initial problem descriptions):
{chr(10).join(f"- {issue[:300]}..." if len(issue) > 300 else f"- {issue}" for issue in issues[:10])}

Solutions and Resolution Steps (from support interactions):
{chr(10).join(f"- {solution[:400]}..." if len(solution) > 400 else f"- {solution}" for solution in solutions[:20])}

Based on the above ticket data, generate a comprehensive knowledge base article that:
1. Create SEO and GEO optimized headings (H2-H6) that:
   - Include the main problem/solution keywords naturally in headings
   - Use descriptive, long-tail keywords that users actually search for
   - Structure headings for AI comprehension (clear problem-solution format)
   - Show expertise and authority in the topic through heading hierarchy
   - Make content scannable for both humans and AI models with semantic heading structure
   - Use question-based headings when appropriate (e.g., "How to Fix...", "Why Does... Happen?")
   - Include action-oriented headings (e.g., "Step-by-Step Solution", "Troubleshooting Guide")
2. Identifies the main problem or question this addresses in the opening paragraph
3. Provides a clear, step-by-step solution with numbered lists and descriptive subheadings
4. Includes comprehensive troubleshooting tips under dedicated headings
5. Is written in a professional, helpful tone that demonstrates expertise
6. Uses semantic HTML structure with proper heading hierarchy (H2 for main sections, H3 for subsections, etc.)
7. Contains NO personal information or specific customer details
8. Is generalized to help future customers with similar issues
9. Includes relevant keywords naturally throughout headings and content for search optimization

IMPORTANT: Include these EXACT sections at the end of the article (copy them verbatim):

<!-- Feedback section -->
<h2>Was this helpful?</h2>
<p>
  If you've followed this guide, we'd love to hear about your experience. Please leave a comment below
  to share whether this guide helped you achieve your goal. If you found an alternative approach
  that worked, we encourage you to share that as well. Your feedback helps us improve our documentation
  and assists others in the community.
</p>

<!-- Further assistance section -->
<h2>Need Further Assistance?</h2>
<p>
  If you need additional support or would like personalized guidance, we're here to help.
  Check out our dedicated support plans at
  <a href="https://itsolver.net/support-plans?utm_source=zendesk&utm_medium=kb_article&utm_campaign=support_referral"
     target="_blank">IT Solver Support Plans</a>
  for expert assistance tailored to your needs.
</p>

Format the output as clean HTML content WITHOUT an H1 heading (the title is set separately). Do NOT include:
- DOCTYPE declaration
- HTML, HEAD, or BODY tags
- Any CSS styling or STYLE tags
- Any meta tags
- H1 headings (title is provided separately)

Start directly with content like <p>, <h2>, <ul>, etc., and include only the article body content with standard HTML tags.
"""

    # Use Grok API to generate the article
    grok_api_url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {grok_api_key}"
    }

    payload = {
        "model": "grok-4-fast-reasoning",
        "messages": [
            {
                "role": "system",
                "content": """You are an expert technical writer creating knowledge base articles for IT support. 
Your articles must be:
- Highly detailed with specific technical steps (commands, registry paths, service names, error codes)
- Professional but practical and actionable
- Well-structured with semantic HTML headings (H2-H6)
- Include keyboard shortcuts in <kbd> tags and code/commands in <code> tags
- Optimized for both human readers and AI/search engines

Do NOT generate generic placeholder content. Every step must be specific and actionable.
If the provided ticket data lacks detail, infer likely solutions based on the technical domain and best practices."""
            },
            {
                "role": "user",
                "content": context
            }
        ],
        "max_tokens": 6000,
        "temperature": 0.7
    }

    try:
        print("Generating knowledge base article with Grok AI...")
        response = requests.post(grok_api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        grok_response = response.json()
        article_content = grok_response['choices'][0]['message']['content']

        # Quality check: ensure the article is substantial
        if len(article_content) < 500:
            raise ValueError(f"Generated article is too short ({len(article_content)} chars). This indicates poor quality content.")

        # Check for generic placeholder content that indicates poor generation
        generic_indicators = [
            "verify the basic configuration",
            "check for any recent changes",
            "issues tagged as",
        ]
        content_lower = article_content.lower()
        if any(indicator in content_lower for indicator in generic_indicators):
            raise ValueError("Generated article contains generic placeholder content. This indicates the AI had insufficient information to work with.")

        print(f"[OK] Generated high-quality article ({len(article_content)} characters)")
        return article_content

    except Exception as e:
        print(f"\n[ERROR] Failed to generate article with Grok API: {e}")
        print("ABORTING: Cannot generate article without AI assistance.")
        print("Possible reasons:")
        print("  - API connection failed")
        print("  - Generated content was too generic/low quality")
        print("  - Insufficient ticket data or too much sanitization")
        raise e

def main():
    """Main function to generate KB article from ticket search or text file."""
    print("=== Zendesk Knowledge Base Article Generator ===")
    print("This tool searches Zendesk tickets OR processes text files to generate KB articles.")
    print()

    # Get user input - support command line args
    input_source = None
    search_query = None
    
    if len(sys.argv) > 1:
        input_source = sys.argv[1]
    else:
        input_source = input("Enter search query for tickets OR path to text file (e.g., content.txt): ").strip()
        if not input_source:
            print("Input cannot be empty.")
            return

    # Determine if input is a file path or search query
    is_file = input_source.endswith('.txt') or input_source.endswith('.md') or '/' in input_source or '\\' in input_source
    
    if is_file:
        # Text file mode
        print("\n[MODE: Text File Input]")
        try:
            ticket_data = parse_text_file_content(input_source)
            search_query = ticket_data[0]['subject']  # Use title as search query for section determination
        except Exception as e:
            print(f"Failed to parse text file: {e}")
            return
    else:
        # Zendesk search mode
        print("\n[MODE: Zendesk Ticket Search]")
        search_query = input_source
        max_results = 10  # Fixed maximum for optimal analysis
        
        # Search tickets
        print(f"\nSearching for up to {max_results} tickets matching: '{search_query}'")
        tickets = search_tickets(search_query, max_results)

        if not tickets:
            print("No tickets found matching the search query.")
            return

        print(f"\nFound {len(tickets)} tickets. Fetching audit data...")

        # Fetch audits for all tickets
        ticket_data = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            audit_results = list(executor.map(get_ticket_audits, [t['id'] for t in tickets]))

        # Process and sanitize data
        print("Processing and sanitizing ticket data...")
        for i, (ticket, audits) in enumerate(zip(tickets, audit_results)):
            sanitized = sanitize_ticket_data(ticket, audits)
            ticket_data.append(sanitized)

            if (i + 1) % 10 == 0:
                print(f"Processed {i + 1}/{len(tickets)} tickets")

        print(f"\nProcessed {len(ticket_data)} tickets successfully.")

    # Generate KB article
    print("\nGenerating knowledge base article...")
    article_html = generate_kb_article_with_grok(ticket_data, search_query)

    # Save the article
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"kb_article_{timestamp}.html"

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(article_html)

    print(f"\nKnowledge base article generated and saved to: {filename}")
    print("\nArticle Preview (first 500 characters):")
    print("-" * 50)
    print(article_html[:500] + "..." if len(article_html) > 500 else article_html)
    print("-" * 50)

    # Create SEO/GEO optimized title
    if is_file:
        # For text files, use the title as-is if it's already a how-to, otherwise enhance it
        if search_query.lower().startswith(('how to', 'fix', 'troubleshoot', 'resolve', 'stop', 'disable')):
            article_title = search_query
        else:
            article_title = f"How to Fix: {search_query}"
    else:
        # For Zendesk search, create descriptive title from query
        clean_query = search_query.replace('_', ' ').replace('-', ' ').title()
        article_title = f"How to Resolve {clean_query} Issues - Complete Troubleshooting Guide"

    # Upload to Zendesk Help Center
    section_id = get_section_choice(article_html, search_query)
    if section_id:
        article_id = upload_to_zendesk_help_center(article_html, article_title, section_id, search_query)
        if article_id:
            print("\nArticle successfully uploaded to Zendesk Help Center as a draft!")
            print(f"You can review/edit it at: https://support.itsolver.net/hc/en-au/articles/{article_id}")
    else:
        print("Upload skipped.")

    # Print statistics
    stats = rate_limiter.get_stats()
    print("\nAPI Statistics:")
    print(f"- Total API requests: {stats['total_requests']}")
    print(f"- Rate limited events: {stats['rate_limited_count']}")

if __name__ == "__main__":
    main()
