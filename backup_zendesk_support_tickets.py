import requests
import json
import os
import time
import csv
import pickle
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

try:
    from firebase_admin import firestore

    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
import io


# Define ZENDESK URL, START_TIME, and other necessary variables
# to get epoch time on mac terminal use e.g. ``date -j -f "%d-%B-%y" 19-FEB-12 +%s``
# First ticket date in IT Solver Zendesk is 2013-04-24 16:00:00 (Epoch time: 1366783200)
# Default START_TIME - will be overridden if last_run.txt exists
START_TIME = "1366783200"  # Use the very beginning as default
# Google Drive folder ID where tickets will be saved
DRIVE_FOLDER_ID = os.environ.get(
    "DRIVE_FOLDER_ID", "1ojRI36toh_LcDiHSFSH5tdYfTsmifp-2"
)  # Default to provided ID
# Google Drive API scope
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
# Path to client secrets file - can be set via environment variable
CLIENT_SECRETS_FILE = os.environ.get("CLIENT_SECRETS_FILE", "client_secrets.json")
# Token pickle file for OAuth storage
TOKEN_PICKLE_FILE = os.environ.get("TOKEN_PICKLE_FILE", "token.pickle")
# Optional: Use Firestore for token storage (for Cloud Run)
USE_FIRESTORE_STORAGE = (
    os.environ.get("USE_FIRESTORE_STORAGE", "False").lower() == "true"
)

# Try to load the last run time from a file
LAST_RUN_FILE = "last_run.txt"
if os.path.exists(LAST_RUN_FILE):
    with open(LAST_RUN_FILE, "r") as f:
        last_run_time = f.read().strip()
        # Only update START_TIME if we have a valid timestamp
        if last_run_time.isdigit():
            START_TIME = last_run_time
            print(f"Starting from last run time: {START_TIME}")
else:
    print(f"No last run file found. Starting from: {START_TIME}")

zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")

# Set up the requests session for Zendesk API
session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)
log = []


class FirestoreStorage:
    """Simple class to store and retrieve data from Firestore."""

    def __init__(self, doc_ref, content_field, created_field, modified_field):
        self.doc_ref = doc_ref
        self.content_field = content_field
        self.created_field = created_field
        self.modified_field = modified_field

    def get(self):
        doc = self.doc_ref.get()
        if not doc.exists:
            print("Firestore object does not exist")
            return None
        return doc.get(self.content_field)

    def update(self, content):
        data = {self.modified_field: datetime.now(), self.content_field: content}
        self.doc_ref.update(data)

    def create(self, content):
        data = {self.created_field: datetime.now(), self.content_field: content}
        self.doc_ref.set(data)


def get_drive_service():
    """Initialize and return a Google Drive API service using OAuth."""
    creds = None

    # Option 1: Try Firestore storage if configured
    if USE_FIRESTORE_STORAGE and FIREBASE_AVAILABLE:
        try:
            db = firestore.client()
            doc_ref = db.collection("pickle").document("zendesk_drive")

            storage = FirestoreStorage(
                doc_ref=doc_ref,
                content_field="pickle",
                created_field="created",
                modified_field="modified",
            )

            pickle_data = storage.get()
            if pickle_data:
                creds = pickle.loads(pickle_data)
                print("Loaded credentials from Firestore")
        except Exception as e:
            print(f"Error accessing Firestore: {e}")

    # Option 2: Try local file storage
    if not creds and os.path.exists(TOKEN_PICKLE_FILE):
        try:
            with open(TOKEN_PICKLE_FILE, "rb") as token:
                creds = pickle.load(token)
                print("Loaded credentials from local file")
        except Exception as e:
            print(f"Error loading token from file: {e}")

    # If credentials need refresh or don't exist
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                print("Refreshed expired credentials")
            except Exception as e:
                print(f"Error refreshing credentials: {e}")
                creds = None

    # If we still don't have valid credentials, we need OAuth flow
    if not creds or not creds.valid:
        try:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                raise FileNotFoundError(
                    f"Client secrets file not found: {CLIENT_SECRETS_FILE}"
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, DRIVE_SCOPES
            )

            # For Cloud Run or server environments, you might need a different flow approach
            # This will open a browser window for authentication
            print("Starting OAuth flow - a browser window will open for authentication")
            creds = flow.run_local_server(port=0)
            print("Authentication successful")

            # Save the credentials for future use
            if USE_FIRESTORE_STORAGE and FIREBASE_AVAILABLE:
                try:
                    storage.create(pickle.dumps(creds))
                    print("Saved credentials to Firestore")
                except Exception as e:
                    print(f"Failed to save credentials to Firestore: {e}")

            try:
                with open(TOKEN_PICKLE_FILE, "wb") as token:
                    pickle.dump(creds, token)
                print(f"Saved credentials to {TOKEN_PICKLE_FILE}")
            except Exception as e:
                print(f"Failed to save credentials to file: {e}")

        except Exception as e:
            print(f"OAuth flow failed: {e}")
            # Fall back to application default credentials as last resort
            print("Falling back to application default credentials")
            from google.auth import default

            credentials, _ = default(scopes=DRIVE_SCOPES)
            return build("drive", "v3", credentials=credentials)

    return build("drive", "v3", credentials=creds)


def get_ticket_events(ticket_id):
    """Get all events for a specific ticket."""
    events_endpoint = (
        f"https://{zendesk_subdomain}/api/v2/tickets/{ticket_id}/audits.json"
    )
    events = []
    while events_endpoint:
        response = session.get(events_endpoint)
        if response.status_code == 429:
            print("Rate limited! Please wait.")
            time.sleep(int(response.headers["retry-after"]))
            continue
        if response.status_code != 200:
            print(
                f"Failed to retrieve events for ticket {ticket_id} with error {response.status_code}"
            )
            return events
        data = response.json()
        events.extend(data["audits"])
        events_endpoint = data.get("next_page")
    return events


def check_file_exists(drive_service, filename):
    """Check if a file with the given name exists in the target folder."""
    query = (
        f"name = '{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    )
    results = (
        drive_service.files()
        .list(
            q=query,
            fields="files(id, name, properties, modifiedTime)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = results.get("files", [])
    return files[0] if files else None


def download_ticket(single_ticket):
    """Download a ticket and save it to Google Drive."""
    ticket_id = single_ticket["id"]
    subject = single_ticket["subject"]
    status = single_ticket["status"]
    updated_at = single_ticket["updated_at"]
    filename = f"{ticket_id}.json"

    # Get Drive service
    drive_service = get_drive_service()

    # Check if the file already exists
    existing_file = check_file_exists(drive_service, filename)

    if existing_file:
        # Check properties to see if it needs updating
        file_properties = existing_file.get("properties", {})
        file_updated_at = file_properties.get("zendesk_updated_at", "")
        file_status = file_properties.get("zendesk_status", "")

        # If the ticket is closed and we have the same updated_at date, skip it
        if (
            status == "closed"
            and file_status == "closed"
            and file_updated_at == updated_at
        ):
            print(f"{filename} is closed and up to date, skipping.")
            return (
                filename,
                subject,
                single_ticket["created_at"],
                updated_at,
                "skipped",
            )

        # If the file has the same or newer updated_at timestamp, skip it
        if file_updated_at and file_updated_at >= updated_at:
            print(f"{filename} is up to date, skipping.")
            return (
                filename,
                subject,
                single_ticket["created_at"],
                updated_at,
                "skipped",
            )

    # Fetch events and comments
    events = get_ticket_events(ticket_id)
    single_ticket["events"] = events

    # Prepare content as bytes
    content = json.dumps(single_ticket, indent=2)
    content_bytes = content.encode("utf-8")

    # Create media upload
    media = MediaInMemoryUpload(content_bytes, mimetype="application/json")

    # Prepare properties to store with the file
    file_properties = {
        "zendesk_updated_at": updated_at,
        "zendesk_status": status,
        "zendesk_subject": subject,
    }

    # Retry mechanism for API operations
    max_retries = 3

    if existing_file:
        # Update existing file with retry
        for attempt in range(max_retries):
            try:
                drive_service.files().update(
                    fileId=existing_file["id"],
                    media_body=media,
                    body={"properties": file_properties},
                    supportsAllDrives=True,
                ).execute()

                # Verify the update was successful by checking the file again
                updated_file = (
                    drive_service.files()
                    .get(
                        fileId=existing_file["id"],
                        fields="properties",
                        supportsAllDrives=True,
                    )
                    .execute()
                )

                # Check if properties were updated correctly
                if (
                    updated_file.get("properties", {}).get("zendesk_updated_at")
                    == updated_at
                ):
                    print(f"{filename} - updated with {len(events)} events!")
                    return (
                        filename,
                        subject,
                        single_ticket["created_at"],
                        updated_at,
                        "backed_up",
                    )
                else:
                    print(
                        f"Warning: File {filename} was updated but properties verification failed. Retrying..."
                    )
                    if attempt == max_retries - 1:
                        print(
                            f"Error: Failed to verify update for {filename} after {max_retries} attempts."
                        )
            except Exception as e:
                if attempt < max_retries - 1:
                    print(
                        f"Error updating {filename}: {str(e)}. Retrying ({attempt + 1}/{max_retries})..."
                    )
                    time.sleep(2**attempt)  # Exponential backoff
                else:
                    print(
                        f"Failed to update {filename} after {max_retries} attempts: {str(e)}"
                    )
                    return (
                        filename,
                        subject,
                        single_ticket["created_at"],
                        updated_at,
                        "error",
                    )
    else:
        # First double-check that the file doesn't already exist (extra safeguard)
        double_check = check_file_exists(drive_service, filename)
        if double_check:
            print(
                f"Warning: Found {filename} in second check, updating instead of creating."
            )
            existing_file = double_check
            # Use the update code path instead
            for attempt in range(max_retries):
                try:
                    drive_service.files().update(
                        fileId=existing_file["id"],
                        media_body=media,
                        body={"properties": file_properties},
                        supportsAllDrives=True,
                    ).execute()
                    print(f"{filename} - updated with {len(events)} events!")
                    return (
                        filename,
                        subject,
                        single_ticket["created_at"],
                        updated_at,
                        "backed_up",
                    )
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(
                            f"Error updating {filename}: {str(e)}. Retrying ({attempt + 1}/{max_retries})..."
                        )
                        time.sleep(2**attempt)
                    else:
                        print(
                            f"Failed to update {filename} after {max_retries} attempts: {str(e)}"
                        )
                        return (
                            filename,
                            subject,
                            single_ticket["created_at"],
                            updated_at,
                            "error",
                        )

        # Create new file with retry
        for attempt in range(max_retries):
            try:
                # Create new file
                file_metadata = {
                    "name": filename,
                    "parents": [DRIVE_FOLDER_ID],
                    "mimeType": "application/json",
                    "properties": file_properties,
                }

                new_file = (
                    drive_service.files()
                    .create(
                        body=file_metadata,
                        media_body=media,
                        fields="id",
                        supportsAllDrives=True,
                    )
                    .execute()
                )

                # Verify the file was created by checking if it exists
                verification = check_file_exists(drive_service, filename)
                if verification and verification.get("id") == new_file.get("id"):
                    print(f"{filename} - created with {len(events)} events!")
                    return (
                        filename,
                        subject,
                        single_ticket["created_at"],
                        updated_at,
                        "backed_up",
                    )
                else:
                    print(
                        f"Warning: File {filename} was reportedly created but verification failed. Retrying..."
                    )
                    if attempt == max_retries - 1:
                        print(
                            f"Error: Failed to verify creation for {filename} after {max_retries} attempts."
                        )
            except Exception as e:
                if attempt < max_retries - 1:
                    print(
                        f"Error creating {filename}: {str(e)}. Retrying ({attempt + 1}/{max_retries})..."
                    )
                    time.sleep(2**attempt)
                else:
                    print(
                        f"Failed to create {filename} after {max_retries} attempts: {str(e)}"
                    )
                    return (
                        filename,
                        subject,
                        single_ticket["created_at"],
                        updated_at,
                        "error",
                    )

    # If we've reached here, something unexpected happened
    return (filename, subject, single_ticket["created_at"], updated_at, "error")


def save_log_to_drive(log_data, log_filename):
    """Save log file to Google Drive."""
    drive_service = get_drive_service()

    # Prepare CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(("Backup Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    writer.writerow(("File", "Subject", "Date Created", "Date Updated", "Status"))
    for ticket in log_data:
        writer.writerow(ticket)

    # Convert to bytes
    content_bytes = output.getvalue().encode("utf-8")

    # Create media upload
    media = MediaInMemoryUpload(content_bytes, mimetype="text/csv")

    # Check if log file already exists
    existing_log = check_file_exists(drive_service, log_filename)

    if existing_log:
        # Update existing file
        drive_service.files().update(
            fileId=existing_log["id"], media_body=media, supportsAllDrives=True
        ).execute()
    else:
        # Create new file
        file_metadata = {
            "name": log_filename,
            "parents": [DRIVE_FOLDER_ID],
            "mimeType": "text/csv",
        }
        drive_service.files().create(
            body=file_metadata, media_body=media, fields="id", supportsAllDrives=True
        ).execute()

    print(f"Log file updated: {log_filename}")


def backup_tickets(request=None):
    """Main function to backup tickets, suitable for Cloud Run."""
    global log, START_TIME

    tickets_endpoint = f"https://{zendesk_subdomain}/api/v2/incremental/tickets.json?start_time={START_TIME}"
    previous_end_time = None
    total_backed_up = 0
    total_skipped = 0
    total_errors = 0
    last_processed_time = START_TIME

    while tickets_endpoint:
        response = session.get(tickets_endpoint)
        if response.status_code == 429:
            print("Rate limited! Please wait.")
            time.sleep(int(response.headers["retry-after"]))
            continue
        if response.status_code != 200:
            print(f"Failed to retrieve tickets with error {response.status_code}")
            return {
                "success": False,
                "error": f"Failed with status {response.status_code}",
            }

        data = response.json()

        # Skip processing if no tickets in the batch
        if not data["tickets"]:
            print("No tickets found in this batch.")
            last_processed_time = data["end_time"]
            break

        with ThreadPoolExecutor() as executor:
            results = list(executor.map(download_ticket, data["tickets"]))
            log += results
            total_backed_up += sum(1 for r in results if r[4] == "backed_up")
            total_skipped += sum(1 for r in results if r[4] == "skipped")
            total_errors += sum(1 for r in results if r[4] == "error")

        # Update the start_time for the next API call
        end_time = data["end_time"]
        if end_time == previous_end_time:
            print("No new tickets found. Ending the process.")
            break

        previous_end_time = end_time
        last_processed_time = end_time

        tickets_endpoint = data.get("next_page")
        if not tickets_endpoint:
            print("Reached the end of tickets.")
            break

    # Save the last processed time to a file
    with open(LAST_RUN_FILE, "w") as f:
        f.write(str(last_processed_time))
    print(f"Last processed time saved: {last_processed_time}")

    # Save logs to Drive
    current_date = datetime.now().strftime("%Y-%m-%d")
    log_filename = f"_log_{current_date}.csv"
    save_log_to_drive(log, log_filename)

    summary = {
        "success": True,
        "total_backed_up": total_backed_up,
        "total_skipped": total_skipped,
        "total_errors": total_errors,
        "total_processed": total_backed_up + total_skipped + total_errors,
        "last_processed_time": last_processed_time,
    }

    print("\nBackup Summary:")
    print(f"Total tickets backed up: {total_backed_up}")
    print(f"Total tickets skipped: {total_skipped}")
    print(f"Total tickets with errors: {total_errors}")
    print(f"Total tickets processed: {total_backed_up + total_skipped + total_errors}")
    print(f"Last processed time: {last_processed_time}")

    return summary


# For local execution
if __name__ == "__main__":
    backup_tickets()
