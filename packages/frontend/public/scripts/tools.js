/* global document, Event, fetch, location, setTimeout */

(function () {
  var configEl = document.getElementById('api-config');
  var apiUrl = configEl?.dataset.url ?? '';

  var grid = document.getElementById('tool-grid');
  var editorPanel = document.getElementById('editor-panel');
  var placeholder = document.getElementById('editor-placeholder');
  var form = document.getElementById('tool-editor-form');
  var countEl = document.getElementById('tool-count');
  var searchInput = document.getElementById('tool-search');
  var newToolBtn = document.getElementById('new-tool-btn');
  var newToolEmptyBtn = document.getElementById('new-tool-empty');
  var feedbackEl = document.getElementById('editor-feedback');
  var canWrite = editorPanel?.dataset.canWrite === 'true';

  if (!grid || !form) return;

  var cards = Array.from(grid.querySelectorAll('.tool-card'));
  var isNewMode = false;

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
    form.elements.toolId.value = card.dataset.toolId;
    form.elements.name.value = card.dataset.toolName;
    form.elements.description.value = card.dataset.toolDescription;
    form.elements.executionEndpoint.value = card.dataset.toolEndpoint;
    form.elements.isSensitive.checked = card.dataset.toolSensitive === 'true';

    var schema = JSON.parse(card.dataset.toolSchema || '{}');
    form.elements.parametersSchema.value =
      Object.keys(schema).length > 0 ? JSON.stringify(schema, null, 2) : '';
    syncCodeEditor(form.elements.parametersSchema);

    var toolAgents = JSON.parse(card.dataset.toolAgents || '[]');
    document.querySelectorAll('.agent-assignment-badge').forEach(function (badge) {
      if (toolAgents.includes(badge.dataset.agentName)) {
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

  function showNewToolForm() {
    if (!canWrite) return;
    cards.forEach(function (c) {
      c.setAttribute('aria-pressed', 'false');
    });
    isNewMode = true;

    form.elements.toolId.value = '';
    form.elements.name.value = '';
    form.elements.description.value = '';
    form.elements.executionEndpoint.value = '';
    form.elements.isSensitive.checked = false;
    form.elements.parametersSchema.value = '';
    syncCodeEditor(form.elements.parametersSchema);

    document.querySelectorAll('.agent-assignment-badge').forEach(function (b) {
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

  if (newToolBtn) newToolBtn.addEventListener('click', showNewToolForm);
  if (newToolEmptyBtn) newToolEmptyBtn.addEventListener('click', showNewToolForm);

  // Filter pills
  document.querySelectorAll('[data-filter]').forEach(function (pill) {
    pill.addEventListener('click', function () {
      document.querySelectorAll('[data-filter]').forEach(function (p) {
        p.classList.remove('pill-active');
        p.setAttribute('aria-checked', 'false');
      });
      pill.classList.add('pill-active');
      pill.setAttribute('aria-checked', 'true');
      applyFilters();
    });
  });

  if (searchInput) {
    searchInput.addEventListener('input', function () {
      applyFilters();
    });
  }

  function applyFilters() {
    var query = (searchInput?.value || '').toLowerCase().trim();
    var activePill = document.querySelector('.pill-active');
    var activeFilter = activePill?.dataset.filter || 'all';
    var shown = 0;

    cards.forEach(function (card) {
      var name = (card.dataset.toolName || '').toLowerCase();
      var desc = (card.dataset.toolDescription || '').toLowerCase();
      var isActive = card.dataset.toolActive === 'true';

      var matchesSearch = !query || name.includes(query) || desc.includes(query);
      var matchesFilter =
        activeFilter === 'all' ||
        (activeFilter === 'active' && isActive) ||
        (activeFilter === 'inactive' && !isActive);

      var visible = matchesSearch && matchesFilter;
      card.style.display = visible ? '' : 'none';
      if (visible) shown++;
    });

    if (countEl) countEl.textContent = 'Showing ' + shown + ' of ' + cards.length + ' tools';
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
    var res = await fetch(apiUrl + '/graphql/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query, variables: variables }),
      credentials: 'include',
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.json();
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (!canWrite) return;
    var btn = document.getElementById('save-tool-btn');
    if (btn) btn.disabled = true;
    hideFeedback();

    try {
      var name = form.elements.name.value.trim();
      var description = form.elements.description.value.trim();
      var endpoint = form.elements.executionEndpoint.value.trim();
      var sensitive = form.elements.isSensitive.checked;
      var schemaRaw = form.elements.parametersSchema.value.trim();

      if (!name) {
        showFeedback('Name is required.', 'error');
        return;
      }

      var schema = null;
      if (schemaRaw) {
        try {
          schema = JSON.parse(schemaRaw);
        } catch {
          showFeedback('Invalid JSON in tool spec.', 'error');
          return;
        }
      }

      var input = {
        name: name,
        description: description,
        executionEndpoint: endpoint,
        isSensitive: sensitive,
      };
      if (schema) input.parametersSchema = schema;

      if (isNewMode) {
        var result = await gqlMutate(
          'mutation CreateTool($input: CreateToolInput!) { createTool(input: $input) { success errors { code message field } tool { id name } } }',
          { input: input },
        );

        var payload = result.data?.createTool;
        if (payload?.success) {
          showFeedback('Tool created. Reloading…', 'success');
          setTimeout(function () {
            location.reload();
          }, 600);
        } else {
          showFeedback(
            payload?.errors?.[0]?.message ||
              "Couldn't create the tool. Check the fields and try again.",
            'error',
          );
        }
      } else {
        var toolId = form.elements.toolId.value;
        var updateResult = await gqlMutate(
          'mutation UpdateTool($id: ID!, $input: UpdateToolInput!) { updateTool(id: $id, input: $input) { success errors { code message field } tool { id name description executionEndpoint isSensitive parametersSchema } } }',
          { id: toolId, input: input },
        );

        var updatePayload = updateResult.data?.updateTool;
        if (updatePayload?.success) {
          showFeedback('Changes saved.', 'success');
          var card = grid.querySelector('[data-tool-id="' + toolId + '"]');
          if (card) {
            card.dataset.toolName = name;
            card.dataset.toolDescription = description;
            card.dataset.toolEndpoint = endpoint;
            card.dataset.toolSensitive = String(sensitive);
            if (schema) card.dataset.toolSchema = JSON.stringify(schema);

            var nameEl = card.querySelector('.tool-name');
            if (nameEl) nameEl.textContent = name;
            var descEl = card.querySelector('.tool-desc');
            if (descEl) descEl.textContent = description || 'No description';
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
