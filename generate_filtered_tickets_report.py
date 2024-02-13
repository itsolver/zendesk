import csv
from datetime import datetime
from config import zendesk_subdomain, zendesk_user, destination_folder, start_time

# Filtering criteria
organization_name_filter = "EIA Services Pty Ltd"
start_date_filter = "2023-01-01"
end_date_filter = "2023-08-18"
tag_filter = "managed_support"

# Define the CSV file path
report_csv_path = destination_folder + "/support/" + organization_name_filter + "_tickets_report_" + start_date_filter + "_" + end_date_filter + ".csv"

# Header for the CSV file
header = ['Ticket ID', 'Status', 'Assignee', 'Created Date', 'Solved Date', 'Subject', 'Type', 'Requester Name', 'Priority', 'Tags']

# Create the CSV file and write the header
with open(report_csv_path, mode='w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(header)

# Add the following code to the ticket retrieval section where tickets are processed

# ...



# Define a function to check if a ticket meets the criteria
def ticket_meets_criteria(ticket):
    # Assuming these fields are available in the ticket object
    organization_name = ticket['organization_name']
    created_date = ticket['created_at']
    tags = ticket['tags']

    # Check if the ticket organization name matches
    if organization_name != organization_name_filter:
        return False

    # Check if the ticket creation date falls within the specified range
    created_date_obj = datetime.strptime(created_date, "%Y-%m-%d")
    start_date_obj = datetime.strptime(start_date_filter, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date_filter, "%Y-%m-%d")
    if created_date_obj < start_date_obj or created_date_obj > end_date_obj:
        return False

    # Check if the ticket contains the specified tag
    if tag_filter not in tags:
        return False

    return True

# In the ticket retrieval loop, apply the filtering function
tickets_endpoint = zendesk_subdomain + '/api/v2/incremental/tickets.json?start_time=' + start_time
filtered_tickets = [] # To store the filtered tickets

while tickets_endpoint:
    response = session.get(tickets_endpoint)
    # ... (error handling code) ...

    data = response.json()
    for ticket in data['tickets']:
        if ticket_meets_criteria(ticket):
            filtered_tickets.append(ticket)
        # ... (existing processing code) ...

    tickets_endpoint = data['next_page']

for ticket in data['tickets']:
    # Filtering by organization name (adjust as needed)
    organization_name = ticket['organization']['name']
    if organization_name != organization_name_filter:
        continue

    # Filtering by dates
    created_date = ticket['created_at']
    if created_date < start_date_filter or created_date > end_date_filter: 
        continue

    # Extracting required information
    ticket_id = ticket['id']
    status = ticket['status']
    assignee = ticket['assignee']['name']
    solved_date = ticket['solved_at']
    subject = ticket['subject']
    ticket_type = ticket['type']
    requester_name = ticket['requester']['name']
    priority = ticket['priority']
    tags = ", ".join(ticket['tags'])

    # Write to the CSV file
    with open(report_csv_path, mode='a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([ticket_id, status, assignee, created_date, solved_date, subject, ticket_type, requester_name, priority, tags])

print('Filtered ticket report generated!')
