/* global document, window, fetch, setInterval, clearInterval */

(function () {
  var root = document.querySelector('[data-run-live]');
  if (!root) return;

  var runUid = root.dataset.runUid;
  var status = (root.dataset.status || '').toUpperCase();
  var eventCount = parseInt(root.dataset.eventCount || '0', 10);
  var lastCallbackAt = root.dataset.lastCallbackAt || '';
  var stampEl = document.querySelector('[data-last-updated]');

  var ACTIVE = ['QUEUED', 'RUNNING'];
  var POLL_MS = 5000;

  function timeAgo(iso) {
    if (!iso) return '';
    var diff = Date.now() - new Date(iso).getTime();
    var mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + ' min ago';
    var hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + 'h ago';
    return Math.floor(hrs / 24) + 'd ago';
  }

  function renderStamp() {
    if (!stampEl) return;
    stampEl.textContent = lastCallbackAt ? 'Last updated ' + timeAgo(lastCallbackAt) : '';
  }

  function isActive() {
    return ACTIVE.indexOf(status) !== -1;
  }

  var clockTimer = null;
  var pollTimer = null;

  function stop() {
    if (clockTimer) clearInterval(clockTimer);
    if (pollTimer) clearInterval(pollTimer);
  }

  function poll() {
    fetch('/api/runs/' + runUid + '.json', { credentials: 'include' })
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(function (state) {
        if (!state) return;
        var changed = state.eventCount !== eventCount || state.status.toUpperCase() !== status;
        status = state.status.toUpperCase();
        eventCount = state.eventCount;
        lastCallbackAt = state.lastCallbackAt || lastCallbackAt;
        renderStamp();
        if (changed) {
          // New events or a status transition: reload to re-render the
          // server-side timeline and sidebar with the projected state.
          stop();
          window.location.reload();
        } else if (!isActive()) {
          stop();
        }
      })
      .catch(function () {
        /* transient — keep polling */
      });
  }

  renderStamp();
  if (isActive()) {
    clockTimer = setInterval(renderStamp, 1000);
    pollTimer = setInterval(poll, POLL_MS);
  }
})();
