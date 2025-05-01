import requests
import json
import os
import time
import csv
import pickle
import re
import shutil
import unicodedata
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# Define ZENDESK URL, START_TIME, and other necessary variables
START_TIME = "1366783200"  # Use the very beginning as default
# Path for local ticket backups
TICKETS_BASE_PATH = r"L:\\Shared drives\\Business\\Zendesk\\Support"
# Alternative paths to check if the default is not accessible
ALTERNATIVE_DRIVE_LETTERS = ["G:", "H:", "I:", "J:", "K:", "M:", "N:", "O:", "P:", "Q:", "R:", "S:", "T:", "U:", "V:", "W:", "X:", "Y:", "Z:"]

def check_drive_path():
    """Check if the Google Drive path is accessible and try alternative drive letters if not."""
    global TICKETS_BASE_PATH
    
    # First try the default path
    if os.path.exists(TICKETS_BASE_PATH):
        return True
        
    # If default path doesn't exist, try alternative drive letters
    base_path_parts = TICKETS_BASE_PATH.split("\\")[1:]  # Remove the drive letter part
    for drive in ALTERNATIVE_DRIVE_LETTERS:
        alternative_path = drive + "\\" + "\\".join(base_path_parts)
        if os.path.exists(alternative_path):
            TICKETS_BASE_PATH = alternative_path
            print(f"Found Google Drive at alternative path: {alternative_path}")
            return True
            
    error_msg = """
ERROR: Cannot access Google Drive path. Please ensure:
1. Google Drive is running and properly syncing
2. You have access to the shared drive
3. The correct drive letter is being used (currently trying: L:)

Alternative drive letters checked: {', '.join(ALTERNATIVE_DRIVE_LETTERS)}
"""
    print(error_msg)
    return False

# Try to load the last run time from a file
LAST_RUN_FILE = "last_run.txt"
if os.path.exists(LAST_RUN_FILE):
    with open(LAST_RUN_FILE, "r") as f:
        last_run_time = f.read().strip()
        if last_run_time.isdigit():
            START_TIME = last_run_time
            print(f"Starting from last run time: {START_TIME}")
else:
    print(f"ERROR: No last run file found. Refusing to start from the beginning (epoch). Please check why last_run.txt is missing or not being updated. Exiting for safety.")
    import sys
    sys.exit(1)

zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")

# Set up the requests session for Zendesk API
session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)
log = []

def slugify(value, allow_unicode=False):
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')

def create_directory(path):
    os.makedirs(path, exist_ok=True)

def get_ticket_events(ticket_id):
    events_endpoint = f"https://{zendesk_subdomain}/api/v2/tickets/{ticket_id}/audits.json"
    events = []
    while events_endpoint:
        response = session.get(events_endpoint)
        if response.status_code == 429:
            print("Rate limited! Please wait.")
            time.sleep(int(response.headers["retry-after"]))
            continue
        if response.status_code != 200:
            print(f"Failed to retrieve events for ticket {ticket_id} with error {response.status_code}")
            return events
        data = response.json()
        events.extend(data["audits"])
        events_endpoint = data.get("next_page")
    return events

def download_ticket_local(single_ticket, backup_path):
    ticket_id = single_ticket["id"]
    subject = single_ticket["subject"]
    status = single_ticket["status"]
    updated_at = single_ticket["updated_at"]
    filename = f"{ticket_id}.json"
    file_path = os.path.join(backup_path, filename)

    # Only skip if the file exists and updated_at is the same
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if existing.get("updated_at", "") == updated_at:
                    print(f"{filename} is up to date, skipping.")
                    return (filename, subject, single_ticket["created_at"], updated_at, "skipped")
        except Exception as e:
            print(f"Error reading {filename}: {e}")

    # Fetch events and comments
    events = get_ticket_events(ticket_id)
    single_ticket["events"] = events

    # Write to file
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(single_ticket, f, indent=2)
        print(f"{filename} - saved locally with {len(events)} events!")
        return (filename, subject, single_ticket["created_at"], updated_at, "backed_up")
    except Exception as e:
        print(f"Failed to save {filename}: {e}")
        return (filename, subject, single_ticket["created_at"], updated_at, "error")

def save_log_local(log_data, log_filename, backup_path):
    log_path = os.path.join(backup_path, log_filename)
    with open(log_path, "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(("Backup Date", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        writer.writerow(("File", "Subject", "Date Created", "Date Updated", "Status"))
        for ticket in log_data:
            writer.writerow(ticket)
    print(f"Log file saved: {log_path}")

def backup_tickets_local(request=None):
    global log, START_TIME
    
    # Check if Google Drive is accessible before proceeding
    if not check_drive_path():
        return {
            "success": False,
            "error": "Google Drive path is not accessible. Please check if Google Drive is running and properly synced."
        }
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    backup_path = os.path.join(TICKETS_BASE_PATH, "tickets")
    create_directory(backup_path)
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
        if not data["tickets"]:
            print("No tickets found in this batch.")
            last_processed_time = data["end_time"]
            break
        with ThreadPoolExecutor() as executor:
            results = list(executor.map(lambda t: download_ticket_local(t, backup_path), data["tickets"]))
            log += results
            total_backed_up += sum(1 for r in results if r[4] == "backed_up")
            total_skipped += sum(1 for r in results if r[4] == "skipped")
            total_errors += sum(1 for r in results if r[4] == "error")
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
    with open(LAST_RUN_FILE, "w") as f:
        f.write(str(last_processed_time))
    print(f"Last processed time saved: {last_processed_time}")
    log_filename = f"_log_{current_date}.csv"
    save_log_local(log, log_filename, backup_path)
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

if __name__ == "__main__":
    backup_tickets_local() 