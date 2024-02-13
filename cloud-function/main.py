import requests
import json
import time
import os
from google.cloud import pubsub_v1

# Initialize Pub/Sub publisher and secrets
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path('billing-sync', 'zendesk-tickets-closed')
zendesk_subdomain = 'itsolver.zendesk.com'  # Replace with your actual subdomain
zendesk_user = 'angus@itsolver.net'  # Replace with your actual user
zendesk_secret = os.environ.get('ZENDESK_API_TOKEN')

session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)

def get_ticket_comments(ticket_id):
    comments = []
    comments_url = f"https://{zendesk_subdomain}.zendesk.com/api/v2/tickets/{ticket_id}/audits.json"
    
    while comments_url:
        comments_response = session.get(comments_url)
        
        if comments_response.status_code == 429:
            time.sleep(int(comments_response.headers['retry-after']))
            continue

        comments_data = comments_response.json()
        for audit in comments_data['audits']:
            for event in audit['events']:
                if event['type'] == 'Comment':
                    comments.append(event['body'])
                    
        comments_url = comments_data.get('next_page', None)

    return comments

def backup_ticket_to_pubsub(request):
    request_json = request.get_json()
    if request_json and 'ticket_id' in request_json:
        ticket_id = request_json['ticket_id']
        
        ticket_url = f"https://{zendesk_subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json"
        ticket_response = session.get(ticket_url)
        
        if ticket_response.status_code != 200:
            return f"Failed to get ticket with error {ticket_response.status_code}", 500

        ticket_data = ticket_response.json()['ticket']
        
        if ticket_data['status'] != 'closed':
            return 'Ticket is not closed. Ignoring.', 200
        
        ticket_data['comments'] = get_ticket_comments(ticket_id)
        content = json.dumps(ticket_data, indent=2)
        
        future = publisher.publish(topic_path, content.encode('utf-8'))
        future.result()

        return 'Ticket backed up and published to Pub/Sub.', 200
    else:
        return 'Invalid request', 400
