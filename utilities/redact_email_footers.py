#!/usr/bin/env python3
"""
Zendesk Email Footer Redaction Tool

This script redacts annoying email disclaimers from Zendesk ticket comments.
It uses the Zendesk Comment Redaction API to identify and redact disclaimer text
that appears in email footers, making ticket comments more mobile-friendly.

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
    - Zendesk API access with comment redaction permissions
    - Agent Workspace enabled for the account
    - Deleting tickets enabled for agents
    - requests library
    - Optional: Google Cloud Secret Manager access for automatic token retrieval

Features:
    - Rate limiting to respect Zendesk API limits (350 req/min)
    - Dry run mode to preview changes
    - Uses Zendesk's native <redact> tags for HTML content
    - Works with closed and archived tickets
    - Supports formatted text (bold, italics, hyperlinks)
"""

import requests
import re
import time
import argparse
import sys
import os
import threading
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version, test_gcloud_access

# Default disclaimer text to redact
DEFAULT_DISCLAIMER = """This message contains information which may be confidential and privileged. Unless you are the intended recipient (or authorized to receive this message for the intended recipient), you may not use, copy, disseminate or disclose to anyone the message or any information contained in the message. If you have received the message in error, please advise the sender by reply e-mail, and delete the message. Thank you very much."""

# Rate Limiting Configuration
MAX_REQUESTS_PER_MINUTE = 350
REQUEST_INTERVAL = 60.0 / MAX_REQUESTS_PER_MINUTE

# Initialize global rate limiter
rate_limiter = None

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

def redact_comment(session, ticket_id, comment_id, html_body, disclaimer_text):
    """Redact disclaimer text from a comment using Zendesk Comment Redaction API."""
    base_url = f"https://{zendesk_subdomain}/api/v2"

    print(f"Attempting to redact comment {comment_id}...")

    if not html_body:
        print(f"Warning: No HTML body found for comment {comment_id}")
        return False

    # Clean and prepare the disclaimer text for matching
    cleaned_disclaimer = disclaimer_text.strip()

    # Try multiple matching strategies to handle HTML formatting differences
    redacted_html = None

    # Strategy 1: Exact match with HTML entities handled
    if redacted_html is None:
        escaped_disclaimer = re.escape(cleaned_disclaimer)
        redacted_html = re.sub(
            escaped_disclaimer,
            '<redact>REDACTED EMAIL DISCLAIMER</redact>',
            html_body,
            flags=re.IGNORECASE | re.DOTALL
        )
        if redacted_html != html_body:
            print("Found disclaimer using exact match")

    # Strategy 2: Match with normalized whitespace
    if redacted_html is None or redacted_html == html_body:
        # Normalize whitespace in both HTML and disclaimer
        normalized_html = re.sub(r'\s+', ' ', html_body)
        normalized_disclaimer = re.sub(r'\s+', ' ', cleaned_disclaimer)

        # Look for the disclaimer in the normalized HTML
        escaped_normalized = re.escape(normalized_disclaimer)
        if re.search(escaped_normalized, normalized_html, re.IGNORECASE):
            # Replace in the original HTML by finding the best match
            # Use a more flexible pattern that accounts for whitespace variations
            flexible_pattern = re.sub(r'\s+', r'\s+', re.escape(cleaned_disclaimer))
            redacted_html = re.sub(
                flexible_pattern,
                '<redact>REDACTED EMAIL DISCLAIMER</redact>',
                html_body,
                flags=re.IGNORECASE | re.DOTALL,
                count=1
            )
            print("Found disclaimer using normalized match")

    # Strategy 3: Look for the disclaimer wrapped in <i> tags (common in email signatures)
    if redacted_html is None or redacted_html == html_body:
        # Pattern to match italicized disclaimer
        italic_pattern = r'<i[^>]*>.*?' + re.escape(cleaned_disclaimer) + r'.*?</i>'
        if re.search(italic_pattern, html_body, re.IGNORECASE | re.DOTALL):
            redacted_html = re.sub(
                italic_pattern,
                '<redact>REDACTED EMAIL DISCLAIMER</redact>',
                html_body,
                flags=re.IGNORECASE | re.DOTALL
            )
            print("Found disclaimer in italic tags")

    # Strategy 4: Multi-line disclaimer with HTML line breaks
    if redacted_html is None or redacted_html == html_body:
        # Handle disclaimers that span multiple lines with <br> tags
        lines = cleaned_disclaimer.split('\n')
        if len(lines) > 1:
            # Create a pattern that matches across multiple lines with HTML breaks
            line_patterns = []
            for line in lines:
                line_patterns.append(re.escape(line.strip()))

            # Join with flexible spacing (including <br>, &nbsp;, etc.)
            flexible_pattern = r'\s*(?:<br[^>]*>|<br/?>|\s|&nbsp;)\s*'.join(line_patterns)

            if re.search(flexible_pattern, html_body, re.IGNORECASE | re.DOTALL):
                redacted_html = re.sub(
                    flexible_pattern,
                    '<redact>REDACTED EMAIL DISCLAIMER</redact>',
                    html_body,
                    flags=re.IGNORECASE | re.DOTALL
                )
                print("Found disclaimer using multi-line pattern")

    # Strategy 5: Word-by-word matching for heavily formatted text
    if redacted_html is None or redacted_html == html_body:
        words = cleaned_disclaimer.split()
        if len(words) > 5:  # Only for longer disclaimers
            # Match first few words and last few words with wildcard in between
            first_words = ' '.join(words[:3])
            last_words = ' '.join(words[-3:])

            word_pattern = re.escape(first_words) + r'.*?' + re.escape(last_words)
            if re.search(word_pattern, html_body, re.IGNORECASE | re.DOTALL):
                redacted_html = re.sub(
                    word_pattern,
                    '<redact>REDACTED EMAIL DISCLAIMER</redact>',
                    html_body,
                    flags=re.IGNORECASE | re.DOTALL
                )
                print("Found disclaimer using word-by-word match")

    # If no match found, return early
    if redacted_html is None or redacted_html == html_body:
        print(f"No disclaimer found in comment {comment_id}")
        return False

    # Ensure the redaction is properly formatted
    # Replace any nested redaction tags
    redacted_html = re.sub(r'<redact[^>]*>.*?<redact[^>]*>.*?</redact>.*?</redact>', '<redact>REDACTED EMAIL DISCLAIMER</redact>', redacted_html)

    # Prepare redaction request using the recommended endpoint
    redaction_url = f"{base_url}/comment_redactions/{comment_id}.json"
    payload = {
        'ticket_id': ticket_id,
        'html_body': redacted_html
    }

    try:
        response = make_api_request(session, 'PUT', redaction_url, json=payload)

        if response.status_code in [200, 201, 204]:
            print(f"✓ Successfully redacted disclaimer in comment {comment_id}")
            return True
        else:
            print(f"✗ Redaction failed: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"✗ Redaction error: {e}")
        return False

def process_ticket(ticket_id, disclaimer_text, dry_run=False, api_token=None):
    """Process a ticket to redact disclaimers in comments."""
    session = setup_zendesk_session(api_token)

    try:
        # Get all comments for the ticket
        comments = get_ticket_comments(session, ticket_id)

        if not comments:
            print(f"No comments found for ticket {ticket_id}")
            return

        # Find comments with disclaimers
        comments_with_disclaimers = []
        escaped_disclaimer = re.escape(disclaimer_text.strip())

        for comment in comments:
            html_body = comment.get('html_body', '')

            # Try exact match first
            if re.search(escaped_disclaimer, html_body, re.IGNORECASE | re.DOTALL):
                comments_with_disclaimers.append(comment)
            else:
                # Try more flexible matching for HTML content
                # Remove extra whitespace and normalize
                normalized_html = re.sub(r'\s+', ' ', html_body)
                normalized_disclaimer = re.sub(r'\s+', ' ', disclaimer_text.strip())

                if re.search(re.escape(normalized_disclaimer), normalized_html, re.IGNORECASE):
                    comments_with_disclaimers.append(comment)

        if not comments_with_disclaimers:
            print(f"No disclaimers found in ticket {ticket_id}")
            return

        print(f"\nFound {len(comments_with_disclaimers)} comments with disclaimers:")
        for comment in comments_with_disclaimers:
            print(f"  - Comment {comment['id']} by {comment.get('author', {}).get('name', 'Unknown')}")

        if dry_run:
            print(f"\nDRY RUN: Would redact disclaimers from {len(comments_with_disclaimers)} comments")
            return

        # Redact disclaimers
        print(f"\nRedacting disclaimers from {len(comments_with_disclaimers)} comments...")
        successful_redactions = 0

        for comment in comments_with_disclaimers:
            if redact_comment(session, ticket_id, comment['id'], comment.get('html_body', ''), disclaimer_text):
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

    # Initialize rate limiter if not already done
    global rate_limiter
    if rate_limiter is None:
        rate_limiter = RateLimiter()

    process_ticket(args.ticket, args.disclaimer, args.dry_run, args.api_token)

if __name__ == '__main__':
    main()
