/* global document */

(function () {
  var table = document.querySelector('.table-wrap');
  var rows = table ? Array.from(table.querySelectorAll('tbody tr')) : [];
  var countEl = document.getElementById('runs-count');
  var searchInput = document.getElementById('runs-search');

  var currentFilter = 'all';
  var totalCount = rows.length;

  var pills = document.querySelectorAll('.filter-pills .pill');
  pills.forEach(function (pill) {
    pill.addEventListener('click', function () {
      pills.forEach(function (p) {
        p.classList.remove('pill-active');
        p.setAttribute('aria-checked', 'false');
      });
      pill.classList.add('pill-active');
      pill.setAttribute('aria-checked', 'true');
      currentFilter = pill.dataset.filter;
      applyFilters();
    });
  });

  if (searchInput) {
    searchInput.addEventListener('input', function () {
      applyFilters();
    });
  }

  function applyFilters() {
    var query = (searchInput?.value ?? '').toLowerCase().trim();
    var shown = 0;

    rows.forEach(function (row) {
      var status = row.dataset.status ?? '';
      var searchText = row.dataset.search ?? '';

      var matchesStatus = currentFilter === 'all' || status === currentFilter;
      var matchesSearch = !query || searchText.includes(query);

      if (matchesStatus && matchesSearch) {
        row.style.display = '';
        shown++;
      } else {
        row.style.display = 'none';
      }
    });

    if (countEl) {
      countEl.textContent = 'Showing ' + shown + ' of ' + totalCount + ' runs';
    }
  }
})();
