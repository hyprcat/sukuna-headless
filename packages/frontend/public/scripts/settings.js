/* global document, fetch, setTimeout, window */

(function () {
  var configEl = document.getElementById('api-config');
  var apiUrl = configEl?.dataset.url ?? '';
  var wsSlug = configEl?.dataset.ws ?? '';

  document.getElementById('form-settings')?.addEventListener('submit', async function (e) {
    e.preventDefault();
    var form = e.target;
    var errEl = document.getElementById('settings-error');
    var okEl = document.getElementById('settings-success');
    var btn = document.getElementById('btn-save-settings');
    errEl.classList.add('hidden');
    okEl.classList.add('hidden');

    var name = form.elements.namedItem('name').value.trim();
    var billingEmail = form.elements.namedItem('billingEmail').value.trim();

    if (!name) {
      errEl.textContent = 'Workspace name is required.';
      errEl.classList.remove('hidden');
      return;
    }

    var input = { name: name, billingEmail: billingEmail };

    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
      var res = await fetch(apiUrl + '/graphql/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Workspace-Slug': wsSlug },
        credentials: 'include',
        body: JSON.stringify({
          query:
            'mutation UpdateWorkspace($input: UpdateWorkspaceInput!) { updateWorkspace(input: $input) { success errors { code field message } workspace { name billingEmail } } }',
          variables: { input: input },
        }),
      });
      var json = await res.json();
      var result = json.data?.updateWorkspace;

      if (!result?.success) {
        errEl.textContent =
          result?.errors?.[0]?.message ?? "Couldn't save your changes. Try again.";
        errEl.classList.remove('hidden');
        return;
      }

      okEl.textContent = 'Settings saved.';
      okEl.classList.remove('hidden');
      if (window.msToast) window.msToast.success('Settings saved.');
      setTimeout(function () {
        okEl.classList.add('hidden');
      }, 3000);
    } catch {
      errEl.textContent = 'Something went wrong. Check your connection and try again.';
      errEl.classList.remove('hidden');
      if (window.msToast)
        window.msToast.error('Something went wrong. Check your connection and try again.');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Save changes';
    }
  });
})();
