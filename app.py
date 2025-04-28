from flask import Flask, request, render_template, send_file, redirect, url_for, session
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta

# Load your dataset
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

# 👉 Correct Engine Code special filtering
if engine_code:
    def custom_filter(row):
        description = str(row['IC Description']).lower()
        if 'engine code' in description:
            return engine_code.lower() in description
        else:
            return True  # Keep rows without 'engine code' mention

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

    return render_template('index.html', parts=parts, search_details=search_details)

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
