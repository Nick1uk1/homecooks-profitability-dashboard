"""
Export Shopify products to CSV for Google Sheets.
Includes product details, images, and metafields.

Usage:
    python export_products.py

Requires environment variables:
    SHOPIFY_STORE_DOMAIN - Your store domain (e.g., mystore.myshopify.com)
    SHOPIFY_ACCESS_TOKEN - Your Shopify Admin API access token

Or create a .env file with these values.
"""

import csv
import os
from datetime import datetime
from shopify_client import ShopifyClient

# Try to load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def export_products_to_csv(
    output_path: str = None,
    include_metafields: bool = True,
    store_domain: str = None,
    access_token: str = None,
):
    """
    Export all active Shopify products to CSV.

    Args:
        output_path: Path for output CSV file (default: Desktop)
        include_metafields: Whether to fetch metafields for each product
    """
    if not output_path:
        desktop = os.path.expanduser("~/Desktop")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(desktop, f"shopify_products_{timestamp}.csv")

    print("Connecting to Shopify...")
    client = ShopifyClient(store_domain=store_domain, access_token=access_token)

    print("Fetching active products...")
    products = list(client.get_products(status="active"))
    print(f"Found {len(products)} active products")

    # Collect all unique metafield keys
    all_metafield_keys = set()
    product_metafields = {}

    if include_metafields:
        print("Fetching metafields for each product...")
        for i, product in enumerate(products):
            product_id = product['id']
            metafields = client.get_product_metafields(product_id)
            product_metafields[product_id] = metafields

            for mf in metafields:
                key = f"{mf.get('namespace', 'custom')}.{mf.get('key', 'unknown')}"
                all_metafield_keys.add(key)

            print(f"  [{i+1}/{len(products)}] {product.get('title', 'Unknown')[:50]}... ({len(metafields)} metafields)")

    # Sort metafield keys for consistent column order
    metafield_keys = sorted(all_metafield_keys)

    # Prepare CSV headers
    headers = [
        'Product ID',
        'Handle',
        'Title',
        'Status',
        'Vendor',
        'Product Type',
        'Tags',
        'Created At',
        'Updated At',
        'Published At',
        'Main Image URL',
        'All Image URLs',
        'Variant Count',
        'First Variant SKU',
        'First Variant Price',
        'First Variant Barcode',
    ]
    headers.extend(metafield_keys)

    # Write CSV
    print(f"\nWriting to {output_path}...")
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for product in products:
            product_id = product['id']

            # Get images
            images = product.get('images', [])
            main_image = images[0].get('src', '') if images else ''
            all_images = ' | '.join([img.get('src', '') for img in images])

            # Get first variant info
            variants = product.get('variants', [])
            first_variant = variants[0] if variants else {}

            # Build row
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

            writer.writerow(row)

    print(f"\nExport complete!")
    print(f"  Products exported: {len(products)}")
    print(f"  Metafield columns: {len(metafield_keys)}")
    print(f"  Output file: {output_path}")
    print("\nYou can now upload this CSV to Google Sheets:")
    print("  1. Go to sheets.google.com")
    print("  2. File > Import > Upload")
    print("  3. Select the CSV file")

    return output_path


if __name__ == "__main__":
    export_products_to_csv()
