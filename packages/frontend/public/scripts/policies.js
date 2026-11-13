/* global document, Event, fetch, location, setTimeout */

(function () {
  var configEl = document.getElementById('api-config');
  var apiUrl = configEl?.dataset.url ?? '';
  var workspaceSlug = configEl?.dataset.ws ?? '';

  var listEl = document.getElementById('policy-list');
  var editorPanel = document.getElementById('editor-panel');
  var placeholder = document.getElementById('editor-placeholder');
  var form = document.getElementById('policy-editor-form');
  var searchInput = document.getElementById('policy-search');
  var newPolicyBtn = document.getElementById('new-policy-btn');
  var newPolicyEmptyBtn = document.getElementById('new-policy-empty');
  var feedbackEl = document.getElementById('editor-feedback');

  if (!listEl || !form) return;

  var cards = Array.from(listEl.querySelectorAll('.policy-card'));
  var isNewMode = false;
  var canWrite = editorPanel?.dataset.canWrite === 'true';

  function syncCodeEditor(field) {
    field.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function selectCard(card) {
    cards.forEach(function (c) {
      c.setAttribute('aria-pressed', 'false');
    });
    card.setAttribute('aria-pressed', 'true');
    isNewMode = false;
    populateEditor(card);
    showEditor();
  }

  function populateEditor(card) {
    form.elements.policyId.value = card.dataset.policyId;
    form.elements.name.value = card.dataset.policyName;

    var actions = JSON.parse(card.dataset.policyActions || '[]');
    var domains = JSON.parse(card.dataset.policyDomains || '[]');
    var outputs = JSON.parse(card.dataset.policyOutputs || '[]');

    var rulesObj = {
      action_restrictions: actions,
      domain_restrictions: domains,
      output_restrictions: outputs,
    };
    form.elements.rules.value = JSON.stringify(rulesObj, null, 2);
    syncCodeEditor(form.elements.rules);

    var policyId = card.dataset.policyId;
    document.querySelectorAll('.agent-scope-badge').forEach(function (badge) {
      if (badge.dataset.overrideId === policyId) {
        badge.classList.add('assigned');
      } else {
        badge.classList.remove('assigned');
      }
    });

    hideFeedback();
  }

  function showEditor() {
    if (editorPanel) editorPanel.hidden = false;
    if (placeholder) placeholder.hidden = true;
  }

  function showNewPolicyForm() {
    if (!canWrite) return;
    cards.forEach(function (c) {
      c.setAttribute('aria-pressed', 'false');
    });
    isNewMode = true;

    form.elements.policyId.value = '';
    form.elements.name.value = '';
    form.elements.rules.value = JSON.stringify(
      { action_restrictions: [], domain_restrictions: [], output_restrictions: [] },
      null,
      2,
    );
    syncCodeEditor(form.elements.rules);

    document.querySelectorAll('.agent-scope-badge').forEach(function (b) {
      b.classList.remove('assigned');
    });

    hideFeedback();
    showEditor();
    form.elements.name.focus();
  }

  cards.forEach(function (card) {
    card.addEventListener('click', function () {
      selectCard(card);
    });
  });

  if (newPolicyBtn) newPolicyBtn.addEventListener('click', showNewPolicyForm);
  if (newPolicyEmptyBtn) newPolicyEmptyBtn.addEventListener('click', showNewPolicyForm);

  // Search
  if (searchInput) {
    searchInput.addEventListener('input', function () {
      applySearch();
    });
  }

  function applySearch() {
    var query = (searchInput?.value || '').toLowerCase().trim();
    cards.forEach(function (card) {
      var name = (card.dataset.policyName || '').toLowerCase();
      var visible = !query || name.includes(query);
      card.style.display = visible ? '' : 'none';
    });
  }

  function showFeedback(message, type) {
    if (!feedbackEl) return;
    feedbackEl.textContent = message;
    feedbackEl.className = 'editor-feedback ' + type;
    feedbackEl.hidden = false;
  }

  function hideFeedback() {
    if (feedbackEl) feedbackEl.hidden = true;
  }

  async function gqlMutate(query, variables) {
    var headers = { 'Content-Type': 'application/json' };
    if (workspaceSlug) headers['X-Workspace-Slug'] = workspaceSlug;

    var res = await fetch(apiUrl + '/graphql/', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ query: query, variables: variables }),
      credentials: 'include',
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var json = await res.json();
    if (json.errors?.length) throw new Error(json.errors[0].message || 'GraphQL error');
    return json;
  }

  function parseRules(raw) {
    var parsed = JSON.parse(raw);
    return {
      actionRestrictions: parsed.action_restrictions || [],
      domainRestrictions: parsed.domain_restrictions || [],
      outputRestrictions: parsed.output_restrictions || [],
    };
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (!canWrite) return;
    var btn = document.getElementById('save-policy-btn');
    if (btn) btn.disabled = true;
    hideFeedback();

    try {
      var name = form.elements.name.value.trim();
      var rulesRaw = form.elements.rules.value.trim();

      if (!name) {
        showFeedback('Name is required.', 'error');
        return;
      }

      var rules;
      try {
        rules = parseRules(rulesRaw);
      } catch {
        showFeedback('Invalid JSON in rule definition.', 'error');
        return;
      }

      var input = {
        name: name,
        actionRestrictions: rules.actionRestrictions,
        domainRestrictions: rules.domainRestrictions,
        outputRestrictions: rules.outputRestrictions,
      };

      if (isNewMode) {
        var result = await gqlMutate(
          'mutation CreatePolicy($input: CreatePolicyInput!) { createPolicy(input: $input) { success errors { code message field } policy { id name } } }',
          { input: input },
        );

        var payload = result.data?.createPolicy;
        if (payload?.success) {
          showFeedback('Policy created. Reloading…', 'success');
          setTimeout(function () {
            location.reload();
          }, 600);
        } else {
          showFeedback(
            payload?.errors?.[0]?.message ||
              "Couldn't create the policy. Check the fields and try again.",
            'error',
          );
        }
      } else {
        var policyId = form.elements.policyId.value;
        var updateResult = await gqlMutate(
          'mutation UpdatePolicy($id: ID!, $input: UpdatePolicyInput!) { updatePolicy(id: $id, input: $input) { success errors { code message field } policy { id name actionRestrictions domainRestrictions outputRestrictions } } }',
          { id: policyId, input: input },
        );

        var updatePayload = updateResult.data?.updatePolicy;
        if (updatePayload?.success) {
          showFeedback('Changes saved.', 'success');
          var card = listEl.querySelector('[data-policy-id="' + policyId + '"]');
          if (card && updatePayload.policy) {
            var p = updatePayload.policy;
            card.dataset.policyName = p.name;
            card.dataset.policyActions = JSON.stringify(p.actionRestrictions || []);
            card.dataset.policyDomains = JSON.stringify(p.domainRestrictions || []);
            card.dataset.policyOutputs = JSON.stringify(p.outputRestrictions || []);

            var nameEl = card.querySelector('.policy-name');
            if (nameEl) nameEl.textContent = p.name;
            var descEl = card.querySelector('.policy-desc');
            if (descEl) {
              var first =
                (p.actionRestrictions || [])[0] ||
                (p.domainRestrictions || [])[0] ||
                (p.outputRestrictions || [])[0] ||
                '';
              descEl.textContent = first || 'No rules defined';
            }
          }
        } else {
          showFeedback(
            updatePayload?.errors?.[0]?.message || "Couldn't save your changes. Try again.",
            'error',
          );
        }
      }
    } catch {
      showFeedback('Something went wrong. Check your connection and try again.', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  });
})();
