from flask import Flask, request, render_template_string, send_file, redirect, url_for, session
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta

# Load your dataset
file_path = 'WebFleet.csv'
df = pd.read_csv(file_path)

# Flask App
app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here'  # Needed for session management!

# Define login credentials
USERS = {
    'admin': 'Silverlake1!',
    'nacho': 'Silverlake1!'
}

# Global variable to hold last search result and search input
last_search_result = None
search_details = None

# Login page template
login_template = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Login</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap" rel="stylesheet"> <!-- Montserrat font -->
  <style>
    body {
      background: url("{{ url_for('static', filename='background.jpg') }}") no-repeat center center fixed;
      background-size: cover;
      color: black;
      font-family: 'Montserrat', sans-serif;
    }
    .form-control {
      background-color: #1a1a1a;
      color: #f0f0f0;
    }
    .btn-primary {
      background-color: #5c9c13;
      border: none;
    }
  </style>
</head>
<body class="p-4">
<div class="container">
  <h1 class="mb-4 text-center">Login</h1>
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

# HTML Template
html_template = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Part Sales Opportunity Finder</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap" rel="stylesheet"> <!-- Montserrat font -->
    <style>
      body {
        background: url("{{ url_for('static', filename='background.jpg') }}") no-repeat center center fixed;
        background-size: cover;
        font-family: 'Montserrat', sans-serif;
        color: black;  /* Set text color to black */
      }
      h1, h2, label {
        color: #5c9c13;
      }
      .btn-primary, .btn-success {
        background-color: #5c9c13;
        border: none;
      }
      .btn-primary:hover, .btn-success:hover {
        background-color: #5c9c13;
      }
      .form-control {
        background-color: #f08989;
        color: #f0f0f0;
        border: 1px solid #333;
      }
      .form-control:focus {
        border-color: #5c9c13;
        box-shadow: 0 0 5px #5c9c13;
        background-color: #1a1a1a;
        color: #fff;
      }
      table {
        color: #f0f0f0;
        background-color: #111;
      }
      th, td {
        border-bottom: 1px solid #5c9c13;
      }
      #model-suggestions {
        background-color: #1a1a1a;
        color: #f0f0f0;
        border: 1px solid #5c9c13;
      }
      .logo {
        text-align: center;
        margin-bottom: 20px;
      }
      .logo img {
        width: 300px;
        max-width: 100%;
        height: auto;
      }
    </style>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script type="text/javascript">
      $(document).ready(function() {
        $('input[name="model"]').on('input', function() {
          var query = $(this).val().trim();
          if (query.length > 0) {
            $.ajax({
              url: '/autocomplete_model',
              method: 'GET',
              data: { 'query': query },
              success: function(response) {
                var suggestions = response.models;
                var suggestionList = $('#model-suggestions');
                suggestionList.empty();
                suggestions.forEach(function(model) {
                  suggestionList.append('<li class="list-group-item">' + model + '</li>');
                });
                suggestionList.show();
              }
            });
          } else {
            $('#model-suggestions').hide();
          }
        });

        $('#model-suggestions').on('click', 'li', function() {
          $('input[name="model"]').val($(this).text());
          $('#model-suggestions').hide();
        });

        $(document).click(function(event) {
          if (!$(event.target).closest('#model-suggestions').length && !$(event.target).closest('input[name="model"]').length) {
            $('#model-suggestions').hide();
          }
        });
      });
    </script>
  </head>
  <body class="p-4">
    <div class="container">
      <div class="logo">
        <img src="{{ url_for('static', filename='logo-slg-strip.svg') }}" alt="Silverlake Logo">
      </div>
      <h1 class="mb-4 text-center">Silverlake Part Sales Opportunity Finder</h1>
      <form method="post">
        <div class="row">
          <div class="col-md-6 mb-3">
            <label class="form-label">Model</label>
            <input type="text" name="model" class="form-control" required>
            <ul id="model-suggestions" class="list-group" style="display: none; position: absolute; z-index: 1000; border: 1px solid #ddd; max-height: 150px; overflow-y: auto;"></ul>
          </div>
          <div class="col-md-2 mb-3">
            <label class="form-label">Year</label>
            <input type="number" name="year" class="form-control" required>
          </div>
          <div class="col-md-4 mb-3">
            <label class="form-label">Engine Code (Optional)</label>
            <input type="text" name="engine_code" class="form-control">
          </div>
        </div>
        <div class="row">
          <div class="col-md-6 mb-3">
            <label class="form-label">Minimum Price (£)</label>
            <input type="number" name="min_price" class="form-control" step="0.01">
          </div>
          <div class="col-md-6 mb-3">
            <label class="form-label">Minimum Opportunity Score (£)</label>
            <input type="number" name="min_opportunity" class="form-control" step="0.01">
          </div>
        </div>
        <button type="submit" class="btn btn-primary">Search</button>
        {% if parts %}
          <a href="/download" class="btn btn-success ms-2">Download Excel</a>
        {% endif %}
      </form>

      {% if search_details %}
      <h2 class="mt-5">Top Parts for {{ search_details.model }} (Year {{ search_details.year }}) {% if search_details.engine_code %} Engine: {{ search_details.engine_code }} {% endif %}</h2>
      {% endif %}

      {% if parts %}
      <table class="table table-striped mt-3">
        <thead><tr>
          <th>Part</th><th>Start Year</th><th>End Year</th><th>Description</th><th>Price</th><th>Parts in Stock</th><th>Backorders</th><th>Parts Sold</th><th>Not Found 180 days</th><th>Potential Profit</th><th>Sales Speed</th><th>Opportunity Score</th>
        </tr></thead>
        <tbody>
        {% for row in parts %}
          <tr>
            <td {% if row['Backorders'] > 0 %} style="color: #5c9c13;" {% endif %}>{{ row['Part'] }}</td>
            <td>{{ row['IC Start Year'] }}</td>
            <td>{{ row['IC End Year'] }}</td>
            <td>{{ row['IC Description'] }}</td>
            <td>£{{ "{:.2f}".format(row['B Price']) }}</td>
            <td>{{ row['Parts in Stock'] }}</td>
            <td>{{ row['Backorders'] }}</td>
            <td>{{ row['Parts Sold All'] }}</td>
            <td>{{ row['Not Found 180 days'] }}</td>
            <td>£{{ "{:.2f}".format(row['Potential_Profit']) }}</td>
            <td>{{ "{:.2f}".format(row['Sales_Speed']) }}</td>
            <td>£{{ "{:.2f}".format(row['Opportunity_Score']) }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      {% endif %}
    </div>
  </body>
</html>
"""

# Login route
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
    return render_template_string(login_template, error=error)

# Logout route
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Protect all pages
@app.before_request
def require_login():
    allowed_routes = ['login', 'static', 'autocomplete_model']
    if request.endpoint not in allowed_routes and not session.get('logged_in'):
        return redirect(url_for('login'))

    # Check session timeout
    if session.get('logged_in'):
        login_time = session.get('login_time')
        if login_time:
            login_time = datetime.strptime(login_time, '%Y-%m-%d %H:%M:%S')
            if datetime.utcnow() - login_time > timedelta(hours=24):
                session.clear()
                return redirect(url_for('login'))

# Autocomplete model route
@app.route('/autocomplete_model', methods=['GET'])
def autocomplete_model():
    query = request.args.get('query', '')
    if query:
        filtered_models = df['Model'].dropna().unique()
        matches = [model for model in filtered_models if query.lower() in model.lower()]
        return {'models': matches}
    return {'models': []}

# Main route
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

            parts = filtered[['Part', 'IC Start Year', 'IC End Year', 'IC Description', 'B Price', 'Parts in Stock', 'Backorders',
                              'Parts Sold All', 'Not Found 180 days', 'Potential_Profit', 'Sales_Speed', 'Opportunity_Score']]
            parts = parts.sort_values(by=['Backorders', 'Opportunity_Score'], ascending=False).head(50)
            last_search_result = parts
            search_details = {'model': model, 'year': year, 'engine_code': engine_code}
            parts = parts.to_dict('records')

    return render_template_string(html_template, parts=parts, search_details=search_details)

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
