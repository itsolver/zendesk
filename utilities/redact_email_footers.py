#!/usr/bin/env python3
"""
Zendesk Email Footer Redaction Tool

This script redacts annoying email disclaimers from Zendesk ticket comments.
It uses the Zendesk API to identify and redact disclaimer text that appears
in email footers, making ticket comments more mobile-friendly.

Usage Examples:
    # Test with ticket 27777 (dry run - see what would be redacted)
    python utilities/redact_email_footers.py --ticket 27777 --dry-run

    # Actually redact disclaimers in ticket 27777
    python utilities/redact_email_footers.py --ticket 27777

    # Use custom disclaimer text
    python utilities/redact_email_footers.py --ticket 27777 --disclaimer "custom disclaimer text"

    # Provide API token directly (alternative to Secret Manager)
    python utilities/redact_email_footers.py --ticket 27777 --api-token "your_api_token_here"

    # Or set environment variable: export ZENDESK_API_TOKEN="your_api_token"

Authentication Options (in order of precedence):
    1. --api-token command line argument
    2. ZENDESK_API_TOKEN environment variable
    3. Google Cloud Secret Manager (project: billing-sync, secret: ZENDESK_API_TOKEN)

Requirements:
    - Zendesk API access with appropriate permissions
    - requests library
    - Optional: Google Cloud Secret Manager access for automatic token retrieval

Features:
    - Rate limiting to respect Zendesk API limits (350 req/min)
    - Dry run mode to preview changes
    - Supports both plain text and HTML comment bodies
    - Redacts using Zendesk's native <redact> tags
    - Works with closed tickets and archived tickets
"""

import requests
import json
import re
import time
import argparse
import sys
import os
from datetime import datetime, timedelta
import threading

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version, test_gcloud_access

# Default disclaimer text to redact
DEFAULT_DISCLAIMER = """This message contains information which may be confidential and privileged. Unless you are the intended recipient (or authorized to receive this message for the intended recipient), you may not use, copy, disseminate or disclose to anyone the message or any information contained in the message. If you have received the message in error, please advise the sender by reply e-mail, and delete the message. Thank you very much."""

# Rate Limiting Configuration
MAX_REQUESTS_PER_MINUTE = 350
REQUEST_INTERVAL = 60.0 / MAX_REQUESTS_PER_MINUTE

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

            # Remove requests older than 1 minute
            cutoff = now - timedelta(minutes=1)
            self.request_times = [req_time for req_time in self.request_times if req_time > cutoff]

            # Check if we need to wait
            if len(self.request_times) >= self.max_requests_per_minute:
                oldest_request = min(self.request_times)
                wait_time = 61 - (now - oldest_request).total_seconds()
                if wait_time > 0:
                    print(f"Rate limiting: waiting {wait_time:.1f}s")
                    time.sleep(wait_time)

            # Add current request time
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

def setup_zendesk_session(api_token=None):
    """Set up authenticated Zendesk API session."""
    print("Setting up Zendesk API session...")

    # Try to get API token from parameter first, then environment, then Secret Manager
    if api_token:
        zendesk_secret = api_token
        print("Using API token from command line argument")
    elif os.environ.get('ZENDESK_API_TOKEN'):
        zendesk_secret = os.environ.get('ZENDESK_API_TOKEN')
        print("Using API token from ZENDESK_API_TOKEN environment variable")
    else:
        # Fall back to Google Cloud Secret Manager
        if not test_gcloud_access():
            print("ERROR: Cannot access Google Cloud Secret Manager.")
            print("Please either:")
            print("1. Set the ZENDESK_API_TOKEN environment variable")
            print("2. Provide the API token via --api-token argument")
            print("3. Ensure Google Cloud SDK is installed and configured")
            sys.exit(1)

        try:
            zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")
            print("Using API token from Google Cloud Secret Manager")
        except Exception as e:
            print(f"ERROR: Failed to retrieve Zendesk API token: {e}")
            print("Please set ZENDESK_API_TOKEN environment variable or use --api-token")
            sys.exit(1)

    # Create session with authentication
    session = requests.Session()
    session.auth = (zendesk_user, zendesk_secret)
    session.headers.update({
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    })

    return session

def make_api_request(session, method, url, **kwargs):
    """Make API request with rate limiting and error handling."""
    rate_limiter.wait_if_needed()

    while True:
        response = session.request(method, url, **kwargs)

        if rate_limiter.handle_rate_limit_response(response):
            continue

        if response.status_code not in [200, 201, 204]:
            error_msg = f"API request failed: {response.status_code} - {response.text}"
            print(error_msg)
            response.raise_for_status()

        return response

def get_ticket_comments(session, ticket_id):
    """Fetch all comments for a ticket."""
    base_url = f"https://{zendesk_subdomain}/api/v2"
    url = f"{base_url}/tickets/{ticket_id}/comments.json"

    print(f"Fetching comments for ticket {ticket_id}...")

    comments = []
    while url:
        response = make_api_request(session, 'GET', url)
        data = response.json()

        comments.extend(data.get('comments', []))
        url = data.get('next_page')

    print(f"Found {len(comments)} comments in ticket {ticket_id}")
    return comments

def find_disclaimer_in_comment(comment, disclaimer_text):
    """Find disclaimer text in a comment and return position information."""
    body = comment.get('body', '')
    html_body = comment.get('html_body', '')

    # Escape special regex characters in disclaimer
    escaped_disclaimer = re.escape(disclaimer_text.strip())

    # Look for disclaimer in both plain text and HTML
    text_match = re.search(escaped_disclaimer, body, re.IGNORECASE | re.DOTALL)
    html_match = re.search(escaped_disclaimer, html_body, re.IGNORECASE | re.DOTALL)

    if text_match or html_match:
        return {
            'comment_id': comment['id'],
            'has_disclaimer': True,
            'body_match': text_match is not None,
            'html_match': html_match is not None,
            'author': comment.get('author', {}).get('name', 'Unknown'),
            'created_at': comment.get('created_at', ''),
            'is_public': comment.get('public', False)
        }

    return None

def redact_comment_disclaimer(session, ticket_id, comment_id, disclaimer_text):
    """Redact disclaimer text from a comment using Zendesk API."""
    base_url = f"https://{zendesk_subdomain}/api/v2"

    # Get the current comment to see its content
    comment_url = f"{base_url}/tickets/{ticket_id}/comments/{comment_id}.json"
    response = make_api_request(session, 'GET', comment_url)
    comment = response.json().get('comment', {})

    html_body = comment.get('html_body', '')
    if not html_body:
        print(f"Warning: No HTML body found for comment {comment_id}")
        return False

    # Escape special regex characters
    escaped_disclaimer = re.escape(disclaimer_text.strip())

    # Replace disclaimer with redaction tags
    redacted_html = re.sub(
        escaped_disclaimer,
        '<redact>REDACTED EMAIL DISCLAIMER</redact>',
        html_body,
        flags=re.IGNORECASE | re.DOTALL
    )

    if redacted_html == html_body:
        print(f"No disclaimer found in comment {comment_id}")
        return False

    # Prepare redaction request
    redaction_url = f"{base_url}/comment_redactions/{comment_id}.json"
    payload = {
        'comment_redaction': {
            'html_body': redacted_html
        }
    }

    # Make the redaction request
    response = make_api_request(session, 'PUT', redaction_url, json=payload)

    if response.status_code in [200, 201, 204]:
        print(f"✓ Successfully redacted disclaimer in comment {comment_id}")
        return True
    else:
        print(f"✗ Failed to redact comment {comment_id}: {response.status_code}")
        return False

def process_ticket(ticket_id, disclaimer_text, dry_run=False, api_token=None):
    """Process a ticket to redact disclaimers in all comments."""
    session = setup_zendesk_session(api_token)

    try:
        # Get all comments for the ticket
        comments = get_ticket_comments(session, ticket_id)

        if not comments:
            print(f"No comments found for ticket {ticket_id}")
            return

        # Find comments with disclaimers
        comments_with_disclaimers = []
        for comment in comments:
            result = find_disclaimer_in_comment(comment, disclaimer_text)
            if result:
                comments_with_disclaimers.append(result)

        if not comments_with_disclaimers:
            print(f"No disclaimers found in ticket {ticket_id}")
            return

        print(f"\nFound {len(comments_with_disclaimers)} comments with disclaimers:")
        for comment_info in comments_with_disclaimers:
            public_status = "Public" if comment_info['is_public'] else "Private"
            print(f"  - Comment {comment_info['comment_id']} by {comment_info['author']} ({public_status})")
            print(f"    Created: {comment_info['created_at']}")

        if dry_run:
            print(f"\nDRY RUN: Would redact disclaimers from {len(comments_with_disclaimers)} comments")
            return

        # Redact disclaimers
        print(f"\nRedacting disclaimers from {len(comments_with_disclaimers)} comments...")
        successful_redactions = 0

        for comment_info in comments_with_disclaimers:
            if redact_comment_disclaimer(session, ticket_id, comment_info['comment_id'], disclaimer_text):
                successful_redactions += 1

        print(f"\nRedaction complete: {successful_redactions}/{len(comments_with_disclaimers)} comments successfully redacted")

    except Exception as e:
        print(f"ERROR: Failed to process ticket {ticket_id}: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Redact email disclaimers from Zendesk ticket comments')
    parser.add_argument('--ticket', '-t', required=True, type=int, help='Ticket ID to process')
    parser.add_argument('--disclaimer', '-d', default=DEFAULT_DISCLAIMER,
                       help='Disclaimer text to redact (default: standard confidentiality disclaimer)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be redacted without making changes')
    parser.add_argument('--api-token', help='Zendesk API token (can also be set via ZENDESK_API_TOKEN env var)')

    args = parser.parse_args()

    print("=" * 60)
    print("Zendesk Email Footer Redaction Tool")
    print("=" * 60)
    print(f"Ticket ID: {args.ticket}")
    print(f"Disclaimer length: {len(args.disclaimer)} characters")
    print(f"Dry run: {'Yes' if args.dry_run else 'No'}")
    print(f"API Token: {'Provided via argument' if args.api_token else 'From environment or Secret Manager'}")
    print()

    # Initialize global rate limiter
    global rate_limiter
    rate_limiter = RateLimiter()

    process_ticket(args.ticket, args.disclaimer, args.dry_run, args.api_token)

if __name__ == '__main__':
    main()
