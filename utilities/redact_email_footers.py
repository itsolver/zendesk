#!/usr/bin/env python3
"""
Zendesk Chat Redaction Tool

This script redacts annoying email disclaimers from Zendesk chat tickets.
It uses the Zendesk Chat Redaction API to identify and redact disclaimer text
that appears in chat messages, making them more mobile-friendly.

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
    - Zendesk API access with chat redaction permissions
    - Agent Workspace enabled for the account
    - Deleting tickets enabled for agents
    - requests library
    - Optional: Google Cloud Secret Manager access for automatic token retrieval

Features:
    - Rate limiting to respect Zendesk API limits (350 req/min)
    - Dry run mode to preview changes
    - Uses Zendesk's native <redact> tags for chat messages
    - Works with chat tickets (not regular ticket comments)
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

def get_ticket_audits(session, ticket_id):
    """Fetch all audits for a ticket to find chat events."""
    base_url = f"https://{zendesk_subdomain}/api/v2"
    url = f"{base_url}/tickets/{ticket_id}/audits.json"

    print(f"Fetching audits for ticket {ticket_id}...")

    audits = []
    while url:
        response = make_api_request(session, 'GET', url)
        data = response.json()

        audits.extend(data.get('audits', []))
        url = data.get('next_page')

    print(f"Found {len(audits)} audits in ticket {ticket_id}")

    # Debug: Show structure of first audit
    if audits:
        first_audit = audits[0]
        print(f"Debug - First audit structure:")
        print(f"  ID: {first_audit.get('id')}")
        print(f"  Events count: {len(first_audit.get('events', []))}")
        if first_audit.get('events'):
            first_event = first_audit['events'][0]
            print(f"  First event type: {first_event.get('type')}")

    return audits

def extract_chat_messages_from_audits(audits):
    """Extract chat messages from ticket audits."""
    chat_messages = []
    chat_started_events = {}

    for audit in audits:
        for event in audit.get('events', []):
            event_type = event.get('type')

            # Look for ChatStartedEvent to get chat_id
            if event_type == 'ChatStartedEvent':
                chat_id = event.get('chat_id')
                if chat_id:
                    chat_started_events[audit['id']] = {
                        'chat_id': chat_id,
                        'audit_id': audit['id']
                    }

            # Look for ChatMessage events
            elif event_type == 'ChatMessage':
                message = event.get('message', '')
                if message:
                    chat_messages.append({
                        'message': message,
                        'chat_index': event.get('chat_index'),
                        'message_id': event.get('message_id'),
                        'audit_id': audit['id'],
                        'event': event
                    })

    # Associate chat messages with their chat_id
    for message in chat_messages:
        chat_info = chat_started_events.get(message['audit_id'])
        if chat_info:
            message['chat_id'] = chat_info['chat_id']

    return chat_messages

def find_disclaimer_in_chat_message(message_data, disclaimer_text):
    """Find disclaimer text in a chat message."""
    message = message_data.get('message', '')

    # Escape special regex characters in disclaimer
    escaped_disclaimer = re.escape(disclaimer_text.strip())

    # Look for disclaimer in the message
    match = re.search(escaped_disclaimer, message, re.IGNORECASE | re.DOTALL)

    if match:
        return {
            'message': message,
            'chat_id': message_data.get('chat_id'),
            'chat_index': message_data.get('chat_index'),
            'message_id': message_data.get('message_id'),
            'audit_id': message_data.get('audit_id'),
            'has_disclaimer': True,
            'message_data': message_data
        }

    return None

def redact_chat_message(session, ticket_id, message_data, disclaimer_text):
    """Redact disclaimer text from a chat message using Zendesk Chat Redaction API."""
    base_url = f"https://{zendesk_subdomain}/api/v2"

    chat_id = message_data.get('chat_id')
    chat_index = message_data.get('chat_index')
    message_id = message_data.get('message_id')
    message = message_data.get('message', '')

    print(f"Attempting to redact chat message (chat_id: {chat_id}, index: {chat_index})...")

    if not chat_id:
        print("✗ No chat_id found for this message")
        return False

    # Escape special regex characters
    escaped_disclaimer = re.escape(disclaimer_text.strip())

    # Replace disclaimer with redaction tags
    redacted_text = re.sub(
        escaped_disclaimer,
        '<redact>REDACTED EMAIL DISCLAIMER</redact>',
        message,
        flags=re.IGNORECASE | re.DOTALL
    )

    if redacted_text == message:
        print("No disclaimer found in chat message")
        return False

    # Prepare chat redaction request
    redaction_url = f"{base_url}/chat_redactions/{ticket_id}.json"

    # Use message_id if available, otherwise use chat_index
    if message_id:
        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': redacted_text
        }
    elif chat_index is not None:
        payload = {
            'chat_id': chat_id,
            'chat_index': chat_index,
            'text': redacted_text
        }
    else:
        print("✗ Neither message_id nor chat_index available")
        return False

    try:
        print(f"  Sending chat redaction request...")
        response = make_api_request(session, 'PUT', redaction_url, json=payload)

        if response.status_code in [200, 201, 204]:
            print("✓ Successfully redacted disclaimer from chat message"            return True
        else:
            print(f"✗ Chat redaction failed: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"✗ Chat redaction error: {e}")
        print("  This could be due to:")
        print("  - Insufficient permissions for chat redaction")
        print("  - Agent Workspace not enabled")
        print("  - Ticket deletion not enabled for agents")
        print("  - Chat is active (redaction doesn't work on active chats)")
        return False

def process_ticket(ticket_id, disclaimer_text, dry_run=False, api_token=None):
    """Process a ticket to redact disclaimers in chat messages."""
    session = setup_zendesk_session(api_token)

    try:
        # Get all audits for the ticket to find chat messages
        audits = get_ticket_audits(session, ticket_id)

        if not audits:
            print(f"No audits found for ticket {ticket_id}")
            return

        # Extract chat messages from audits
        chat_messages = extract_chat_messages_from_audits(audits)

        if not chat_messages:
            print(f"No chat messages found in ticket {ticket_id}")
            print("This ticket may not contain chat conversations or may be a regular ticket.")
            return

        # Find chat messages with disclaimers
        messages_with_disclaimers = []
        for message_data in chat_messages:
            result = find_disclaimer_in_chat_message(message_data, disclaimer_text)
            if result:
                messages_with_disclaimers.append(result)

        if not messages_with_disclaimers:
            print(f"No disclaimers found in chat messages for ticket {ticket_id}")
            return

        print(f"\nFound {len(messages_with_disclaimers)} chat messages with disclaimers:")
        for message_info in messages_with_disclaimers:
            print(f"  - Chat {message_info['chat_id']}, Message {message_info['chat_index'] or message_info['message_id']}")
            # Show first 100 chars of the message to verify
            message_preview = message_info['message'][:100]
            print(f"    Preview: {message_preview}...")
            print(f"    Has chat_id: {'Yes' if message_info['chat_id'] else 'No'}")

        if dry_run:
            print(f"\nDRY RUN: Would redact disclaimers from {len(messages_with_disclaimers)} chat messages")
            return

        # Redact disclaimers from chat messages
        print(f"\nRedacting disclaimers from {len(messages_with_disclaimers)} chat messages...")
        successful_redactions = 0

        for message_info in messages_with_disclaimers:
            if redact_chat_message(session, ticket_id, message_info, disclaimer_text):
                successful_redactions += 1

        print(f"\nRedaction complete: {successful_redactions}/{len(messages_with_disclaimers)} chat messages successfully redacted")

        if successful_redactions == 0:
            print("\nTroubleshooting suggestions:")
            print("1. Verify your Zendesk user has chat redaction permissions")
            print("2. Check if Agent Workspace is enabled for your account")
            print("3. Verify that ticket deletion is enabled for agents")
            print("4. Chat redaction doesn't work on active chats")
            print("5. The ticket may not be a chat ticket")

    except Exception as e:
        print(f"ERROR: Failed to process ticket {ticket_id}: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Redact email disclaimers from Zendesk chat tickets')
    parser.add_argument('--ticket', '-t', required=True, type=int, help='Ticket ID to process')
    parser.add_argument('--disclaimer', '-d', default=DEFAULT_DISCLAIMER,
                       help='Disclaimer text to redact (default: standard confidentiality disclaimer)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be redacted without making changes')
    parser.add_argument('--api-token', help='Zendesk API token (can also be set via ZENDESK_API_TOKEN env var)')

    args = parser.parse_args()

    print("=" * 60)
    print("Zendesk Chat Redaction Tool")
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
