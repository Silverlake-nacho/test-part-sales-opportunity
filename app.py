from flask import Flask, request, render_template, send_file, redirect, url_for, session, jsonify
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build

import requests
from bs4 import BeautifulSoup
from flask import render_template_string
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here'

# Load dataset
file_path = 'WebFleet.csv'
df = pd.read_csv(file_path)

# User credentials
USERS = {
    'admin': 'Silverlake1!',
    'nacho': 'Silverlake1!'
}

last_search_result = None
search_details = None

def get_matching_google_sheet_rows(engine_code):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key('1Xw-gCRHSCOIOZXiMPGW4Smq9UXdQRDefvQDW-GO4IXY').sheet1
        data = sheet.get_all_records()
        df_sheet = pd.DataFrame(data)
        filtered = df_sheet[df_sheet['Engine Code'].astype(str).str.contains(engine_code, case=False, na=False)]
        return filtered.to_dict(orient='records')
    except Exception as e:
        print("Error accessing Google Sheets:", e)
        return []

@app.route('/lookup', methods=['POST'])
def lookup_registration():
    try:
        reg = request.json.get('registration', '').replace(" ", "")
        if not reg:
            return {'error': 'No registration provided'}, 400

        DVLA_API_URL = f"https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"
        headers = {
            "x-api-key": "G7jQjk2Cnv2LDMEZiBp0l1XXwfBrhHlS3b6qLYqY",  # ⬅️ Replace with your DVLA API key
            "Content-Type": "application/json"
        }
        payload = {"registrationNumber": reg}

        response = requests.post(DVLA_API_URL, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        return {
            'model': data.get('make', ''),
            'year': int(data.get('yearOfManufacture', 0)),
            'engine_code': data.get('engineNumber', ''),
            'all_data': data
        }
    except Exception as e:
        print("DVLA API error:", e)
        return {'error': 'Failed to fetch vehicle details'}, 500

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
    allowed_routes = ['login', 'static', 'autocomplete_model', 'lookup_registration', 'lookup']
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
            (df['Model'].str.contains(model, case=False, na=False)) &
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
    model = request.args.get('model', '').strip()
    year = request.args.get('year', '').strip()
    if not model or not year:
        return "Model and year are required.", 400

    query = f"{model} {year} used car parts"
    search_url = (
        "https://www.ebay.co.uk/sch/i.html?_nkw=" + query.replace(" ", "+") +
        "&_sop=12&_udhi=20&LH_ItemCondition=3000&LH_Complete=1&LH_Sold=1"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        return f"Failed to fetch data from eBay: {str(e)}", 500

    soup = BeautifulSoup(response.text, 'html.parser')
    items = soup.select('.s-item')

    part_data = defaultdict(lambda: {"price": "", "link": "", "count": 0})

    for item in items:
        title_tag = item.select_one('.s-item__title')
        price_tag = item.select_one('.s-item__price')
        link_tag = item.select_one('.s-item__link')

        if not title_tag or not price_tag or not link_tag:
            continue

        title = title_tag.get_text(strip=True)
        price_text = price_tag.get_text(strip=True).replace("£", "").split()[0]
        link = link_tag.get("href")

        try:
            price = float(price_text)
        except ValueError:
            continue

        if price <= 20:
            if title not in part_data:
                part_data[title]["price"] = f"£{price:.2f}"
                part_data[title]["link"] = link
            part_data[title]["count"] += 1

    if not part_data:
        return "<p>No results found under £20.</p>"

    html = "<table class='table table-striped'><thead><tr><th>Title</th><th>Price</th><th>Link</th><th>Count</th></tr></thead><tbody>"
    for title, data in part_data.items():
        html += f"<tr><td>{title}</td><td>{data['price']}</td><td><a href='{data['link']}' target='_blank'>View</a></td><td>{data['count']}</td></tr>"
    html += "</tbody></table>"

    return render_template_string(html)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
