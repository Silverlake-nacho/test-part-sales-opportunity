from flask import Flask, request, render_template, send_file, redirect, url_for, session
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build

import requests
from bs4 import BeautifulSoup
from flask import request, render_template_string
from collections import defaultdict

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
    import time
    from flask import jsonify
    import logging
    model = request.args.get('model', '').strip()
    year = request.args.get('year', '').strip()
    if not model or not year:
        return jsonify({"error": "Model and year are required."}), 400

    query = f"{model} {year} used car parts"
    search_url = (
        "https://www.ebay.co.uk/sch/i.html?_nkw=" + query.replace(" ", "+") +
        "&_sop=12&_udhi=50000&LH_ItemCondition=3000&LH_Complete=1&LH_Sold=1"
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9"
    }

    response = None
    for attempt in range(2):
        try:
            print(f"Attempt {attempt + 1}: Fetching {search_url}")
            response = requests.get(search_url, headers=headers, timeout=8)
            response.raise_for_status()
            break
        except requests.exceptions.Timeout:
            print(f"eBay fetch attempt {attempt + 1} timed out")
        except Exception as e:
            print(f"eBay fetch attempt {attempt + 1} failed: {e}")
        time.sleep(1)

    if not response or response.status_code != 200:
        return jsonify({
            "under50": "<p><strong>eBay timed out or failed to respond.</strong></p>",
            "between50and500": "<p><strong>No data due to timeout or error.</strong></p>",
            "over500": "<p><strong>No data due to timeout or error.</strong></p>"
        }), 200

    soup = BeautifulSoup(response.text, 'html.parser')
    items = soup.select('.s-item')

    if len(items) > 50:
        items = items[:50]  # Limit number of items to prevent timeouts

    part_list = []

    for item in items:
        title_tag = item.select_one('.s-item__title')
        price_tag = item.select_one('.s-item__price')
        link_tag = item.select_one('.s-item__link')

        if not title_tag or not price_tag or not link_tag:
            continue

        title = title_tag.get_text(strip=True)
        price_text = price_tag.get_text(strip=True).replace("£", "").split()[0].replace(",", "")
        link = link_tag.get("href")

        try:
            price = float(price_text)
        except ValueError:
            continue

        part_list.append({"title": title, "price": price, "link": link})

    def table_html(parts):
        if not parts:
            return "<p>No results found.</p>"
        html = "<table class='table table-striped'><thead><tr><th>Title</th><th>Price</th><th>Link</th></tr></thead><tbody>"
        for part in parts:
            html += f"<tr><td>{part['title']}</td><td>£{part['price']:.2f}</td><td><a href='{part['link']}' target='_blank'>View</a></td></tr>"
        html += "</tbody></table>"
        return html

    under_50 = [p for p in part_list if p["price"] <= 50]
    between_50_500 = [p for p in part_list if 50 < p["price"] <= 500]
    over_500 = [p for p in part_list if 500 < p["price"] <= 1000]

    return jsonify({
        "under50": table_html(under_50),
        "between50and500": table_html(between_50_500),
        "over500": table_html(over_500)
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
