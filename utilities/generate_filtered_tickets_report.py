import requests
import csv
from datetime import datetime
from config import zendesk_subdomain, zendesk_user, destination_folder, start_time
from secret_manager import access_secret_version

# Authentication Setup
zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")
session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)

# Define the CSV file path and header
organization_name_filter = "EIA Services Pty Ltd"
start_date_filter = "2023-01-01"
end_date_filter = "2023-08-18"
tag_filter = "managed_support"
report_csv_path = f"{destination_folder}/support/{organization_name_filter}_tickets_report_{start_date_filter}_{end_date_filter}.csv"
header = ['Ticket ID', 'Status', 'Assignee', 'Created Date', 'Solved Date', 'Subject', 'Type', 'Requester Name', 'Priority', 'Tags', 'Total Time Spent (Seconds)']

# Create and write header to the CSV file
with open(report_csv_path, mode='w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(header)

def ticket_meets_criteria(ticket, organization_name_filter, start_date_filter, end_date_filter, tag_filter):
    # Adjust the field access according to your ticket's JSON structure
    organization_name = ticket.get('organization_name', "")
    created_date = ticket.get('created_at', "")
    tags = ticket.get('tags', [])

    if organization_name != organization_name_filter:
        return False

    created_date_obj = datetime.strptime(created_date[:10], "%Y-%m-%d")  # [:10] to slice the date part of the datetime string
    start_date_obj = datetime.strptime(start_date_filter, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date_filter, "%Y-%m-%d")
    if not (start_date_obj <= created_date_obj <= end_date_obj):
        return False

    if tag_filter not in tags:
        return False

    return True

# Tickets retrieval and filtering
tickets_endpoint = f"https://{zendesk_subdomain}/api/v2/incremental/tickets.json?start_time={start_time}"
while tickets_endpoint:
    response = session.get(tickets_endpoint)
    if response.status_code != 200:
        print(f"Failed to retrieve tickets: {response.status_code}")
        break

    data = response.json()
    for ticket in data['tickets']:
        if ticket_meets_criteria(ticket, organization_name_filter, start_date_filter, end_date_filter, tag_filter):
            # Extract custom field value for total time spent
            total_time_spent = next((field['value'] for field in ticket['custom_fields'] if field['id'] == 5397925840655), None)

            # Update ticket_info dictionary to include total_time_spent
            ticket_info = {
                # Previous fields...
                'Total Time Spent (Seconds)': total_time_spent
            }

            # Update the CSV writing section to include total_time_spent
            with open(report_csv_path, mode='a', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(ticket_info.values())

    tickets_endpoint = data.get('next_page')

print("Filtered ticket report generated for EIA Services!")
