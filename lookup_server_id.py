"""
One-off helper to find your PST Server Serial Number.

The WebPST UI doesn't display it directly, but the API's Entities Search
endpoint (read-only) does. This only requires PST_API_USERNAME,
PST_API_PASSWORD, and PST_DBS_CODE to be set in your .env file.

Usage:
    python lookup_server_id.py Kosearas
    (or run with no argument and it will prompt you)
"""
import os
import sys

from dotenv import load_dotenv

from pst_client import PstApiError, PstClient

load_dotenv()


def main():
    last_name = sys.argv[1] if len(sys.argv) > 1 else input("Last name to search for: ").strip()

    pst = PstClient(
        api_username=os.environ["PST_API_USERNAME"],
        api_password=os.environ["PST_API_PASSWORD"],
        dbs_code=os.environ["PST_DBS_CODE"],
    )

    try:
        entities = pst.search_entities(SearchBy="LastName", SearchText=last_name, EntityType="Server")
    except PstApiError as exc:
        print(f"PST API error: {exc}")
        return

    if not entities:
        print(f"No server entities found matching last name '{last_name}'.")
        return

    print(f"Found {len(entities)} match(es):\n")
    for entity in entities:
        print(f"  Serial Number: {entity.get('SerialNumber')}")
        print(f"  Name:          {entity.get('FirstName')} {entity.get('LastName')}")
        print(f"  Firm:          {entity.get('FirmName')}")
        print(f"  Email:         {entity.get('EmailAddress')}")
        print()


if __name__ == "__main__":
    main()
