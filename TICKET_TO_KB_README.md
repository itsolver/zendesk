# Zendesk Ticket to Knowledge Base Article Generator

This script searches Zendesk tickets for a specific string, retrieves their audit data, and uses the Grok API to generate a comprehensive knowledge base article that can be published on the IT Solver Zendesk Guide.

## Features

- **Smart Ticket Search**: Searches Zendesk tickets using user-defined queries
- **Audit Data Retrieval**: Gets complete audit trails for matching tickets
- **Privacy Protection**: Automatically removes personal information (emails, names, phone numbers, IPs) before sending data to Grok
- **AI-Powered Generation**: Uses Grok Code Fast model to analyze ticket patterns and create helpful KB articles
- **HTML Template Integration**: Formats articles using the provided Zendesk Guide template
- **Rate Limiting**: Respects Zendesk API rate limits to avoid throttling

## Prerequisites

1. **Google Cloud Access**: Must have access to the `billing-sync` project with Secret Manager permissions
2. **Environment Variables**: 
   - `GOOGLE_APPLICATION_CREDENTIALS` must be set
   - Or run interactive authentication when prompted
3. **API Keys**: The following secrets must be stored in Google Cloud Secret Manager:
   - `ZENDESK_API_TOKEN`: Your Zendesk API token
   - `GROK_API_KEY`: Your Grok API key

## Installation

1. Ensure you have the required Python packages:
   ```bash
   pip install requests
   ```

2. Make sure the following files are in the same directory:
   - `ticket_to_kb_generator.py` (main script)
   - `zendesk_guide_article_template.py` (HTML template)
   - `config.py` (Zendesk configuration)
   - `secret_manager.py` (Google Cloud Secret Manager integration)

## Usage

Run the script:
```bash
python ticket_to_kb_generator.py
```

The script will prompt you for:
1. **Search Query**: The string to search for in Zendesk tickets
   - Examples: "password reset", "email not working", "VPN connection issues"
2. **Maximum Tickets**: How many tickets to analyze (default: 20)

## How It Works

1. **Search Phase**: Searches Zendesk tickets using the provided query
2. **Data Collection**: Retrieves audit data for each matching ticket
3. **Privacy Sanitization**: Removes personal information from all ticket data
4. **AI Analysis**: Sends sanitized data to Grok API for analysis
5. **Article Generation**: Grok generates a comprehensive KB article based on common patterns
6. **HTML Formatting**: Formats the article using the Zendesk Guide template
7. **File Output**: Saves the article as an HTML file with timestamp

## Output

The script generates an HTML file named: `kb_article_[search_query]_[timestamp].html`

Example: `kb_article_password_reset_20241201_143022.html`

## Privacy & Security

- **Personal Data Removal**: Automatically removes:
  - Email addresses → `[EMAIL]`
  - Phone numbers → `[PHONE]`
  - Names → `[NAME]`
  - IP addresses → `[IP_ADDRESS]`
  - URLs → `[URL]`
- **No Data Storage**: Ticket data is processed in memory only
- **Secure API**: Uses Google Cloud Secret Manager for API key storage

## Rate Limiting

The script implements intelligent rate limiting:
- **Zendesk API**: Respects 400 requests/minute limit (uses 350 req/min for safety)
- **Grok API**: Includes retry logic for rate limit responses
- **Progressive Delays**: Automatically adjusts request timing

## Troubleshooting

### Common Issues

1. **"Cannot access Google Cloud Secret Manager"**
   - Ensure `GOOGLE_APPLICATION_CREDENTIALS` is set
   - Run `gcloud auth application-default login` if needed
   - Verify access to the `billing-sync` project

2. **"No tickets found"**
   - Try broader search terms
   - Check if the search query matches your ticket content
   - Ensure you have access to the tickets being searched

3. **"Grok API error"**
   - Verify the `GROK_API_KEY` secret exists in Secret Manager
   - Check if the API key is valid and has sufficient credits
   - Ensure internet connectivity to x.ai API

4. **Rate limiting errors**
   - The script handles this automatically with retries
   - If persistent, try reducing the maximum ticket count

### API Limits

- **Zendesk**: 400 requests/minute for Professional plans
- **Grok**: Varies by plan, typically 1000 requests/day for free tier

## Example Output

The generated article will include:
- **Title**: Based on the common issue identified
- **Introduction**: Problem description
- **Prerequisites**: Requirements (if applicable)
- **Resolution Steps**: Step-by-step solution
- **Troubleshooting Tips**: Common variations and solutions
- **Additional Information**: Relevant details
- **Feedback Section**: Encouraging user interaction
- **Support Referral**: Link to IT Solver support plans

## Customization

To modify the article template, edit `zendesk_guide_article_template.py` and update the `get_template()` function.

## Support

For issues with this script, contact the IT Solver development team or refer to the main Zendesk backup documentation.
