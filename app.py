from flask import Flask, request, render_template, send_file, redirect, url_for, session, render_template_string
import os
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build

import logging
import requests


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

def rgb_to_hex(rgb):
    r = int(rgb.get('red', 1) * 255)
    g = int(rgb.get('green', 1) * 255)
    b = int(rgb.get('blue', 1) * 255)
    return '#{:02X}{:02X}{:02X}'.format(r, g, b)

def get_matching_google_sheet_rows(engine_code):
    try:
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
        creds = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)

        SPREADSHEET_ID = '1iH-70OrINA2jcd6YKszW-N8XpuJDTC9A3oArNWHbEeY'
        RANGE = 'Sheet1'

        service = build('sheets', 'v4', credentials=creds)

        values_result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=RANGE).execute()
        values = values_result.get('values', [])

        format_result = service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID,
            ranges=[RANGE],
            fields='sheets.data.rowData.values.effectiveFormat.backgroundColor'
        ).execute()

        row_data = format_result['sheets'][0]['data'][0]['rowData']

        headers = values[0]
        rows = []

        for i, row in enumerate(values[1:], start=1):
            row_dict = {}
            for j, cell in enumerate(row):
                if j in (17, 18):  # Skip columns R and S
                    continue
                cell_text = cell
                bg_color = row_data[i]['values'][j].get('effectiveFormat', {}).get('backgroundColor', {})
                hex_color = rgb_to_hex(bg_color)
                key = headers[j]
                row_dict[key] = {'value': cell_text, 'bg': hex_color}
            if any(engine_code.lower() in str(c).lower() for c in row):
                rows.append(row_dict)

        return rows

    except Exception as e:
        print("Error accessing Google Sheets:", e)
        return []

EBAY_API_ENDPOINT = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_GB")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
EBAY_OAUTH_TOKEN = os.getenv("EBAY_OAUTH_TOKEN")

if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
    logger.warning("eBay client ID/secret are not fully configured. Token refresh will not be available.")


def _sanitize_vehicle_term(value):
    """Return a cleaned vehicle search term containing only alphanumerics and spaces."""

    if not value:
        return ""
    cleaned = re.sub(r"[^0-9A-Za-z ]", " ", str(value))
    return " ".join(cleaned.split())


def query_ebay_api(model, year, min_price=None, max_price=None, limit=50):
    """Query the eBay Browse API and return parsed item summaries."""

    if not EBAY_OAUTH_TOKEN:
        logger.error("EBAY_OAUTH_TOKEN is not configured. Unable to query eBay API.")
        return [], "eBay API credentials are not configured."

    sanitized_model = _sanitize_vehicle_term(model)
    sanitized_year = "".join(ch for ch in str(year) if ch.isdigit())
    query = " ".join(part for part in (sanitized_model, sanitized_year) if part).strip()
    if not query:
        logger.error("Attempted to query eBay API without a search keyword.")
        return [], "Missing search keyword for the eBay query."

    params = {
        "q": query,
        "limit": str(limit),
    }

    price_filters = []
    if min_price is not None and max_price is not None:
        price_filters.append(f"price:[{min_price}..{max_price}]")
    elif min_price is not None:
        price_filters.append(f"price:[{min_price}..]")
    elif max_price is not None:
        price_filters.append(f"price:[..{max_price}]")

    if price_filters:
        params["filter"] = ",".join(price_filters)

    headers = {
        "Authorization": f"Bearer {EBAY_OAUTH_TOKEN}",
        "Content-Type": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
    }

    try:
        response = requests.get(EBAY_API_ENDPOINT, params=params, headers=headers, timeout=15)
        logger.info("Queried eBay API with params %s; status code %s", params, response.status_code)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        if status_code == 401:
            logger.error("eBay API authentication failed (401). Token may be expired.")
            return [], "eBay authentication failed. Please refresh the OAuth token."
        logger.error("eBay API request failed with status %s: %s", status_code, exc)
        return [], "eBay API request failed. Please try again later."
    except requests.RequestException as exc:
        logger.error("Network error while querying eBay API: %s", exc)
        return [], "Unable to reach the eBay API. Please try again later."

    try:
        payload = response.json()
    except ValueError:
        logger.error("Failed to parse eBay API response as JSON.")
        return [], "Received an unexpected response from the eBay API."

    items = []
    model_lower = sanitized_model.lower()
    year_lower = sanitized_year.lower()
    for item in payload.get("itemSummaries", []):
        title = item.get("title")
        url = item.get("itemWebUrl")
        price_info = item.get("price") or {}
        try:
            price = float(price_info.get("value"))
        except (TypeError, ValueError):
            logger.debug("Skipping eBay item without a valid price: %s", item)
            continue
        if not title or not url:
            logger.debug("Skipping eBay item missing title or URL: %s", item)
            continue

        title_lower = title.lower()
        if model_lower:
            if model_lower not in title_lower:
                logger.debug(
                    "Skipping eBay item without model match: %s",
                    {"title": title},
                )
                continue
        if year_lower:
            if year_lower not in title_lower:
                logger.debug(
                    "Skipping eBay item without year match: %s",
                    {"title": title},
                )
                continue
        items.append({"title": title, "price": price, "link": url})

    if not items:
        logger.info("eBay API returned no item summaries for query '%s'.", query)

    return items, None


def render_parts_table(parts):
    html = (
        "<table class='table table-striped'><thead><tr><th>Title</th><th>Price</th><th>Link"\

        "</th></tr></thead><tbody>"
    )
    for part in parts:
        html += (
            f"<tr><td>{part['title']}</td><td>£{part['price']:.2f}</td>"
            f"<td><a href='{part['link']}' target='_blank'>View</a></td></tr>"
        )
    html += "</tbody></table>"
    return render_template_string(html)

file_path = 'WebFleet.csv'
df = pd.read_csv(file_path)

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here'

USERS = {
    'admin': 'Silverlake1!',
    'nacho': 'Silverlake1!'
}

last_search_result = None
search_details = None

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in USERS and USERS[username] == password:
            session['logged_in'] = True
            session['login_time'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            return redirect(url_for('index'))
        else:
            error = 'Invalid Credentials. Please try again.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.before_request
def require_login():
    allowed_routes = ['login', 'static', 'autocomplete_model']
    if request.endpoint not in allowed_routes and not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('logged_in'):
        login_time = session.get('login_time')
        if login_time:
            login_time = datetime.strptime(login_time, '%Y-%m-%d %H:%M:%S')
            if datetime.utcnow() - login_time > timedelta(hours=24):
                session.clear()
                return redirect(url_for('login'))

@app.route('/autocomplete_model', methods=['GET'])
def autocomplete_model():
    query = request.args.get('query', '')
    if query:
        filtered_models = df['Model'].dropna().unique()
        matches = [model for model in filtered_models if query.lower() in model.lower()]
        return {'models': matches}
    return {'models': []}

@app.route('/', methods=['GET', 'POST'])
def index():
    global last_search_result, search_details
    parts = None
    google_sheet_matches = []
    if request.method == 'POST':
        model = request.form['model']
        year = int(request.form['year'])
        engine_code = request.form.get('engine_code', '').strip()
        min_price = request.form.get('min_price')
        min_opportunity = request.form.get('min_opportunity')
        action = request.form.get('action')

        # Initial filtering
        filtered = df[
            (df['Model'].str.lower() == model.lower()) &
            (df['IC Start Year'] <= year) &
            (df['IC End Year'] >= year)
        ]

        if engine_code:
            def custom_filter(row):
                description = str(row['IC Description'])
                if 'engine code' in description.lower():
                    return engine_code.lower() in description.lower()
                return True
            filtered = filtered[filtered.apply(custom_filter, axis=1)]

        # 🚨 NEW: exclusion list logic
        if action == 'search_excluding':
            exclusion_keywords = [
                "ENGINE", "TRANS/GEARBOX", "TURBOCHARGER", "SUPERCHARGER", "THROTTLE_BODY",
                "ALTERNATOR", "STARTER", "A/C_COMPRESSOR", "Cylinder_head",
                "FUEL_INJECTOR", "Injector_rail", "COIL/COIL_PACK",
                "Injector_pump", "OIL_PAN/SUMP", "EGR_VALVE/COOLER"
            ]
            pattern = '|'.join(rf'\b{kw}\b' for kw in exclusion_keywords)
            filtered = filtered[~filtered['Part'].str.contains(pattern, case=False, na=False, regex=True)]

        # Proceed with opportunity calculations if there's something left
        if not filtered.empty:
            filtered['Potential_Profit'] = (filtered['Backorders'] + filtered['Not Found 180 days']) * filtered['B Price']
            filtered['Sales_Speed'] = filtered['Parts Sold All'] / (filtered['Parts in Stock'] + 1)
            filtered['Opportunity_Score'] = filtered['Potential_Profit'] * filtered['Sales_Speed']

            if min_price:
                filtered = filtered[filtered['B Price'] >= float(min_price)]
            if min_opportunity:
                filtered = filtered[filtered['Opportunity_Score'] >= float(min_opportunity)]

            parts = filtered[['Part', 'IC Start Year', 'IC End Year', 'IC Description', 'B Price', 'Parts in Stock', 'Backorders',
                              'Parts Sold All', 'Not Found 180 days', 'Potential_Profit', 'Sales_Speed', 'Opportunity_Score']]
            parts = parts.sort_values(by=['Backorders', 'Opportunity_Score'], ascending=False).head(50)
            last_search_result = parts
            search_details = {'model': model, 'year': year, 'engine_code': engine_code}
            parts = parts.to_dict('records')

        if engine_code:
            google_sheet_matches = get_matching_google_sheet_rows(engine_code)

    return render_template('index.html', parts=parts, search_details=search_details, google_sheet_matches=google_sheet_matches)

@app.route('/download')
def download():
    global last_search_result
    if last_search_result is not None:
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            last_search_result.to_excel(writer, index=False, sheet_name='Parts')
        output.seek(0)
        return send_file(output, download_name="parts_opportunity.xlsx", as_attachment=True)
    return "No data to download", 400

@app.route('/ebay_small_parts')
def ebay_small_parts():
    model = request.args.get('model', '').strip()
    year = request.args.get('year', '').strip()
    if not model or not year:
        return "Model and year are required.", 400

    parts, error = query_ebay_api(model, year, max_price=50)
    if error:
        return render_template_string(f"<p><strong>{error}</strong></p>")

    logger.info("Parsed %d candidate items in eBay search Small.", len(parts))

    part_list = [part for part in parts if part["price"] <= 50]

    if not part_list:
        return render_template_string("<p>No eBay results found under £50 for the selected vehicle.</p>")

    part_list.sort(key=lambda x: x["price"], reverse=True)

    return render_parts_table(part_list)

@app.route('/ebay_medium_parts')
def ebay_medium_parts():
    model = request.args.get('model', '').strip()
    year = request.args.get('year', '').strip()
    if not model or not year:
        return "Model and year are required.", 400

    parts, error = query_ebay_api(model, year, min_price=50, max_price=500)
    if error:
        return render_template_string(f"<p><strong>{error}</strong></p>")

    logger.info("Parsed %d candidate items in eBay search Medium.", len(parts))

    part_list = [part for part in parts if part["price"] > 50 and part["price"] <= 500]

    if not part_list:
        return render_template_string("<p>No eBay results found between £50 and £500 for the selected vehicle.</p>")

    part_list.sort(key=lambda x: x["price"], reverse=False)

    return render_parts_table(part_list)
    
@app.route('/ebay_large_parts')
def ebay_large_parts():
    model = request.args.get('model', '').strip()
    year = request.args.get('year', '').strip()
    if not model or not year:
        return "Model and year are required.", 400

    parts, error = query_ebay_api(model, year, min_price=500, max_price=5000)
    if error:
        return render_template_string(f"<p><strong>{error}</strong></p>")

    logger.info("Parsed %d candidate items in eBay search Large.", len(parts))

    part_list = [part for part in parts if part["price"] >= 500]

    if not part_list:
        return render_template_string("<p>No eBay results found over £500 for the selected vehicle.</p>")

    part_list.sort(key=lambda x: x["price"], reverse=True)

    return render_parts_table(part_list)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')







