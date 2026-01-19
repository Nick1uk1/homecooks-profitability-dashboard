# HomeCooks Order Profitability Dashboard

A comprehensive Streamlit dashboard for tracking order profitability across D2C, Retail, and Go Puff sales channels.

## Features

### HomeCooks D2C Tab
- **Order tracking by dispatch date** - Uses Linnworks processed dates (not Shopify created dates)
- **Monday & Thursday dispatch filtering** - Focus on specific dispatch days
- **Profitability calculation**: Revenue - COGS - Packaging = Profit
- **COGS from Shopify** - Pulls InventoryItem.cost for each variant
- **Packaging costs** based on SKU count:
  - Small (1-10 SKUs): £12.66
  - Large (11-16 SKUs): £13.81
  - 2x Large (>16 SKUs): £27.62
- **Weekly breakdown** with calendar date ranges
- Customer names, SKU counts, box info, discounts, shipping, contribution margin

### HomeCooks Retail Tab
- **B2B retail store orders** from Linnworks (identified by "No Shipping Required" shipping method)
- **MTD (Month to Date)** revenue and orders - resets each month
- **YTD (Year to Date)** cumulative revenue
- **Variance analysis**:
  - vs Last Month (same period comparison)
  - vs LFL (Like-for-Like, same period last year)
- **All-time store list** with order count and last order date
- Duplicate store name detection with warnings

### Go Puff Sales Tab
- **SKU of the Day** - Top selling product today
- **Weekly Top Seller** - Best performer this week
- **Monthly Top Seller** - Best performer this month
- **All-Time Top Seller** - Historical best
- **Today's Sales by Product** - Breakdown with quantities and percentages
- **Weekly Sales Navigator** - View and compare previous weeks
- Data sourced from Google Sheets (auto-synced)

### Dashboard Features
- **Auto-refresh at 8am daily** - Data automatically refreshes each morning
- **HomeCooks branding** - Custom teal/mint color scheme with logo
- **Responsive layout** - Filters in sidebar, KPIs always visible
- **Export capabilities** - Download data as needed

## Installation

### Prerequisites
- Python 3.9+
- Shopify Admin API access token
- Linnworks API credentials

### Setup

1. Clone the repository:
```bash
git clone https://github.com/YOUR_USERNAME/homecooks-profitability-dashboard.git
cd homecooks-profitability-dashboard
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create environment file:
```bash
cp .env.example .env
```

4. Edit `.env` with your credentials:
```
SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxx
SHOPIFY_API_VERSION=2024-07

LINNWORKS_APP_ID=your-app-id
LINNWORKS_APP_SECRET=your-app-secret
LINNWORKS_INSTALL_TOKEN=your-install-token
```

5. Run the dashboard:
```bash
streamlit run app.py
```

The dashboard will open at `http://localhost:8501`

## Deployment Options

### Streamlit Cloud (Recommended)
1. Push repository to GitHub
2. Connect to [Streamlit Cloud](https://streamlit.io/cloud)
3. Add secrets in Streamlit Cloud dashboard settings

### Local with Environment Variables
```bash
SHOPIFY_STORE_DOMAIN="your-store.myshopify.com" \
SHOPIFY_ACCESS_TOKEN="shpat_xxx" \
streamlit run app.py
```

## Project Structure

```
homecooks-profitability-dashboard/
├── app.py              # Main Streamlit application (all 3 tabs)
├── shopify_client.py   # Shopify API client with pagination & rate limiting
├── linnworks_client.py # Linnworks API client for dispatch data
├── costing.py          # COGS and packaging cost calculations
├── metrics.py          # Order processing and KPI calculations
├── assets/
│   └── logo.jpeg       # HomeCooks logo
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── .gitignore          # Git ignore rules
└── README.md           # This file
```

## API Requirements

### Shopify Admin API
Required scopes:
- `read_orders` - Fetch order data
- `read_products` - Lookup variant information
- `read_inventory` - Get InventoryItem.cost for COGS

### Linnworks API
- Application credentials (App ID, App Secret, Install Token)
- Access to ProcessedOrders and Orders endpoints

## Data Sources

| Data | Source | Update Frequency |
|------|--------|------------------|
| Order details, COGS | Shopify Admin API | Real-time |
| Dispatch dates | Linnworks ProcessedOrders | Real-time |
| Retail orders | Linnworks (No Shipping Required) | Real-time |
| Go Puff sales | Google Sheets | Daily |

## Profitability Calculations

### Revenue
```
gross_item_value = sum(line_item.price × quantity)
total_discounts = order-level or line-level discount allocations
net_revenue = gross_item_value - total_discounts
```

### COGS
For each line item:
1. Look up `variant_id` → get `inventory_item_id`
2. Fetch `InventoryItem` → get `cost`
3. `line_cogs = unit_cost × quantity`
4. `total_cogs = sum(line_cogs)`

### Packaging Costs
| SKU Count | Box Type | Cost |
|-----------|----------|------|
| 1-10 | Small | £12.66 |
| 11-16 | Large | £13.81 |
| > 16 | 2x Large | £27.62 |

### Profit Metrics
```
contribution = net_revenue - cogs - packaging_total
contribution_margin_% = contribution / net_revenue × 100
```

## Caching

- **Orders cache**: 5 minutes TTL
- **Variant costs**: 1 hour TTL + session state
- **Retail orders**: 10 minutes TTL
- **Auto-refresh**: Daily at 8am (clears all caches)

Use "Clear Cache" button in sidebar to force refresh.

## Troubleshooting

### Missing environment variables
Ensure all required variables are set in `.env` or environment.

### Rate limiting (429 errors)
The app handles rate limits automatically. If persistent, reduce date range.

### Missing COGS
- Check products have cost set in Shopify admin
- Verify API token has `read_inventory` scope

## License

Private - HomeCooks internal use only.
