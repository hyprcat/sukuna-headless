/* global document, fetch, window */

(function () {
  'use strict';

  var cfg = document.getElementById('api-config');
  if (!cfg) return;
  var apiUrl = cfg.dataset.url || '';
  var wsSlug = cfg.dataset.ws || '';

  // --- Preset button selection ---
  var presetBtns = document.querySelectorAll('.modal-preset-btn');
  var customInput = document.getElementById('modal-custom-amount');
  var selectedAmount = null;

  presetBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      presetBtns.forEach(function (b) {
        b.classList.remove('selected');
      });
      btn.classList.add('selected');
      selectedAmount = parseFloat(btn.dataset.amount);
      if (customInput) customInput.value = '';
    });
  });

  if (customInput) {
    customInput.addEventListener('input', function () {
      presetBtns.forEach(function (b) {
        b.classList.remove('selected');
      });
      var val = parseFloat(customInput.value);
      selectedAmount = val > 0 ? val : null;
    });
  }

  // --- Dialog open/close ---
  var dialog = document.getElementById('topup-dialog');
  var trigger = document.getElementById('topup-trigger');
  var cancelBtn = document.getElementById('modal-cancel');
  var emptyTrigger = document.getElementById('topup-empty-cta');

  function openModal() {
    if (!dialog) return;
    dialog.classList.add('is-open');
    var firstPreset = dialog.querySelector('.modal-preset-btn');
    if (firstPreset) firstPreset.focus();
    dialog.scrollIntoView({ block: 'center' });
  }

  function closeModal() {
    if (!dialog) return;
    dialog.classList.remove('is-open');
    resetForm();
  }

  function resetForm() {
    presetBtns.forEach(function (b) {
      b.classList.remove('selected');
    });
    if (customInput) customInput.value = '';
    selectedAmount = null;
    var err = document.getElementById('modal-topup-error');
    if (err) err.hidden = true;
  }

  if (trigger) trigger.addEventListener('click', openModal);
  if (emptyTrigger) emptyTrigger.addEventListener('click', openModal);
  if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

  // --- Top-up submission ---
  var submitBtn = document.getElementById('modal-topup-submit');
  var errorEl = document.getElementById('modal-topup-error');

  if (submitBtn) {
    submitBtn.addEventListener('click', function () {
      var amount = selectedAmount;
      if (customInput && customInput.value) {
        amount = parseFloat(customInput.value);
      }
      submitTopup(amount, errorEl, submitBtn);
    });
  }

  function submitTopup(amount, errEl, btn) {
    if (errEl) errEl.hidden = true;

    if (!amount) {
      showError(errEl, 'Choose $20, $50, $100, or $500.');
      return;
    }
    if (![20, 50, 100, 500].includes(amount)) {
      showError(errEl, 'Choose $20, $50, $100, or $500 to continue.');
      return;
    }

    var idempotencyKey = 'topup_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);

    btn.disabled = true;
    btn.textContent = 'Processing…';

    var headers = { 'Content-Type': 'application/json' };
    if (wsSlug) headers['X-Workspace-Slug'] = wsSlug;

    fetch(apiUrl + '/graphql/', {
      method: 'POST',
      headers: headers,
      credentials: 'include',
      body: JSON.stringify({
        query:
          'mutation CreateTopup($input: CreateTopupInput!) { createTopup(input: $input) { success errors { field message code } topup { id amountUsd status } hostedCheckoutUrl } }',
        variables: {
          input: {
            amount: String(amount),
            idempotencyKey: idempotencyKey,
          },
        },
      }),
    })
      .then(function (res) {
        return res.json();
      })
      .then(function (json) {
        if (json.errors && json.errors.length) {
          showError(
            errEl,
            json.errors[0].message || 'Something went wrong. Check your connection and try again.',
          );
          btn.disabled = false;
          btn.textContent = 'Continue to payment';
          return;
        }
        var result = json.data && json.data.createTopup;
        if (!result || !result.success) {
          var msg =
            (result && result.errors && result.errors[0] && result.errors[0].message) ||
            'Something went wrong. Check your connection and try again.';
          showError(errEl, msg);
          btn.disabled = false;
          btn.textContent = 'Continue to payment';
          return;
        }

        if (result.hostedCheckoutUrl) {
          window.location.href = result.hostedCheckoutUrl;
        } else {
          showError(errEl, 'Something went wrong. Please try again.');
          btn.disabled = false;
          btn.textContent = 'Continue to payment';
        }
      })
      .catch(function () {
        showError(errEl, 'Something went wrong. Check your connection and try again.');
        btn.disabled = false;
        btn.textContent = 'Continue to payment';
      });
  }

  function showError(el, msg) {
    if (el) {
      el.textContent = msg;
      el.hidden = false;
    }
  }
})();
