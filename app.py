html_template = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Silverlake Part Sales Opportunity Finder</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">

    <!-- Custom Silverlake Styles -->
    <style>
      body {
        background: linear-gradient(to bottom, #0b0c10, #1f2833);
        color: #ffffff;
        font-family: 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        min-height: 100vh;
        padding-top: 20px;
      }

      h1, h2, h3, label {
        color: #66fcf1;
      }

      .btn-primary {
        background-color: #45a29e;
        border-color: #45a29e;
      }

      .btn-primary:hover {
        background-color: #66fcf1;
        border-color: #66fcf1;
        color: #0b0c10;
      }

      .btn-success {
        background-color: #66fcf1;
        border-color: #66fcf1;
        color: #0b0c10;
      }

      .table {
        background-color: #1f2833;
        color: #ffffff;
      }

      .table th, .table td {
        border-color: #45a29e;
      }

      .list-group-item {
        background-color: #1f2833;
        color: #ffffff;
        border: 1px solid #45a29e;
      }

      #logo {
        display: block;
        margin: 0 auto 20px auto;
        max-width: 300px;
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
      
      <!-- Logo -->
      <img id="logo" src="/static/logo-slg-strip.svg" alt="Silverlake Logo">

      <h1 class="text-center mb-4">Silverlake Part Sales Opportunity Finder</h1>

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

      {% if model_input %}
        <h2 class="mt-5 text-center">Results for: {{ model_input }} {{ year_input }} {% if engine_input %} - {{ engine_input }} {% endif %}</h2>
      {% endif %}

      {% if parts %}
      <table class="table table-striped mt-4">
        <thead><tr>
          <th>Part</th><th>Start Year</th><th>End Year</th><th>Description</th><th>Price</th><th>Parts in Stock</th><th>Backorders</th><th>Parts Sold</th><th>Not Found 180 days</th><th>Potential Profit</th><th>Sales Speed</th><th>Opportunity Score</th>
        </tr></thead>
        <tbody>
        {% for row in parts %}
          <tr>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>{{ row['Part'] }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>{{ row['IC Start Year'] }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>{{ row['IC End Year'] }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>{{ row['IC Description'] }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>£{{ "{:.2f}".format(row['B Price']) }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>{{ row['Parts in Stock'] }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>{{ row['Backorders'] }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>{{ row['Parts Sold All'] }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>{{ row['Not Found 180 days'] }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>£{{ "{:.2f}".format(row['Potential_Profit']) }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>{{ "{:.2f}".format(row['Sales_Speed']) }}</td>
            <td {% if row['Backorders'] > 0 %} style="color: #66fcf1;" {% endif %}>£{{ "{:.2f}".format(row['Opportunity_Score']) }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      {% endif %}
    </div>
  </body>
</html>
"""
