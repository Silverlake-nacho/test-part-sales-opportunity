from flask import Flask, request, render_template, send_file, redirect, url_for, session
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build

import json
import logging
import re
import time
import requests
from bs4 import BeautifulSoup
from flask import request, render_template_string
from collections import defaultdict
from urllib.parse import urlencode, quote_plus, urljoin


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


EBAY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
    "Referer": "https://www.ebay.co.uk/",
}


def build_ebay_search_url(model, year, min_price=None, max_price=None):
    query = f"{model} {year}".strip()
    params = {
        "_nkw": query,
        "LH_ItemCondition": "4",
        "rt": "nc",
        "_sop": "12",
        "LH_Complete": "1",
        "LH_Sold": "1",
    }
    if min_price is not None:
        params["_udlo"] = str(min_price)
    if max_price is not None:
        params["_udhi"] = str(max_price)
    return "https://www.ebay.co.uk/sch/131090/i.html?" + urlencode(params, quote_via=quote_plus)


def parse_price_value(value):
    if value is None:
        return None
    price_str = str(value).replace(",", "").replace("\xa0", " ").strip()
    match = re.search(r"\d+(?:\.\d+)?", price_str)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def get_price_from_offer(offer):
    if not isinstance(offer, dict):
        return None
    for key in ("price", "lowPrice", "highPrice"):
        price = parse_price_value(offer.get(key))
        if price is not None:
            return price
    price_spec = offer.get("priceSpecification")
    if isinstance(price_spec, dict):
        for key in ("price", "minPrice", "maxPrice"):
            price = parse_price_value(price_spec.get(key))
            if price is not None:
                return price
    return None


def extract_items_from_jsonld(soup):
    parts = []
    seen = set()

    def process_entry(entry):
        if not isinstance(entry, dict):
            return
        item = entry.get("item")
        if not isinstance(item, dict):
            return
        title = item.get("name") or entry.get("name")
        url = entry.get("url") or item.get("url")
        if not title or not url:
            return
        offers = item.get("offers")
        price = None
        if isinstance(offers, list):
            for offer in offers:
                price = get_price_from_offer(offer)
                if price is not None:
                    break
        elif isinstance(offers, dict):
            price = get_price_from_offer(offers)
        if price is None:
            return
        if not url.startswith("http"):
            url = urljoin("https://www.ebay.co.uk", url)
        key = (title, url)
        if key in seen:
            return
        seen.add(key)
        parts.append({"title": title, "price": price, "link": url})

    def walk(node):
        if isinstance(node, dict):
            node_type = node.get("@type")
            if node_type == "ItemList" and isinstance(node.get("itemListElement"), list):
                for entry in node["itemListElement"]:
                    process_entry(entry)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    walk(item)

    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or "".join(script.strings)
        if not text:
            continue
        text = text.strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        walk(data)

    return parts


def extract_items_from_html(soup):
    parts = []
    seen = set()
    for item in soup.select(".s-item"):
        title_tag = item.select_one(".s-item__title") or item.select_one('[data-testid="ITEM_TITLE"]')
        link_tag = item.select_one(".s-item__link")
        if link_tag is None:
            link_tag = item.find("a", href=True)
        price_tag = item.select_one(".s-item__price") or item.select_one('[data-testid="ITEM_PRICE"]')

        if not link_tag or not link_tag.get("href"):
            continue

        url = link_tag.get("href")
        if not url.startswith("http"):
            url = urljoin("https://www.ebay.co.uk", url)

        title = title_tag.get_text(strip=True) if title_tag else None
        price_text = price_tag.get_text(" ", strip=True) if price_tag else None
        price = parse_price_value(price_text)

        if not title or price is None:
            continue

        key = (title, url)
        if key in seen:
            continue
        seen.add(key)
        parts.append({"title": title, "price": price, "link": url})

    return parts


def fetch_ebay_html(url):
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        response = None
        try:
            response = requests.get(url, headers=EBAY_HEADERS, timeout=15)
            logger.info(
                "Fetched eBay URL %s (attempt %d/%d) with status %s",
                url,
                attempt,
                max_attempts,
                response.status_code,
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            status_code = response.status_code if response is not None else "no response"
            logger.warning(
                "eBay fetch attempt %d/%d for %s failed with status %s: %s",
                attempt,
                max_attempts,
                url,
                status_code,
                e,
            )
            time.sleep(2)
    logger.error("Failed to fetch eBay URL %s after %d attempts", url, max_attempts)
    return None


def _looks_like_consent_or_captcha(html_snippet):
    lowered = html_snippet.lower()
    keywords = [
        "captcha",
        "consent",
        "robot",
        "verify you're human",
        "verify you are human",
        "are you a robot",
        "security measure",
        "botblock",
        "hcaptcha",
        "recaptcha",
        "enter the characters",
    ]
    return any(keyword in lowered for keyword in keywords)


def parse_ebay_response(html, url=None):
    soup = BeautifulSoup(html, "html.parser")
    parts = extract_items_from_jsonld(soup)
    if not parts:
        parts = extract_items_from_html(soup)
    if not parts:
        snippet = re.sub(r"\s+", " ", html)[:500]
        consent_captcha = _looks_like_consent_or_captcha(snippet)
        logger.warning(
            "No parts parsed from eBay response for %s. Consent/CAPTCHA suspected: %s. Snippet: %s",
            url or "unknown URL",
            "yes" if consent_captcha else "no",
            snippet,
        )
    return parts


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

    search_url = build_ebay_search_url(model, year, max_price=50)
    print("\U0001F50D eBay search URL:", search_url)

    html = fetch_ebay_html(search_url)
    if html is None:
        return render_template_string("<p><strong>Failed to fetch data from eBay after 3 attempts.</strong></p>")

    parts = parse_ebay_response(html, url=search_url)
    print(f"Parsed {len(parts)} candidate items in eBay search Small.")

    part_list = [part for part in parts if part["price"] <= 50]

    if not part_list:
        return "<p>No results found under £50.</p>"

    part_list.sort(key=lambda x: x["price"], reverse=True)

    return render_parts_table(part_list)

@app.route('/ebay_medium_parts')
def ebay_medium_parts():
    model = request.args.get('model', '').strip()
    year = request.args.get('year', '').strip()
    if not model or not year:
        return "Model and year are required.", 400

    search_url = build_ebay_search_url(model, year, min_price=50, max_price=500)
    print("\U0001F50D eBay search URL:", search_url)

    html = fetch_ebay_html(search_url)
    if html is None:
        return render_template_string("<p><strong>Failed to fetch data from eBay after 3 attempts.</strong></p>")

    parts = parse_ebay_response(html, url=search_url)
    print(f"Parsed {len(parts)} candidate items in eBay search Medium.")

    part_list = [part for part in parts if part["price"] > 50 and part["price"] <= 500]

    if not part_list:
        return "<p>No results found between £50 and £500.</p>"

    part_list.sort(key=lambda x: x["price"], reverse=False)

    return render_parts_table(part_list)

@app.route('/ebay_large_parts')
def ebay_large_parts():
    model = request.args.get('model', '').strip()
    year = request.args.get('year', '').strip()
    if not model or not year:
        return "Model and year are required.", 400

    search_url = build_ebay_search_url(model, year, min_price=500, max_price=5000)
    print("\U0001F50D eBay search URL:", search_url)

    html = fetch_ebay_html(search_url)
    if html is None:
        return render_template_string("<p><strong>Failed to fetch data from eBay after 3 attempts.</strong></p>")

    parts = parse_ebay_response(html, url=search_url)
    print(f"Parsed {len(parts)} candidate items in eBay search Large.")

    part_list = [part for part in parts if part["price"] >= 500]

    if not part_list:
        return "<p>No results found over £500.</p>"

    part_list.sort(key=lambda x: x["price"], reverse=True)

    return render_parts_table(part_list)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')

