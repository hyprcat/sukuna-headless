/* global document, window, setTimeout, clearTimeout, requestAnimationFrame */

(function () {
  'use strict';

  function getContainer() {
    var container = document.getElementById('ms-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'ms-toast-container';
      container.className = 'toast-container';
      container.setAttribute('aria-live', 'polite');
      container.setAttribute('aria-atomic', 'false');
      document.body.appendChild(container);
    }
    return container;
  }

  function show(message, variant, duration) {
    var el = document.createElement('div');
    el.className = 'toast toast-' + variant;
    el.setAttribute('role', variant === 'error' ? 'alert' : 'status');
    el.textContent = message;

    var c = getContainer();
    c.appendChild(el);

    requestAnimationFrame(function () {
      el.classList.add('toast-visible');
    });

    var timer = setTimeout(function () {
      dismiss(el);
    }, duration || 3500);

    el.addEventListener('click', function () {
      clearTimeout(timer);
      dismiss(el);
    });
  }

  function dismiss(el) {
    el.classList.remove('toast-visible');
    el.classList.add('toast-leaving');
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 200);
  }

  window.msToast = {
    success: function (msg, duration) {
      show(msg, 'success', duration);
    },
    error: function (msg, duration) {
      show(msg, 'error', duration);
    },
    info: function (msg, duration) {
      show(msg, 'info', duration);
    },
  };
})();
