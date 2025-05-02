import requests
import json
import os
from config import zendesk_subdomain, zendesk_user
from secret_manager import access_secret_version

# Setup authentication
zendesk_secret = access_secret_version("billing-sync", "ZENDESK_API_TOKEN", "latest")
session = requests.Session()
session.auth = (zendesk_user, zendesk_secret)

def fetch_all_organizations():
    """Fetch all organizations from Zendesk."""
    organizations = []
    endpoint = f"https://{zendesk_subdomain}/api/v2/organizations.json"
    while endpoint:
        response = session.get(endpoint)
        if response.status_code != 200:
            print(f"Failed to fetch organizations: {response.status_code}")
            print(f"Response: {response.text}")  # Add detailed error message
            break
        data = response.json()
        organizations.extend(data["organizations"])
        endpoint = data.get("next_page")
    return organizations

def fetch_users_by_org(org_id):
    """Fetch all users for a given organization."""
    users = []
    endpoint = f"https://{zendesk_subdomain}/api/v2/organizations/{org_id}/users.json"
    while endpoint:
        response = session.get(endpoint)
        if response.status_code != 200:
            print(f"Failed to fetch users for org {org_id}: {response.status_code}")
            break
        data = response.json()
        users.extend(data["users"])
        endpoint = data.get("next_page")
    return [user["email"] for user in users]

def enrich_customers(customers_file="customers.json"):
    """Enrich customers.json with organization_id and authorized_emails."""
    # Load customers
    with open(customers_file, "r", encoding="utf-8") as f:
        customers = json.load(f)

    # Fetch organization data
    organizations = fetch_all_organizations()
    
    # Fix: Use domain_names instead of domains from Zendesk API
    org_map = {org["id"]: {"name": org["name"], "domain_names": org.get("domain_names", [])} 
               for org in organizations}

    # Enrich each customer
    for customer in customers.get("customers", []):
        customer_name = customer.get("name")
        customer_domains = customer.get("domains", [])
        matched_org_id = None

        # Match by name or domain
        for org_id, org_data in org_map.items():
            # Match by name
            if customer_name and customer_name.lower() == org_data["name"].lower():
                matched_org_id = org_id
                break
            
            # Match by domain
            if customer_domains:
                for domain in customer_domains:
                    if domain in org_data["domain_names"]:
                        matched_org_id = org_id
                        break
                if matched_org_id:
                    break

        if matched_org_id:
            customer["organization_id"] = matched_org_id
            customer["authorized_emails"] = fetch_users_by_org(matched_org_id)
        else:
            customer["organization_id"] = None
            customer["authorized_emails"] = []

    # Save enriched data
    with open(customers_file, "w", encoding="utf-8") as f:
        json.dump(customers, f, indent=2)
    print(f"Enriched data saved to {customers_file}")

if __name__ == "__main__":
    enrich_customers()