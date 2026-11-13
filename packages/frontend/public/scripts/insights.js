/* global AbortController, document, fetch, console, window */

(function () {
  var configEl = document.getElementById('api-config');
  var apiUrl = configEl?.dataset.url ?? '';
  var wsSlug = configEl?.dataset.ws ?? '';

  var feed = document.getElementById('insight-feed');
  var countEl = document.getElementById('insight-count');
  var pills = document.querySelectorAll('[data-category]');

  if (!feed) return;

  var controller = new AbortController();
  var signal = controller.signal;
  var items = Array.from(feed.querySelectorAll('.insight-feed-item'));
  var activeCategory = 'all';

  function applyFilter() {
    var visible = 0;
    items.forEach(function (item) {
      var cat = item.dataset.category;
      var show = activeCategory === 'all' || cat === activeCategory;
      item.hidden = !show;
      if (show) visible++;
    });
    if (countEl) {
      countEl.textContent = 'Showing ' + visible + ' insight' + (visible !== 1 ? 's' : '');
    }
  }

  pills.forEach(function (pill) {
    pill.addEventListener(
      'click',
      function () {
        pills.forEach(function (p) {
          p.classList.remove('pill-active');
          p.setAttribute('aria-checked', 'false');
        });
        pill.classList.add('pill-active');
        pill.setAttribute('aria-checked', 'true');
        activeCategory = pill.dataset.category;
        applyFilter();
      },
      { signal: signal },
    );
  });

  async function gqlMutate(query, variables) {
    var headers = { 'Content-Type': 'application/json' };
    if (wsSlug) headers['x-workspace-slug'] = wsSlug;
    try {
      var response = await fetch(apiUrl + '/graphql/', {
        method: 'POST',
        credentials: 'include',
        headers: headers,
        body: JSON.stringify({ query: query, variables: variables }),
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    } catch (err) {
      console.error('GraphQL mutation failed:', err);
      return null;
    }
  }

  function restoreItem(item) {
    item.style.opacity = '';
    item.style.pointerEvents = '';
  }

  function mutationError(res, key, fallback) {
    return res?.errors?.[0]?.message || res?.data?.[key]?.errors?.[0]?.message || fallback;
  }

  function confirmDismiss() {
    var confirm = window['msConfirm'];
    if (typeof confirm !== 'function') return Promise.resolve(true);
    return confirm({
      title: 'Dismiss insight',
      message:
        'This insight will be hidden from the feed. It can still be found in the dismissed filter.',
      confirmLabel: 'Dismiss',
      variant: 'danger',
    });
  }

  function toast(method, message) {
    var toastApi = window['msToast'];
    if (toastApi && typeof toastApi[method] === 'function') toastApi[method](message);
  }

  function setPinned(item, btn, pinned) {
    item.dataset.status = pinned ? 'pinned' : 'active';
    var meta = item.querySelector('.insight-meta');
    var existing = meta?.querySelector('.insight-pinned-badge');
    if (pinned && meta && !existing) {
      var badge = document.createElement('span');
      badge.className = 'insight-pinned-badge';
      badge.textContent = 'Pinned';
      var ts = meta.querySelector('.insight-timestamp');
      if (ts) ts.insertAdjacentElement('afterend', badge);
    }
    if (!pinned && existing) existing.remove();
    btn.remove();
  }

  feed.addEventListener('click', handleFeedClick, { signal: signal });
  window.addEventListener(
    'pagehide',
    function () {
      controller.abort();
    },
    { once: true, signal: signal },
  );

  async function handleFeedClick(e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;

    var action = btn.dataset.action;
    var insightId = btn.dataset.insightId;
    var item = btn.closest('.insight-feed-item');

    if (action === 'dismiss' && insightId) await dismissInsight(item, insightId);
    if (action === 'pin' && insightId) pinInsight(item, btn, insightId);
    if (action === 'unpin' && insightId) unpinInsight(item, btn, insightId);
  }

  async function dismissInsight(item, insightId) {
    if (!(await confirmDismiss())) return;
    item.style.opacity = '0.5';
    item.style.pointerEvents = 'none';
    gqlMutate(
      'mutation DismissInsight($id: ID!) { dismissInsight(id: $id) { success errors { code message } } }',
      { id: insightId },
    ).then(function (res) {
      if (res?.data?.dismissInsight?.success) {
        item.remove();
        items = items.filter(function (i) {
          return i !== item;
        });
        applyFilter();
        toast('success', 'Insight dismissed.');
      } else {
        restoreItem(item);
        toast('error', mutationError(res, 'dismissInsight', "Couldn't dismiss the insight."));
      }
    });
  }

  function pinInsight(item, btn, insightId) {
    gqlMutate(
      'mutation PinInsight($id: ID!) { pinInsight(id: $id) { success errors { code message } } }',
      { id: insightId },
    ).then(function (res) {
      if (res?.data?.pinInsight?.success) {
        setPinned(item, btn, true);
        toast('success', 'Insight pinned.');
      } else {
        toast('error', mutationError(res, 'pinInsight', "Couldn't pin the insight."));
      }
    });
  }

  function unpinInsight(item, btn, insightId) {
    gqlMutate(
      'mutation UnpinInsight($id: ID!) { unpinInsight(id: $id) { success errors { code message } } }',
      { id: insightId },
    ).then(function (res) {
      if (res?.data?.unpinInsight?.success) {
        setPinned(item, btn, false);
        toast('success', 'Insight unpinned.');
      } else {
        toast('error', mutationError(res, 'unpinInsight', "Couldn't unpin the insight."));
      }
    });
  }
})();
