/* global document */

(function () {
  var table = document.querySelector('.table-wrap');
  var rows = table ? Array.from(table.querySelectorAll('tbody tr')) : [];
  var countEl = document.getElementById('agents-count');
  var searchInput = document.getElementById('agents-search');
  var tierSelect = document.getElementById('agents-tier-filter');

  var currentStatusFilter = 'all';
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
      currentStatusFilter = pill.dataset.filter;
      applyFilters();
    });
  });

  if (searchInput) {
    searchInput.addEventListener('input', function () {
      applyFilters();
    });
  }

  if (tierSelect) {
    tierSelect.addEventListener('change', function () {
      applyFilters();
    });
  }

  function applyFilters() {
    var query = (searchInput?.value ?? '').toLowerCase().trim();
    var tierFilter = tierSelect?.value ?? 'all';
    var shown = 0;

    rows.forEach(function (row) {
      var name = (row.dataset.name ?? '').toLowerCase();
      var tier = (row.dataset.tier ?? '').toLowerCase();
      var isActive = row.dataset.active;

      var matchesStatus =
        currentStatusFilter === 'all' ||
        (currentStatusFilter === 'active' && isActive === 'true') ||
        (currentStatusFilter === 'inactive' && isActive === 'false');

      var matchesTier = tierFilter === 'all' || tier === tierFilter;

      var matchesSearch = !query || name.includes(query);

      if (matchesStatus && matchesTier && matchesSearch) {
        row.style.display = '';
        shown++;
      } else {
        row.style.display = 'none';
      }
    });

    if (countEl) {
      countEl.textContent = 'Showing ' + shown + ' of ' + totalCount + ' agents';
    }
  }
})();
