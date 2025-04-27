from flask import Flask, request, render_template_string, send_file, redirect, url_for, session
import pandas as pd
from io import BytesIO

# Load your dataset
file_path = 'WebFleet.csv'
df = pd.read_csv(file_path)

# Flask App
app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here'  # Needed for session management!

# Define your login credentials
USERNAME = 'admin'
PASSWORD = 'Silverlake1!'
USERNAME = 'nacho'
PASSWORD = 'Silverlake1!'

# Global variable to hold last search result
last_search_result = None

# Login page template
login_template = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Login</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="p-4">
<div class="container">
  <h1 class="mb-4">Login</h1>
  <form method="post">
    <div class="mb-3">
      <label class="form-label">Username</label>
      <input type="text" name="username" class="form-control" required>
    </div>
    <div class="mb-3">
      <label class="form-label">Password</label>
      <input type="password" name="password" class="form-control" required>
    </div>
    <button type="submit" class="btn btn-primary">Login</button>
    {% if error %}
      <div class="alert alert-danger mt-3">{{ error }}</div>
    {% endif %}
  </form>
</div>
</body>
</html>
"""

# Your current HTML template
html_template = """ 
(your whole big form, same as before) 
"""  # [✏️ keep your existing html_template here]

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == USERNAME and password == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = 'Invalid Credentials. Please try again.'
    return render_template_string(login_template, error=error)

# Logout route (optional)
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Protect all pages
@app.before_request
def require_login():
    allowed_routes = ['login', 'static']
    if request.endpoint not in allowed_routes and not session.get('logged_in'):
        return redirect(url_for('login'))

# Main route
@app.route('/', methods=['GET', 'POST'])
def index():
    global last_search_result
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

        if engine_code:
            filtered = filtered[filtered['IC Description'].str.contains(engine_code, case=False, na=False)]

        if not filtered.empty:
            filtered['Potential_Profit'] = (filtered['Backorders'] + filtered['Not Found 180 days']) * filtered['B Price']
            filtered['Sales_Speed'] = filtered['Parts Sold All'] / (filtered['Parts in Stock'] + 1)
            filtered['Opportunity_Score'] = filtered['Potential_Profit'] * filtered['Sales_Speed']

            if min_price:
                filtered = filtered[filtered['B Price'] >= float(min_price)]
            if min_opportunity:
                filtered = filtered[filtered['Opportunity_Score'] >= float(min_opportunity)]

            parts = filtered[['Part', 'IC Description', 'B Price', 'Parts in Stock',
                              'Parts Sold All', 'Potential_Profit', 'Sales_Speed', 'Opportunity_Score']]
            parts = parts.sort_values(by='Opportunity_Score', ascending=False).head(50)
            last_search_result = parts
            parts = parts.to_dict('records')

    return render_template_string(html_template, parts=parts)

# Download route
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
