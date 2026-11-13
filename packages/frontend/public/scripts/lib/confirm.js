/* global document, window */

(function () {
  'use strict';

  function buildDialog(options) {
    var dialog = document.createElement('dialog');
    dialog.className = 'confirm-dialog';
    dialog.setAttribute('aria-labelledby', 'confirm-title');
    dialog.setAttribute('aria-describedby', 'confirm-message');
    dialog.innerHTML =
      '<div class="confirm-body">' +
      '<h3 id="confirm-title" class="confirm-title"></h3>' +
      '<p id="confirm-message" class="confirm-message"></p>' +
      '</div>' +
      '<div class="confirm-actions">' +
      '<button id="confirm-cancel" type="button" class="btn btn-secondary"></button>' +
      '<button id="confirm-ok" type="button" class="btn"></button>' +
      '</div>';

    dialog.querySelector('#confirm-title').textContent = options.title || 'Are you sure?';
    dialog.querySelector('#confirm-message').textContent = options.message || '';

    var okBtn = dialog.querySelector('#confirm-ok');
    okBtn.textContent = options.confirmLabel || 'Confirm';
    okBtn.classList.add(options.variant === 'primary' ? 'btn-primary' : 'btn-danger');

    dialog.querySelector('#confirm-cancel').textContent = options.cancelLabel || 'Cancel';
    return dialog;
  }

  window.msConfirm = function (options) {
    return new Promise(function (res) {
      var dialog = buildDialog(options || {});
      var previousFocus = document.activeElement;
      var settled = false;

      function finish(value) {
        if (settled) return;
        settled = true;
        res(value);
        dialog.close();
      }

      dialog.addEventListener('close', function () {
        if (!settled) {
          settled = true;
          res(false);
        }
        dialog.remove();
        if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
      });

      dialog.querySelector('#confirm-cancel').addEventListener('click', function () {
        finish(false);
      });

      dialog.querySelector('#confirm-ok').addEventListener('click', function () {
        finish(true);
      });

      document.body.appendChild(dialog);
      dialog.showModal();
    });
  };
})();
