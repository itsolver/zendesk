#!/usr/bin/env python3
"""
Sort customers.json alphabetically by customer name (case-insensitive)

This is a one-time utility to sort the existing customers.json file
to match the sorting behavior of the sync_customers_managed_support.py script.
"""

import json
import os

# Path to the customers.json file
CUSTOMERS_FILE = r"C:\Users\AngusMcLauchlan\Projects\itsolver\gsuitedev\Prompting\Claude\IT Solver\customers.json"

def sort_customers_by_name():
    """Sort customers.json alphabetically by customer name."""
    print("Loading customers.json...")

    # Load the JSON file
    try:
        with open(CUSTOMERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: {CUSTOMERS_FILE} not found")
        return False
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {CUSTOMERS_FILE}: {e}")
        return False

    # Get the customers array
    customers = data.get('customers', [])
    print(f"Found {len(customers)} customers")

    # Sort customers by name (case-insensitive)
    customers.sort(key=lambda x: x.get('name', '').lower())

    # Update the data with sorted customers
    data['customers'] = customers

    # Add/update sorting metadata
    data['last_sorted'] = "alphabetically by name (case-insensitive)"

    # Save the sorted data back to the file
    try:
        with open(CUSTOMERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✓ Successfully sorted {len(customers)} customers alphabetically by name")
        print(f"✓ Updated {CUSTOMERS_FILE}")
        return True
    except Exception as e:
        print(f"Error: Failed to save sorted data: {e}")
        return False

def main():
    """Main function."""
    print("=" * 60)
    print("Customer JSON Sorter")
    print("=" * 60)
    print(f"Target file: {CUSTOMERS_FILE}")
    print()

    success = sort_customers_by_name()

    if success:
        print("\n" + "=" * 60)
        print("SORTING COMPLETE")
        print("=" * 60)
        print("Customers are now sorted alphabetically by name!")
        print("=" * 60)
        return True
    else:
        print("✗ Sorting failed")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
