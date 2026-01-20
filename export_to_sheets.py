"""
Export Shopify products directly to Google Sheets.
"""

import os
import pickle
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from shopify_client import ShopifyClient

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
CREDENTIALS_FILE = '/Users/nicholascollins/credentials.json'
TOKEN_FILE = '/Users/nicholascollins/token.pickle'


def get_google_creds():
    """Get or refresh Google credentials."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

    return creds


def export_products_to_google_sheets(
    store_domain: str = None,
    access_token: str = None,
    sheet_name: str = None,
):
    """Export Shopify products directly to a new Google Sheet."""

    if not sheet_name:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        sheet_name = f"Shopify Products - {timestamp}"

    print("Authenticating with Google...")
    creds = get_google_creds()
    sheets_service = build('sheets', 'v4', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)

    print("Connecting to Shopify...")
    client = ShopifyClient(store_domain=store_domain, access_token=access_token)

    print("Fetching active products...")
    products = list(client.get_products(status="active"))
    print(f"Found {len(products)} active products")

    # Collect metafields
    print("Fetching metafields...")
    all_metafield_keys = set()
    product_metafields = {}

    for i, product in enumerate(products):
        product_id = product['id']
        metafields = client.get_product_metafields(product_id)
        product_metafields[product_id] = metafields

        for mf in metafields:
            key = f"{mf.get('namespace', 'custom')}.{mf.get('key', 'unknown')}"
            all_metafield_keys.add(key)

        print(f"  [{i+1}/{len(products)}] {product.get('title', 'Unknown')[:40]}...")

    metafield_keys = sorted(all_metafield_keys)

    # Prepare headers
    headers = [
        'Product ID', 'Handle', 'Title', 'Status', 'Vendor', 'Product Type', 'Tags',
        'Created At', 'Updated At', 'Published At',
        'Main Image URL', 'All Image URLs',
        'Variant Count', 'First Variant SKU', 'First Variant Price', 'First Variant Barcode',
    ]
    headers.extend(metafield_keys)

    # Prepare data rows
    rows = [headers]

    for product in products:
        product_id = product['id']
        images = product.get('images', [])
        main_image = images[0].get('src', '') if images else ''
        all_images = ' | '.join([img.get('src', '') for img in images])
        variants = product.get('variants', [])
        first_variant = variants[0] if variants else {}

        row = [
            product_id,
            product.get('handle', ''),
            product.get('title', ''),
            product.get('status', ''),
            product.get('vendor', ''),
            product.get('product_type', ''),
            product.get('tags', ''),
            product.get('created_at', ''),
            product.get('updated_at', ''),
            product.get('published_at', ''),
            main_image,
            all_images,
            len(variants),
            first_variant.get('sku', ''),
            first_variant.get('price', ''),
            first_variant.get('barcode', ''),
        ]

        # Add metafield values
        metafields = product_metafields.get(product_id, [])
        metafield_dict = {}
        for mf in metafields:
            key = f"{mf.get('namespace', 'custom')}.{mf.get('key', 'unknown')}"
            metafield_dict[key] = mf.get('value', '')

        for key in metafield_keys:
            row.append(metafield_dict.get(key, ''))

        rows.append(row)

    # Create Google Sheet
    print(f"\nCreating Google Sheet: {sheet_name}")
    spreadsheet = sheets_service.spreadsheets().create(body={
        'properties': {'title': sheet_name},
        'sheets': [{'properties': {'title': 'Products'}}]
    }).execute()

    spreadsheet_id = spreadsheet['spreadsheetId']
    spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    # Write data
    print("Writing data to sheet...")
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range='Products!A1',
        valueInputOption='RAW',
        body={'values': rows}
    ).execute()

    # Format header row (bold, frozen)
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            'requests': [
                {
                    'repeatCell': {
                        'range': {'sheetId': 0, 'startRowIndex': 0, 'endRowIndex': 1},
                        'cell': {
                            'userEnteredFormat': {
                                'textFormat': {'bold': True},
                                'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
                            }
                        },
                        'fields': 'userEnteredFormat(textFormat,backgroundColor)'
                    }
                },
                {
                    'updateSheetProperties': {
                        'properties': {'sheetId': 0, 'gridProperties': {'frozenRowCount': 1}},
                        'fields': 'gridProperties.frozenRowCount'
                    }
                }
            ]
        }
    ).execute()

    print(f"\nDone!")
    print(f"  Products exported: {len(products)}")
    print(f"  Metafield columns: {len(metafield_keys)}")
    print(f"  Google Sheet URL: {spreadsheet_url}")

    return spreadsheet_url


if __name__ == "__main__":
    # Uses SHOPIFY_STORE_DOMAIN and SHOPIFY_ACCESS_TOKEN from environment or .env
    export_products_to_google_sheets()
