import requests
import time
import re
from datetime import datetime, timedelta
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version, test_gcloud_access
from zendesk_guide_article_template import get_template

class TicketKnowledgeBaseGenerator:
    """Generate knowledge base articles from Zendesk ticket search results using Grok API."""
    
    def __init__(self):
        """Initialize the generator with Zendesk and Grok API configurations."""
        self.zendesk_session = None
        self.grok_api_key = None
        self.grok_base_url = "https://api.x.ai/v1"
        self.rate_limiter = RateLimiter()
        
    def setup_apis(self):
        """Setup Zendesk and Grok API connections."""
        print("Setting up API connections...")
        
        # Test Google Cloud access for Zendesk API token
        if not test_gcloud_access():
            print("ERROR: Cannot access Google Cloud Secret Manager.")
            print("Please ensure:")
            print("1. GOOGLE_APPLICATION_CREDENTIALS environment variable is set")
            print("2. You have access to the 'billing-sync' project")
            print("3. You have Secret Manager permissions")
            return False
            
        # Get Zendesk API token
        try:
            zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")
        except (ValueError, RuntimeError) as e:
            print(f"Failed to get Zendesk API token: {e}")
            return False
            
        # Get Grok API key
        try:
            self.grok_api_key = access_secret_version("billing-sync", "GROK_API_KEY", "latest")
        except (ValueError, RuntimeError) as e:
            print(f"Failed to get Grok API key: {e}")
            return False
            
        # Setup Zendesk session
        self.zendesk_session = requests.Session()
        self.zendesk_session.auth = (zendesk_user, zendesk_secret)
        self.zendesk_session.headers.update({
            'Connection': 'keep-alive',
            'Accept-Encoding': 'gzip, deflate',
            'User-Agent': 'itsolver-ticket-to-kb-generator/1.0'
        })
        
        print("API connections established successfully!")
        return True
        
    def search_tickets(self, search_query, max_results=50):
        """Search Zendesk tickets for the given query."""
        print(f"Searching tickets for: '{search_query}'")
        
        # URL encode the search query
        encoded_query = requests.utils.quote(search_query)
        search_url = f"https://{zendesk_subdomain}/api/v2/search.json?query={encoded_query}&sort_by=updated_at&sort_order=desc"
        
        all_tickets = []
        page_count = 0
        
        while search_url and len(all_tickets) < max_results:
            page_count += 1
            print(f"Fetching search results page {page_count}...")
            
            try:
                response = self.zendesk_session.get(search_url)
                
                if response.status_code == 429:
                    retry_after = int(response.headers.get('retry-after', 60))
                    print(f"Rate limited. Waiting {retry_after} seconds...")
                    time.sleep(retry_after)
                    continue
                    
                if response.status_code != 200:
                    print(f"Search failed with status {response.status_code}: {response.text}")
                    break
                    
                data = response.json()
                results = data.get('results', [])
                
                if not results:
                    print("No more results found.")
                    break
                    
                print(f"Found {len(results)} results on page {page_count}")
                all_tickets.extend(results[:max_results - len(all_tickets)])
                
                search_url = data.get('next_page')
                time.sleep(0.2)  # Rate limiting
                
            except (requests.RequestException, ValueError) as e:
                print(f"Error searching tickets: {e}")
                break
                
        print(f"Total tickets found: {len(all_tickets)}")
        return all_tickets
        
    def get_ticket_audits(self, ticket_id):
        """Get audit data for a specific ticket."""
        audits_url = f"https://{zendesk_subdomain}/api/v2/tickets/{ticket_id}/audits.json"
        
        try:
            response = self.zendesk_session.get(audits_url)
            
            if response.status_code == 429:
                retry_after = int(response.headers.get('retry-after', 60))
                print(f"Rate limited. Waiting {retry_after} seconds...")
                time.sleep(retry_after)
                return self.get_ticket_audits(ticket_id)  # Retry
                
            if response.status_code != 200:
                print(f"Failed to get audits for ticket {ticket_id}: {response.status_code}")
                return []
                
            data = response.json()
            return data.get('audits', [])
            
        except requests.RequestException as e:
            print(f"Error getting audits for ticket {ticket_id}: {e}")
            return []
            
    def sanitize_ticket_data(self, tickets_with_audits):
        """Remove personal information from ticket data."""
        print("Sanitizing ticket data to remove personal information...")
        
        sanitized_data = []
        
        for ticket_data in tickets_with_audits:
            ticket = ticket_data['ticket']
            audits = ticket_data['audits']
            
            # Sanitize ticket data
            sanitized_ticket = {
                'id': ticket.get('id'),
                'subject': ticket.get('subject', '').replace(ticket.get('requester_email', ''), '[EMAIL]'),
                'description': ticket.get('description', ''),
                'status': ticket.get('status'),
                'priority': ticket.get('priority'),
                'type': ticket.get('type'),
                'tags': ticket.get('tags', []),
                'created_at': ticket.get('created_at'),
                'updated_at': ticket.get('updated_at')
            }
            
            # Remove email addresses and personal info from description
            sanitized_ticket['description'] = self.remove_personal_info(sanitized_ticket['description'])
            sanitized_ticket['subject'] = self.remove_personal_info(sanitized_ticket['subject'])
            
            # Sanitize audits
            sanitized_audits = []
            for audit in audits:
                sanitized_audit = {
                    'id': audit.get('id'),
                    'created_at': audit.get('created_at'),
                    'author_id': audit.get('author_id'),
                    'events': []
                }
                
                for event in audit.get('events', []):
                    sanitized_event = {
                        'type': event.get('type'),
                        'field_name': event.get('field_name'),
                        'value': event.get('value')
                    }
                    
                    # Remove personal info from event values
                    if isinstance(sanitized_event['value'], str):
                        sanitized_event['value'] = self.remove_personal_info(sanitized_event['value'])
                    
                    sanitized_audit['events'].append(sanitized_event)
                    
                sanitized_audits.append(sanitized_audit)
            
            sanitized_data.append({
                'ticket': sanitized_ticket,
                'audits': sanitized_audits
            })
            
        return sanitized_data
        
    def remove_personal_info(self, text):
        """Remove personal information from text."""
        if not isinstance(text, str):
            return text
            
        # Remove email addresses
        text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
        
        # Remove phone numbers
        text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)
        
        # Remove common personal info patterns
        text = re.sub(r'\b[A-Z][a-z]+ [A-Z][a-z]+\b', '[NAME]', text)  # Names
        
        # Remove IP addresses
        text = re.sub(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', '[IP_ADDRESS]', text)
        
        # Remove URLs that might contain personal info
        text = re.sub(r'https?://[^\s]+', '[URL]', text)
        
        return text
        
    def generate_kb_article_with_grok(self, sanitized_data, search_query):
        """Use Grok API to generate a knowledge base article from ticket data."""
        print("Generating knowledge base article using Grok API...")
        
        # Prepare the prompt for Grok
        prompt = self.create_grok_prompt(sanitized_data, search_query)
        
        headers = {
            'Authorization': f'Bearer {self.grok_api_key}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'model': 'grok-code-fast-1',
            'messages': [
                {
                    'role': 'system',
                    'content': 'You are an expert technical writer specializing in creating comprehensive knowledge base articles for IT support. You excel at analyzing ticket data and creating helpful, well-structured articles that solve common problems.'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            'max_tokens': 4000,
            'temperature': 0.7
        }
        
        try:
            response = requests.post(
                f"{self.grok_base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code != 200:
                print(f"Grok API error: {response.status_code} - {response.text}")
                return None
                
            result = response.json()
            return result['choices'][0]['message']['content']
            
        except (requests.RequestException, KeyError) as e:
            print(f"Error calling Grok API: {e}")
            return None
            
    def create_grok_prompt(self, sanitized_data, search_query):
        """Create a comprehensive prompt for Grok to generate the KB article."""
        ticket_summaries = []
        
        for i, ticket_data in enumerate(sanitized_data[:10], 1):  # Limit to first 10 tickets
            ticket = ticket_data['ticket']
            audits = ticket_data['audits']
            
            # Extract key information from audits
            key_events = []
            for audit in audits:
                for event in audit.get('events', []):
                    if event.get('type') in ['Comment', 'Status', 'Priority', 'Type']:
                        key_events.append({
                            'type': event.get('type'),
                            'field': event.get('field_name'),
                            'value': event.get('value')
                        })
            
            summary = f"""
Ticket {i}:
- Subject: {ticket.get('subject', 'N/A')}
- Status: {ticket.get('status', 'N/A')}
- Priority: {ticket.get('priority', 'N/A')}
- Description: {ticket.get('description', 'N/A')[:500]}...
- Key Resolution Steps: {len(key_events)} events found
- Tags: {', '.join(ticket.get('tags', []))}
"""
            ticket_summaries.append(summary)
        
        prompt = f"""
I need you to create a comprehensive knowledge base article based on the analysis of {len(sanitized_data)} Zendesk support tickets related to: "{search_query}"

Here's the ticket data:

{chr(10).join(ticket_summaries)}

Please create a knowledge base article that:

1. **Identifies the common problem** described in these tickets
2. **Provides a clear, step-by-step solution** based on the resolution patterns found in the ticket audits
3. **Includes troubleshooting tips** for common variations of the issue
4. **Is written in a professional, helpful tone** suitable for end users
5. **Follows the provided HTML template structure** (but you only need to provide the content, not the HTML tags)

The article should be:
- Comprehensive but concise
- Easy to follow for non-technical users
- Include prerequisites if applicable
- Include troubleshooting tips for edge cases
- Focus on the most common resolution paths found in the tickets

Please structure your response as follows:

**TITLE:** [Suggested article title]

**INTRODUCTION:** [Brief description of the problem/solution]

**PREREQUISITES:** [Any requirements or prerequisites]

**RESOLUTION STEPS:** [Detailed step-by-step solution]

**TROUBLESHOOTING TIPS:** [Common issues and solutions]

**ADDITIONAL INFORMATION:** [Any relevant additional details]

Focus on creating content that would genuinely help users solve this problem without needing to contact support.
"""

        return prompt
        
    def format_html_article(self, content, search_query):
        """Format the generated content into the HTML template."""
        print("Formatting article into HTML template...")
        
        # Extract sections from the generated content
        title = self.extract_section(content, "TITLE:", "INTRODUCTION:")
        introduction = self.extract_section(content, "INTRODUCTION:", "PREREQUISITES:")
        prerequisites = self.extract_section(content, "PREREQUISITES:", "RESOLUTION STEPS:")
        resolution_steps = self.extract_section(content, "RESOLUTION STEPS:", "TROUBLESHOOTING TIPS:")
        troubleshooting = self.extract_section(content, "TROUBLESHOOTING TIPS:", "ADDITIONAL INFORMATION:")
        additional_info = self.extract_section(content, "ADDITIONAL INFORMATION:", "")
        
        # Get the HTML template
        template = get_template()
        
        # Replace template placeholders with actual content
        html_content = template.replace("[Article Title]", title.strip() if title else f"Solution for: {search_query}")
        html_content = html_content.replace("[Brief description of the article]", introduction.strip() if introduction else f"This article provides a solution for issues related to: {search_query}")
        
        # Handle prerequisites section
        if prerequisites and prerequisites.strip():
            prereq_items = [item.strip() for item in prerequisites.split('\n') if item.strip() and item.strip().startswith('-')]
            prereq_html = '\n    '.join([f'<li>{item[1:].strip()}</li>' for item in prereq_items])
            html_content = html_content.replace('<li>[Prerequisite 1]</li>\n    <li>[Prerequisite 2]</li>', prereq_html)
        else:
            # Remove prerequisites section if empty
            prereq_start = html_content.find('<h2>Prerequisites</h2>')
            prereq_end = html_content.find('</ul>', prereq_start) + 5
            html_content = html_content[:prereq_start] + html_content[prereq_end:]
        
        # Handle resolution steps
        if resolution_steps and resolution_steps.strip():
            steps_items = [item.strip() for item in resolution_steps.split('\n') if item.strip()]
            steps_html = ''
            step_num = 1
            for step in steps_items:
                if step and not step.startswith('**') and not step.startswith('#'):
                    steps_html += f'  <li>\n    <p>{step}</p>\n  </li>\n'
                    step_num += 1
            
            html_content = html_content.replace('<li>\n    <p>[Step 1 description]</p>', steps_html.strip())
        
        # Handle troubleshooting tips
        if troubleshooting and troubleshooting.strip():
            tips_items = [item.strip() for item in troubleshooting.split('\n') if item.strip() and item.strip().startswith('-')]
            tips_html = '\n    '.join([f'<li>{item[1:].strip()}</li>' for item in tips_items])
            html_content = html_content.replace('<li>[Troubleshooting tip 1]</li>\n    <li>[Troubleshooting tip 2]</li>', tips_html)
        
        # Handle additional information
        if additional_info and additional_info.strip():
            info_items = [item.strip() for item in additional_info.split('\n') if item.strip() and item.strip().startswith('-')]
            info_html = '\n    '.join([f'<li>{item[1:].strip()}</li>' for item in info_items])
            html_content = html_content.replace('<li>[Additional note 1]</li>\n    <li>[Additional note 2]</li>', info_html)
        
        return html_content
        
    def extract_section(self, content, start_marker, end_marker):
        """Extract a section from the generated content."""
        start_idx = content.find(start_marker)
        if start_idx == -1:
            return ""
        
        start_idx += len(start_marker)
        
        if end_marker:
            end_idx = content.find(end_marker, start_idx)
            if end_idx == -1:
                end_idx = len(content)
        else:
            end_idx = len(content)
        
        return content[start_idx:end_idx].strip()
        
    def save_article(self, html_content, search_query):
        """Save the generated article to a file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_query = re.sub(r'[^\w\s-]', '', search_query).strip()
        safe_query = re.sub(r'[-\s]+', '_', safe_query)
        
        filename = f"kb_article_{safe_query}_{timestamp}.html"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"Knowledge base article saved as: {filename}")
            return filename
        except (IOError, OSError) as e:
            print(f"Error saving article: {e}")
            return None


class RateLimiter:
    """Simple rate limiter for API calls."""
    
    def __init__(self, max_requests_per_minute=350):
        self.max_requests_per_minute = max_requests_per_minute
        self.request_times = []
        
    def wait_if_needed(self):
        """Wait if approaching rate limits."""
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


def main():
    """Main function to orchestrate the KB article generation."""
    print("=== Zendesk Ticket to Knowledge Base Article Generator ===")
    
    # Get user input
    search_query = input("Enter the search query for Zendesk tickets: ").strip()
    if not search_query:
        print("Search query cannot be empty!")
        return
    
    max_tickets = input("Maximum number of tickets to analyze (default 20): ").strip()
    try:
        max_tickets = int(max_tickets) if max_tickets else 20
    except ValueError:
        max_tickets = 20
    
    # Initialize generator
    generator = TicketKnowledgeBaseGenerator()
    
    # Setup APIs
    if not generator.setup_apis():
        print("Failed to setup API connections. Exiting.")
        return
    
    try:
        # Search for tickets
        tickets = generator.search_tickets(search_query, max_tickets)
        if not tickets:
            print("No tickets found for the given search query.")
            return
        
        print(f"\nAnalyzing {len(tickets)} tickets...")
        
        # Get audit data for each ticket
        tickets_with_audits = []
        for i, ticket in enumerate(tickets, 1):
            print(f"Getting audit data for ticket {i}/{len(tickets)}: {ticket.get('id')}")
            audits = generator.get_ticket_audits(ticket['id'])
            tickets_with_audits.append({
                'ticket': ticket,
                'audits': audits
            })
            time.sleep(0.2)  # Rate limiting
        
        # Sanitize data
        sanitized_data = generator.sanitize_ticket_data(tickets_with_audits)
        
        # Generate KB article using Grok
        kb_content = generator.generate_kb_article_with_grok(sanitized_data, search_query)
        if not kb_content:
            print("Failed to generate knowledge base article.")
            return
        
        print("\nGenerated article content:")
        print("-" * 50)
        print(kb_content)
        print("-" * 50)
        
        # Format as HTML
        html_content = generator.format_html_article(kb_content, search_query)
        
        # Save article
        filename = generator.save_article(html_content, search_query)
        if filename:
            print("\n✅ Knowledge base article generated successfully!")
            print(f"📄 File saved as: {filename}")
            print(f"🔍 Based on {len(tickets)} tickets related to: '{search_query}'")
        else:
            print("\n❌ Failed to save the article.")
            
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
    except (requests.RequestException, ValueError, RuntimeError) as e:
        print(f"\n❌ An error occurred: {e}")


if __name__ == "__main__":
    main()
