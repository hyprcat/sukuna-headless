/* global document, fetch, location, setTimeout, window */

(function () {
  var configEl = document.getElementById('api-config');
  var apiUrl = configEl?.dataset.url ?? '';
  var wsSlug = configEl?.dataset.ws ?? '';

  var dlgRemove = document.getElementById('dlg-remove');
  var dlgRevokeInvite = document.getElementById('dlg-revoke-invite');

  function notify(message, isError) {
    if (window.msToast) {
      if (isError) window.msToast.error(message);
      else window.msToast.success(message);
    }
  }

  async function gqlFetch(query, variables) {
    var res = await fetch(apiUrl + '/graphql/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Workspace-Slug': wsSlug },
      credentials: 'include',
      body: JSON.stringify({ query: query, variables: variables }),
    });
    return res.json();
  }

  // --- Invite form ---
  document.getElementById('btn-show-invite')?.addEventListener('click', function () {
    document.getElementById('invite-email')?.focus();
  });
  document.getElementById('btn-show-invite-empty')?.addEventListener('click', function () {
    document.getElementById('invite-email')?.focus();
  });

  document.getElementById('form-invite')?.addEventListener('submit', async function (e) {
    e.preventDefault();
    var form = e.target;
    var errEl = document.getElementById('invite-error');
    var okEl = document.getElementById('invite-success');
    var btn = document.getElementById('btn-invite');
    errEl.classList.add('hidden');
    okEl.classList.add('hidden');

    var email = form.elements.namedItem('email').value.trim();
    var role = form.elements.namedItem('role').value;

    if (!email) {
      errEl.textContent = 'Email is required.';
      errEl.classList.remove('hidden');
      return;
    }

    btn.disabled = true;
    btn.querySelector('span').textContent = 'Sending...';

    try {
      var json = await gqlFetch(
        'mutation Invite($input: InviteMemberInput!) { inviteWorkspaceMember(input: $input) { success errors { code field message } invitation { id email role } } }',
        { input: { email: email, role: role } },
      );
      var result = json.data?.inviteWorkspaceMember;

      if (!result?.success) {
        errEl.textContent =
          result?.errors?.[0]?.message ?? "Couldn't send the invitation. Try again.";
        errEl.classList.remove('hidden');
        return;
      }

      form.reset();
      okEl.textContent = 'Invitation sent to ' + email + '.';
      okEl.classList.remove('hidden');
      setTimeout(function () {
        location.reload();
      }, 1200);
    } catch {
      errEl.textContent = 'Something went wrong. Check your connection and try again.';
      errEl.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btn.querySelector('span').textContent = 'Send invite';
    }
  });

  // --- Role change ---
  document.querySelectorAll('.role-select').forEach(function (sel) {
    sel.addEventListener('change', async function () {
      var memberId = sel.dataset.memberId;
      var newRole = sel.value;
      var prev = sel.dataset.currentRole;

      sel.disabled = true;

      try {
        var json = await gqlFetch(
          'mutation UpdateRole($input: UpdateMemberRoleInput!) { updateWorkspaceMemberRole(input: $input) { success errors { code field message } } }',
          { input: { memberId: memberId, role: newRole } },
        );
        var result = json.data?.updateWorkspaceMemberRole;

        if (!result?.success) {
          sel.value = prev;
          notify(result?.errors?.[0]?.message ?? "Couldn't update the role. Try again.", true);
        } else {
          sel.dataset.currentRole = newRole;
          notify('Role updated.', false);
        }
      } catch {
        sel.value = prev;
        notify('Something went wrong. Check your connection and try again.', true);
      } finally {
        sel.disabled = false;
      }
    });
  });

  // --- Remove member ---
  document.querySelectorAll('.btn-remove').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.getElementById('remove-member-id').value = btn.dataset.memberId;
      document.getElementById('remove-member-name').textContent = btn.dataset.memberName;
      document.getElementById('remove-error').classList.add('hidden');
      dlgRemove?.showModal();
    });
  });

  document.getElementById('btn-cancel-remove')?.addEventListener('click', function () {
    dlgRemove?.close();
  });

  document.getElementById('form-remove')?.addEventListener('submit', async function (e) {
    e.preventDefault();
    var errEl = document.getElementById('remove-error');
    var submitBtn = e.target.querySelector('button[type="submit"]');
    errEl.classList.add('hidden');

    var memberId = document.getElementById('remove-member-id').value;

    submitBtn.disabled = true;
    submitBtn.textContent = 'Removing...';

    try {
      var json = await gqlFetch(
        'mutation Remove($memberId: ID!) { removeWorkspaceMember(memberId: $memberId) { success errors { code field message } } }',
        { memberId: memberId },
      );
      var result = json.data?.removeWorkspaceMember;

      if (!result?.success) {
        errEl.textContent =
          result?.errors?.[0]?.message ?? "Couldn't remove the member. Try again.";
        errEl.classList.remove('hidden');
        return;
      }

      dlgRemove.close();
      location.reload();
    } catch {
      errEl.textContent = 'Something went wrong. Check your connection and try again.';
      errEl.classList.remove('hidden');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Remove';
    }
  });

  // --- Resend invitation ---
  document.querySelectorAll('.btn-resend').forEach(function (btn) {
    btn.addEventListener('click', async function () {
      var invitationId = btn.dataset.invitationId;
      btn.disabled = true;

      try {
        var json = await gqlFetch(
          'mutation Resend($input: ResendWorkspaceInvitationInput!) { resendWorkspaceInvitation(input: $input) { success errors { code field message } } }',
          { input: { invitationId: invitationId } },
        );
        var result = json.data?.resendWorkspaceInvitation;

        if (!result?.success) {
          notify(
            result?.errors?.[0]?.message ?? "Couldn't resend the invitation. Try again.",
            true,
          );
        } else {
          var svg = btn.innerHTML;
          btn.innerHTML =
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
          notify('Invitation resent.', false);
          setTimeout(function () {
            btn.innerHTML = svg;
          }, 1500);
        }
      } catch {
        notify('Something went wrong. Check your connection and try again.', true);
      } finally {
        btn.disabled = false;
      }
    });
  });

  // --- Revoke invitation (dialog-based) ---
  document.querySelectorAll('.btn-revoke-invite').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.getElementById('revoke-invite-id').value = btn.dataset.invitationId;
      document.getElementById('revoke-invite-email').textContent = btn.dataset.invitationEmail;
      document.getElementById('revoke-invite-error').classList.add('hidden');
      dlgRevokeInvite?.showModal();
    });
  });

  document.getElementById('btn-cancel-revoke-invite')?.addEventListener('click', function () {
    dlgRevokeInvite?.close();
  });

  document.getElementById('form-revoke-invite')?.addEventListener('submit', async function (e) {
    e.preventDefault();
    var errEl = document.getElementById('revoke-invite-error');
    var submitBtn = e.target.querySelector('button[type="submit"]');
    errEl.classList.add('hidden');

    var invitationId = document.getElementById('revoke-invite-id').value;

    submitBtn.disabled = true;
    submitBtn.textContent = 'Cancelling...';

    try {
      var json = await gqlFetch(
        'mutation Revoke($input: RevokeWorkspaceInvitationInput!) { revokeWorkspaceInvitation(input: $input) { success errors { code field message } } }',
        { input: { invitationId: invitationId } },
      );
      var result = json.data?.revokeWorkspaceInvitation;

      if (!result?.success) {
        errEl.textContent =
          result?.errors?.[0]?.message ?? "Couldn't cancel the invitation. Try again.";
        errEl.classList.remove('hidden');
        return;
      }

      dlgRevokeInvite.close();
      location.reload();
    } catch {
      errEl.textContent = 'Something went wrong. Check your connection and try again.';
      errEl.classList.remove('hidden');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Cancel invitation';
    }
  });
})();
