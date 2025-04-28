<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Part Sales Opportunity Finder</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap" rel="stylesheet">
    <style>
      body {
        background: url("{{ url_for('static', filename='background.jpg') }}") no-repeat center center fixed;
        background-size: cover;
        font-family: 'Montserrat', sans-serif;
        color: black;
      }
      h1, h2, label {
        color: #5c9c13;
      }
      .btn-primary, .btn-success {
        background-color: #5c9c13;
        border: none;
      }
      .btn-primary:hover, .btn-success:hover {
        background-color: #4a8010;
      }
      .form-control {
        background-color: #d6f5c1;
        color: #lalala;
        border: 1px solid #lalala;
      }
      .form-control:focus {
        border-color: #5c9c13;
        box-shadow: 0 0 5px #5c9c13;
        background-color: #d6f5c1;
        color: #lalala;
      }
      table {
        color: #f0f0f0;
        background-color: #111;
      }
      th, td {
        border-bottom: 1px solid #5c9c13;
      }
      #model-suggestions {
        background-color: #d6f5c1;
        color: #lalala;
        border: 1px solid #5c9c13;
      }
      .navbar {
        border-radius: 10px;
        margin-bottom: 20px;
      }
      .navbar-brand img {
        height: 40px;
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

      <!-- Navbar -->
      <nav class="navbar navbar-expand-lg navbar-dark" style="background-color: #5c9c13;">
        <div class="container-fluid">
          <a class="navbar-brand" href="#">
            <img src="{{ url_for('static', filename='logo-slg-strip.svg') }}" alt="Silverlake Logo">
          </a>
          <div class="d-flex">
            <a href="{{ url_for('logout') }}" class="btn btn-light">Logout</a>
          </div>
        </div>
      </nav>

      <h1 class="mb-4 text-center">Silverlake Part Sales Opportunity Finder</h1>

      <form method="post">
        <div class="row">
          <div class="col-md-6 mb-3">
            <label class="form-label">Model</label>
            <input type="text" name="model" class="form-control" required>
            <ul id="model-suggestions" class="list-group" style="display: none; position: absolute; z-index: 1000; max-height: 150px; overflow-y: auto;"></ul>
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
