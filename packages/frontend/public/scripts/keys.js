/* global document, fetch, location, navigator, setTimeout */

(function () {
  var configEl = document.getElementById('api-config');
  var apiUrl = configEl?.dataset.url ?? '';
  var wsSlug = configEl?.dataset.ws ?? '';

  var dlgCreate = document.getElementById('dlg-create');
  var dlgSecret = document.getElementById('dlg-secret');
  var dlgRevoke = document.getElementById('dlg-revoke');

  dlgSecret?.addEventListener('cancel', function (event) {
    event.preventDefault();
  });

  function openCreate() {
    dlgCreate?.showModal();
  }
  document.getElementById('btn-open-create')?.addEventListener('click', openCreate);
  document.getElementById('btn-open-create-empty')?.addEventListener('click', openCreate);
  document.getElementById('btn-cancel-create')?.addEventListener('click', function () {
    dlgCreate?.close();
  });

  document.getElementById('form-create')?.addEventListener('submit', async function (e) {
    e.preventDefault();
    var form = e.target;
    var errEl = document.getElementById('create-error');
    var submitBtn = document.getElementById('btn-submit-create');
    errEl.classList.add('hidden');

    var name = form.elements.namedItem('name').value.trim();
    var checked = form.querySelectorAll('input[name="scopes"]:checked');
    var scopes = Array.from(checked).map(function (cb) {
      return cb.value;
    });
    var expiry = form.elements.namedItem('expiresAt').value;

    if (!name) {
      errEl.textContent = 'Name is required.';
      errEl.classList.remove('hidden');
      return;
    }
    if (scopes.length === 0) {
      errEl.textContent = 'Select at least one scope.';
      errEl.classList.remove('hidden');
      return;
    }

    var input = { name: name, scopes: scopes };
    if (expiry) input.expiresAt = new Date(expiry).toISOString();

    submitBtn.disabled = true;
    submitBtn.textContent = 'Creating...';

    try {
      var res = await fetch(apiUrl + '/graphql/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Workspace-Slug': wsSlug },
        credentials: 'include',
        body: JSON.stringify({
          query:
            'mutation CreateAPIKey($input: CreateAPIKeyInput!) { createApiKey(input: $input) { success errors { code field message } apiKey { id name keyPrefix scopes isActive createdAt } plaintextSecret } }',
          variables: { input: input },
        }),
      });
      var json = await res.json();
      if (json.errors?.[0]?.message) {
        errEl.textContent = json.errors[0].message;
        errEl.classList.remove('hidden');
        return;
      }
      var result = json.data?.createApiKey;

      if (!result?.success) {
        var msg =
          result?.errors?.[0]?.message ?? "Couldn't create the key. Check the name and try again.";
        errEl.textContent = msg;
        errEl.classList.remove('hidden');
        return;
      }

      dlgCreate.close();
      form.reset();

      document.getElementById('secret-value').textContent = result.plaintextSecret;
      document.getElementById('secret-copied').classList.add('hidden');
      dlgSecret?.showModal();
    } catch {
      errEl.textContent = 'Something went wrong. Check your connection and try again.';
      errEl.classList.remove('hidden');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Create key';
    }
  });

  document.querySelector('.btn-copy-secret')?.addEventListener('click', async function () {
    var text = document.getElementById('secret-value')?.textContent ?? '';
    try {
      await navigator.clipboard.writeText(text);
      document.getElementById('secret-copied')?.classList.remove('hidden');
    } catch {
      /* clipboard denied */
    }
  });

  document.getElementById('btn-close-secret')?.addEventListener('click', function () {
    dlgSecret?.close();
    location.reload();
  });

  document.querySelectorAll('.btn-revoke').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.getElementById('revoke-key-id').value = btn.dataset.keyId;
      document.getElementById('revoke-key-name').textContent = btn.dataset.keyName;
      document.getElementById('revoke-key-prefix').textContent = btn.dataset.keyPrefix + '...';
      document.getElementById('revoke-error').classList.add('hidden');
      document.getElementById('revoke-reason').value = '';
      dlgRevoke?.showModal();
    });
  });

  document.getElementById('btn-cancel-revoke')?.addEventListener('click', function () {
    dlgRevoke?.close();
  });

  document.getElementById('form-revoke')?.addEventListener('submit', async function (e) {
    e.preventDefault();
    var errEl = document.getElementById('revoke-error');
    var submitBtn = e.target.querySelector('button[type="submit"]');
    errEl.classList.add('hidden');

    var id = document.getElementById('revoke-key-id').value;
    var reason = document.getElementById('revoke-reason').value.trim();

    submitBtn.disabled = true;
    submitBtn.textContent = 'Revoking...';

    try {
      var res = await fetch(apiUrl + '/graphql/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Workspace-Slug': wsSlug },
        credentials: 'include',
        body: JSON.stringify({
          query:
            'mutation RevokeAPIKey($input: RevokeAPIKeyInput!) { revokeApiKey(input: $input) { success errors { code field message } apiKey { id isActive } } }',
          variables: { input: { id: id, reason: reason } },
        }),
      });
      var json = await res.json();
      if (json.errors?.[0]?.message) {
        errEl.textContent = json.errors[0].message;
        errEl.classList.remove('hidden');
        return;
      }
      var result = json.data?.revokeApiKey;

      if (!result?.success) {
        var msg = result?.errors?.[0]?.message ?? "Couldn't revoke the key. Try again.";
        errEl.textContent = msg;
        errEl.classList.remove('hidden');
        return;
      }

      dlgRevoke.close();
      location.reload();
    } catch {
      errEl.textContent = 'Something went wrong. Check your connection and try again.';
      errEl.classList.remove('hidden');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Revoke';
    }
  });

  document.querySelectorAll('.btn-copy').forEach(function (btn) {
    btn.addEventListener('click', async function () {
      var text = btn.dataset.copy;
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        var icon = btn.querySelector('span');
        if (icon) {
          var original = icon.innerHTML;
          icon.innerHTML =
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
          setTimeout(function () {
            icon.innerHTML = original;
          }, 1200);
        }
      } catch {
        /* clipboard denied */
      }
    });
  });
})();
