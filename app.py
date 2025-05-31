from flask import Flask, request, render_template, send_file, redirect, url_for, session, render_template_string
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests
from bs4 import BeautifulSoup
from collections import defaultdict

# Load WebFleet data from Google Sheets
def load_webfleet_from_google_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        client = gspread.authorize(creds)

        sheet = client.open_by_key('1tsC3u68FbojBmdovaz_IQOtroA_dNRpT8v6qtSfBh48')
        worksheet = sheet.get_worksheet(0)  # First sheet
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        print("Error loading WebFleet Google Sheet:", e)
        return pd.DataFrame()

df = load_webfleet_from_google_sheet()

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
                cell_text = cell
                try:
                    bg_color = row_data[i]['values'][j].get('effectiveFormat', {}).get('backgroundColor', {})
                except (IndexError, KeyError):
                    bg_color = {}
                hex_color = rgb_to_hex(bg_color)
                key = headers[j]
                row_dict[key] = {'value': cell_text, 'bg': hex_color}
            if any(engine_code.lower() in str(c).lower() for c in row):
                rows.append(row_dict)

        return rows

    except Exception as e:
        print("Error accessing Google Sheets:", e)
        return []

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
    print(f"/autocomplete_model called with query: '{query}'")
    print(f"DataFrame columns: {df.columns.tolist()}")
    if query:
        if 'Model' not in df.columns:
            print("ERROR: 'Model' column not found in dataframe!")
            return {'models': []}

        filtered_models = df['Model'].dropna().unique()
        matches = [model for model in filtered_models if query.lower() in model.lower()]
        print(f"Matches found: {matches}")
        return {'models': matches}
    return {'models': []}
    
@app.route('/test_df')
def test_df():
    return f"DF shape: {df.shape}, columns: {df.columns.tolist()}"

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

        # Filter by model and year
        filtered = df[
            (df['Model'].str.lower() == model.lower()) &
            (df['IC Start Year'] <= year) &
            (df['IC End Year'] >= year)
        ]

        if not filtered.empty:
            filtered = filtered.copy()

            # Engine code filtering logic
            if engine_code:
                def custom_filter(row):
                    description = str(row['IC Description']).lower()
                    if 'engine code' in description:
                        return engine_code.lower() in description
                    return True  # keep rows that don't mention 'engine code'

                filtered = filtered[filtered.apply(custom_filter, axis=1)]

            # Convert numeric fields safely
            numeric_cols = ['Backorders', 'Not Found 180 days', 'B Price', 'Parts in Stock', 'Parts Sold All']
            for col in numeric_cols:
                filtered[col] = pd.to_numeric(filtered[col], errors='coerce').fillna(0)

            # Compute calculated fields
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

        # Lookup in Google Sheet
        if engine_code:
            google_sheet_matches = get_matching_google_sheet_rows(engine_code)

    return render_template('index.html', parts=parts, search_details=search_details, google_sheet_matches=google_sheet_matches)


@app.route('/download')
def download():
    global last_search_result
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if last_search_result is not None:
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            last_search_result.to_excel(writer, index=False, sheet_name='Parts')
        output.seek(0)
        return send_file(output, download_name="parts_opportunity.xlsx", as_attachment=True)
    return "No data to download", 400

@app.route('/ebay_small_parts')
def ebay_small_parts():
    import time, re
    model = request.args.get('model', '').strip()
    year = request.args.get('year', '').strip()
    if not model or not year:
        return "Model and year are required.", 400

    query = f"{model} {year} used car parts"
    search_url = (
        "https://www.ebay.co.uk/sch/i.html?_nkw=" + query.replace(" ", "+") +
        "&_sop=12&_udhi=50&LH_ItemCondition=3000&LH_Complete=1&LH_Sold=1"
    )
    print("🔍 Searching eBay:", search_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        for attempt in range(3):
            try:
                response = requests.get(search_url, headers=headers, timeout=10)
                response.raise_for_status()
                break
            except Exception as e:
                print(f"eBay fetch attempt {attempt + 1} failed: {e}")
                time.sleep(2)
        else:
            return render_template_string("<p><strong>Failed to fetch data from eBay after 3 attempts.</strong></p>")

        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.select('.s-item')

        part_list = []
        for item in items:
            title_tag = item.select_one('.s-item__title')
            price_tag = item.select_one('.s-item__price')
            link_tag = item.select_one('.s-item__link')

            if not title_tag or not price_tag or not link_tag:
                continue

            title = title_tag.get_text(strip=True)
            price_text = price_tag.get_text(strip=True)
            link = link_tag.get("href")

            match = re.search(r'(\d+(\.\d{1,2})?)', price_text.replace(",", ""))
            if not match:
                continue
            price = float(match.group(1))

            if price <= 50:
                part_list.append({
                    "title": title,
                    "price": price,
                    "link": link
                })

        if not part_list:
            return "<p>No results found under £50.</p>"

        part_list.sort(key=lambda x: x["price"], reverse=True)

        html = "<table class='table table-striped'><thead><tr><th>Title</th><th>Price</th><th>Link</th></tr></thead><tbody>"
        for part in part_list:
            html += f"<tr><td>{part['title']}</td><td>£{part['price']:.2f}</td><td><a href='{part['link']}' target='_blank'>View</a></td></tr>"
        html += "</tbody></table>"

        return render_template_string(html)

    except Exception as e:
        print("❌ Unexpected error in /ebay_small_parts:", e)
        return "<p><strong>Error loading data.</strong></p>"


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
