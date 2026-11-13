/* global AbortController, document, fetch, location, setTimeout, window */

(function () {
  var configEl = document.getElementById('api-config');
  var apiUrl = configEl?.dataset.url ?? '';
  var wsSlug = configEl?.dataset.ws ?? '';
  var canWrite = document.querySelector('[data-can-write]')?.dataset.canWrite === 'true';

  var table = document.querySelector('.table-wrap');
  var rows = table ? Array.from(table.querySelectorAll('tbody tr')) : [];
  var countEl = document.getElementById('eu-count');
  var searchInput = document.getElementById('eu-search');
  var tierSelect = document.getElementById('eu-tier-filter');
  var newBtn = document.getElementById('invite-eu-btn');
  var newBtnEmpty = document.getElementById('invite-eu-empty');
  var dialog = document.getElementById('dlg-end-user');
  var cancelBtn = document.getElementById('btn-cancel-end-user');
  var form = document.getElementById('end-user-form');
  var submitBtn = document.getElementById('btn-submit-end-user');
  var errorEl = document.getElementById('end-user-form-error');
  var controller = new AbortController();
  var signal = controller.signal;
  var lastTrigger = null;

  var currentStatusFilter = 'all';
  var totalCount = rows.length;

  // --- Status filter pills ---

  var pills = document.querySelectorAll('.filter-pills .pill');
  pills.forEach(function (pill) {
    pill.addEventListener(
      'click',
      function () {
        pills.forEach(function (p) {
          p.classList.remove('pill-active');
          p.setAttribute('aria-pressed', 'false');
        });
        pill.classList.add('pill-active');
        pill.setAttribute('aria-pressed', 'true');
        currentStatusFilter = pill.dataset.filter;
        applyFilters();
      },
      { signal: signal },
    );
  });

  // --- Search ---

  if (searchInput) {
    searchInput.addEventListener(
      'input',
      function () {
        applyFilters();
      },
      { signal: signal },
    );
  }

  // --- Tier dropdown ---

  if (tierSelect) {
    tierSelect.addEventListener(
      'change',
      function () {
        applyFilters();
      },
      { signal: signal },
    );
  }

  // --- Create end user dialog ---

  function openDialog(trigger) {
    if (!canWrite) return;
    if (!dialog) return;
    lastTrigger = trigger;
    if (form) form.reset();
    hideError();
    dialog.showModal();
    form?.elements.namedItem('externalUserId')?.focus();
  }

  if (newBtn) {
    newBtn.addEventListener(
      'click',
      function () {
        openDialog(newBtn);
      },
      { signal: signal },
    );
  }
  if (newBtnEmpty) {
    newBtnEmpty.addEventListener(
      'click',
      function () {
        openDialog(newBtnEmpty);
      },
      { signal: signal },
    );
  }
  if (cancelBtn) {
    cancelBtn.addEventListener(
      'click',
      function () {
        closeDialog();
      },
      { signal: signal },
    );
  }
  if (dialog) {
    dialog.addEventListener('close', restoreFocus, { signal: signal });
  }

  if (form) {
    form.addEventListener(
      'submit',
      function (e) {
        e.preventDefault();
        if (!canWrite) return;

        var els = form.elements;
        var externalUserId = els.namedItem('externalUserId').value.trim();
        var displayName = els.namedItem('displayName').value.trim();
        var tierLabel = els.namedItem('tierLabel').value;

        if (!externalUserId) {
          showError('Enter the external user ID from your app.');
          return;
        }

        var query =
          'mutation CreateEndUser($input: CreateEndUserInput!) { createEndUser(input: $input) { success errors { field message } endUser { id externalUserId } } }';
        var headers = { 'Content-Type': 'application/json' };
        if (wsSlug) headers['X-Workspace-Slug'] = wsSlug;

        setSubmitting(true);
        hideError();

        fetch(apiUrl + '/graphql/', {
          method: 'POST',
          credentials: 'include',
          headers: headers,
          body: JSON.stringify({
            query: query,
            variables: {
              input: {
                externalUserId: externalUserId,
                displayName: displayName,
                tierLabel: tierLabel,
              },
            },
          }),
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (json) {
            if (json?.errors?.length) {
              showError(
                json.errors[0].message ||
                  "Couldn't create the end user. Check the fields and try again.",
              );
              return;
            }

            var result = json?.data?.createEndUser;
            if (result?.success) {
              dialog?.close();
              if (window.msToast) window.msToast.success('End user created.');
              setTimeout(function () {
                location.reload();
              }, 300);
              return;
            }

            var msg =
              result?.errors
                ?.map(function (error) {
                  return error.message;
                })
                .join(', ') || "Couldn't create the end user. Check the fields and try again.";
            showError(msg);
          })
          .catch(function () {
            showError('Something went wrong. Check your connection and try again.');
          })
          .finally(function () {
            setSubmitting(false);
          });
      },
      { signal: signal },
    );
  }

  window.addEventListener(
    'pagehide',
    function () {
      controller.abort();
    },
    { once: true },
  );

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
      countEl.textContent = 'Showing ' + shown + ' of ' + totalCount + ' end users';
    }
  }

  function setSubmitting(isSubmitting) {
    if (!submitBtn) return;
    submitBtn.disabled = isSubmitting;
    submitBtn.setAttribute('aria-busy', isSubmitting ? 'true' : 'false');
    submitBtn.textContent = isSubmitting ? 'Creating...' : 'Create end user';
  }

  function closeDialog() {
    if (dialog?.open) dialog.close();
  }

  function restoreFocus() {
    if (lastTrigger && document.contains(lastTrigger)) {
      lastTrigger.focus();
    }
    lastTrigger = null;
  }

  function showError(msg) {
    if (!errorEl) return;
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
  }

  function hideError() {
    if (errorEl) errorEl.classList.add('hidden');
  }
})();
