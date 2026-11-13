/* global document, fetch, location, setTimeout, window */

(function () {
  var configEl = document.getElementById('api-config');
  var apiUrl = configEl?.dataset.url ?? '';
  var wsSlug = configEl?.dataset.ws ?? '';
  var canWrite = document.querySelector('[data-can-write]')?.dataset.canWrite === 'true';

  var table = document.querySelector('.table-wrap');
  var rows = table ? Array.from(table.querySelectorAll('tbody tr')) : [];
  var countEl = document.getElementById('schedule-count');
  var searchInput = document.getElementById('schedule-search');

  var newBtn = document.getElementById('new-schedule-btn');
  var newBtnEmpty = document.getElementById('new-schedule-empty');
  var dialog = document.getElementById('dlg-schedule');
  var cancelBtn = document.getElementById('btn-cancel-schedule');
  var form = document.getElementById('schedule-form');
  var errorEl = document.getElementById('schedule-form-error');

  var currentFilter = 'all';
  var totalCount = rows.length;

  // --- Filter pills ---

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

  // --- Search ---

  if (searchInput) {
    searchInput.addEventListener('input', function () {
      applyFilters();
    });
  }

  function applyFilters() {
    var query = (searchInput?.value ?? '').toLowerCase().trim();
    var shown = 0;

    rows.forEach(function (row) {
      var name = (row.dataset.name ?? '').toLowerCase();
      var agent = (row.dataset.agent ?? '').toLowerCase();
      var desc = (row.dataset.description ?? '').toLowerCase();
      var status = (row.dataset.status ?? '').toLowerCase();

      var matchesFilter = currentFilter === 'all' || status === currentFilter;
      var matchesSearch =
        !query || name.includes(query) || agent.includes(query) || desc.includes(query);

      if (matchesFilter && matchesSearch) {
        row.style.display = '';
        shown++;
      } else {
        row.style.display = 'none';
      }
    });

    if (countEl) {
      countEl.textContent = 'Showing ' + shown + ' of ' + totalCount + ' schedules';
    }
  }

  // --- New schedule dialog ---

  function openDialog() {
    if (!canWrite) return;
    if (!dialog) return;
    if (form) form.reset();
    hideError();
    dialog.showModal();
  }

  if (newBtn) newBtn.addEventListener('click', openDialog);
  if (newBtnEmpty) newBtnEmpty.addEventListener('click', openDialog);
  if (cancelBtn)
    cancelBtn.addEventListener('click', function () {
      dialog?.close();
    });

  // --- Create schedule ---

  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!canWrite) return;
      var els = form.elements;

      var variables = {
        input: {
          name: els.name.value.trim(),
          description: els.description.value.trim(),
          agentId: els.agentId.value,
          targetEndUserId: els.endUserId.value,
          prompt: els.prompt.value.trim(),
          cronExpression: els.cronExpression.value.trim(),
          failureHandling: els.failureHandling.value,
        },
      };

      var query =
        'mutation CreateSchedule($input: CreateScheduleInput!) { createSchedule(input: $input) { success errors { field message } schedule { id name } } }';

      var headers = { 'Content-Type': 'application/json' };
      if (wsSlug) headers['X-Workspace-Slug'] = wsSlug;

      fetch(apiUrl + '/graphql/', {
        method: 'POST',
        credentials: 'include',
        headers: headers,
        body: JSON.stringify({ query: query, variables: variables }),
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (json) {
          if (json?.errors?.length) {
            showError(
              json.errors[0].message ||
                "Couldn't create the schedule. Check the fields and try again.",
            );
            return;
          }
          var result = json?.data?.createSchedule;
          if (result?.success) {
            dialog?.close();
            if (window.msToast) window.msToast.success('Schedule created.');
            setTimeout(function () {
              location.reload();
            }, 300);
          } else {
            var msg =
              result?.errors
                ?.map(function (e) {
                  return e.message;
                })
                .join(', ') || "Couldn't create the schedule. Check the fields and try again.";
            showError(msg);
          }
        })
        .catch(function () {
          showError('Something went wrong. Check your connection and try again.');
        });
    });
  }

  // --- Error helpers ---

  function showError(msg) {
    if (!errorEl) return;
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
  }

  function hideError() {
    if (errorEl) errorEl.classList.add('hidden');
  }
})();
