/* global document, fetch, location, setTimeout, window */

(function () {
  var configEl = document.getElementById('api-config');
  var apiUrl = configEl?.dataset.url ?? '';

  var grid = document.getElementById('kb-grid');
  var detailPanel = document.getElementById('kb-detail-panel');
  var newPanel = document.getElementById('kb-new-panel');
  var countEl = document.getElementById('kb-count');
  var searchInput = document.getElementById('kb-search');
  var newBtn = document.getElementById('new-kb-btn');
  var newEmptyBtn = document.getElementById('new-kb-empty');
  var canWrite = document.querySelector('[data-can-write]')?.dataset.canWrite === 'true';

  if (!grid && !newEmptyBtn) return;

  var cards = grid ? Array.from(grid.querySelectorAll('.kb-card')) : [];

  var kindLabels = {
    DOCUMENT: 'Document',
    DATASET: 'Dataset',
    CONNECTED_SOURCE: 'Connected source',
  };

  function selectCard(card) {
    cards.forEach(function (c) {
      c.setAttribute('aria-pressed', 'false');
    });
    card.setAttribute('aria-pressed', 'true');
    hideNewPanel();
    populateDetail(card);
    showDetail();
  }

  function populateDetail(card) {
    var d = card.dataset;
    var nameEl = document.getElementById('detail-name');
    var kindBadge = document.getElementById('detail-kind-badge');
    var statusBadge = document.getElementById('detail-status-badge');
    var filenameEl = document.getElementById('detail-filename');
    var filesizeEl = document.getElementById('detail-filesize');
    var contenttypeEl = document.getElementById('detail-contenttype');
    var updatedEl = document.getElementById('detail-updated');
    var indexedEl = document.getElementById('detail-indexed');
    var indexedWrap = document.getElementById('detail-indexed-wrap');
    var endpointEl = document.getElementById('detail-endpoint');
    var endpointWrap = document.getElementById('detail-endpoint-wrap');
    var descEl = document.getElementById('detail-description');
    var agentsEl = document.getElementById('detail-agents');
    var toggleBtn = document.getElementById('btn-toggle-active');
    var editId = document.getElementById('edit-kb-id');
    var editName = document.getElementById('edit-name');
    var editDesc = document.getElementById('edit-description');
    var editEndpoint = document.getElementById('edit-endpoint');
    var editEndpointField = document.getElementById('edit-endpoint-field');

    if (nameEl) nameEl.textContent = d.kbName;
    if (kindBadge) kindBadge.textContent = kindLabels[d.kbKind] || d.kbKind;

    var isActive = d.kbActive === 'true';
    if (statusBadge) {
      statusBadge.textContent = isActive ? 'Active' : 'Inactive';
      statusBadge.className = 'status-badge ' + (isActive ? 'active' : 'inactive');
    }
    if (toggleBtn) toggleBtn.textContent = isActive ? 'Deactivate' : 'Activate';

    if (filenameEl) filenameEl.textContent = d.kbFilename || '—';
    if (filesizeEl) filesizeEl.textContent = formatSize(d.kbFilesize);
    if (contenttypeEl) contenttypeEl.textContent = d.kbContenttype || '—';
    if (updatedEl) updatedEl.textContent = d.kbUpdated ? formatDate(d.kbUpdated) : '—';

    if (d.kbIndexed) {
      if (indexedEl) indexedEl.textContent = formatDate(d.kbIndexed);
      if (indexedWrap) indexedWrap.hidden = false;
    } else {
      if (indexedWrap) indexedWrap.hidden = true;
    }

    var isSource = d.kbKind === 'CONNECTED_SOURCE';
    if (endpointWrap) endpointWrap.hidden = !isSource;
    if (endpointEl && isSource) endpointEl.textContent = d.kbEndpoint || '—';
    if (editEndpointField) editEndpointField.hidden = !isSource;

    if (descEl) descEl.textContent = d.kbDescription || '';

    var agents = JSON.parse(d.kbAgents || '[]');
    if (agentsEl) {
      agentsEl.innerHTML = '';
      if (agents.length === 0) {
        var empty = document.createElement('span');
        empty.className = 'agent-empty';
        empty.textContent = 'No agents assigned';
        agentsEl.appendChild(empty);
      } else {
        agents.forEach(function (name) {
          var pill = document.createElement('span');
          pill.className = 'agent-pill';
          pill.textContent = name;
          agentsEl.appendChild(pill);
        });
      }
    }

    if (editId) editId.value = d.kbId;
    if (editName) editName.value = d.kbName;
    if (editDesc) editDesc.value = d.kbDescription;
    if (editEndpoint) editEndpoint.value = d.kbEndpoint || '';

    switchTab('overview');
    hideEditFeedback();
  }

  function showDetail() {
    if (detailPanel) detailPanel.hidden = false;
    detailPanel?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function hideDetail() {
    if (detailPanel) detailPanel.hidden = true;
  }

  function showNewPanel() {
    if (!canWrite) return;
    cards.forEach(function (c) {
      c.setAttribute('aria-pressed', 'false');
    });
    hideDetail();
    if (newPanel) newPanel.hidden = false;

    var newForm = document.getElementById('kb-new-form');
    if (newForm) {
      newForm.elements.name.value = '';
      newForm.elements.kind.value = 'connected_source';
      newForm.elements.description.value = '';
      newForm.elements.sourceEndpoint.value = '';
    }
    updateNewEndpointVisibility();
    hideNewFeedback();
    newPanel?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    var nameInput = document.getElementById('new-name');
    if (nameInput) nameInput.focus();
  }

  function hideNewPanel() {
    if (newPanel) newPanel.hidden = true;
  }

  cards.forEach(function (card) {
    card.addEventListener('click', function () {
      selectCard(card);
    });
  });

  if (newBtn) newBtn.addEventListener('click', showNewPanel);
  if (newEmptyBtn) newEmptyBtn.addEventListener('click', showNewPanel);

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
    searchInput.addEventListener('input', applyFilters);
  }

  function applyFilters() {
    var query = (searchInput?.value || '').toLowerCase().trim();
    var activePill = document.querySelector('.pill-active');
    var activeFilter = activePill?.dataset.filter || 'all';
    var shown = 0;

    cards.forEach(function (card) {
      var name = (card.dataset.kbName || '').toLowerCase();
      var desc = (card.dataset.kbDescription || '').toLowerCase();
      var isActive = card.dataset.kbActive === 'true';

      var matchesSearch = !query || name.includes(query) || desc.includes(query);
      var matchesFilter =
        activeFilter === 'all' ||
        (activeFilter === 'active' && isActive) ||
        (activeFilter === 'inactive' && !isActive);

      var visible = matchesSearch && matchesFilter;
      card.style.display = visible ? '' : 'none';
      if (visible) shown++;
    });

    if (countEl)
      countEl.textContent = 'Showing ' + shown + ' of ' + cards.length + ' knowledge sources';
  }

  // Detail panel tabs
  document.querySelectorAll('.detail-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      switchTab(tab.dataset.tab);
    });
  });

  function switchTab(tabId) {
    document.querySelectorAll('.detail-tab').forEach(function (t) {
      var active = t.dataset.tab === tabId;
      t.classList.toggle('detail-tab-active', active);
      t.setAttribute('aria-selected', String(active));
    });
    var overview = document.getElementById('tab-overview');
    var edit = document.getElementById('tab-edit');
    if (overview) overview.hidden = tabId !== 'overview';
    if (edit) edit.hidden = tabId !== 'edit';
  }

  // Toggle active/inactive
  var toggleBtn = document.getElementById('btn-toggle-active');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', async function () {
      if (!canWrite) return;
      var selectedCard = grid?.querySelector('[aria-pressed="true"]');
      if (!selectedCard) return;

      var id = selectedCard.dataset.kbId;
      var isActive = selectedCard.dataset.kbActive === 'true';
      var name = selectedCard.dataset.kbName || 'this knowledge source';

      if (isActive && typeof window.msConfirm === 'function') {
        var ok = await window.msConfirm({
          title: 'Deactivate knowledge',
          message:
            'Agents using "' + name + '" will lose access to it. You can reactivate it later.',
          confirmLabel: 'Deactivate',
          variant: 'danger',
        });
        if (!ok) return;
      }

      var mutation = isActive
        ? 'mutation($id:ID!){deactivateKnowledge(id:$id){success errors{code message}}}'
        : 'mutation($id:ID!){activateKnowledge(id:$id){success errors{code message}}}';

      toggleBtn.disabled = true;
      try {
        var result = await gqlMutate(mutation, { id: id });
        var payload = result.data?.[isActive ? 'deactivateKnowledge' : 'activateKnowledge'];
        if (payload?.success) {
          selectedCard.dataset.kbActive = String(!isActive);
          selectedCard.dataset.inactive = String(isActive);
          toggleBtn.textContent = isActive ? 'Activate' : 'Deactivate';
          var statusBadge = document.getElementById('detail-status-badge');
          if (statusBadge) {
            statusBadge.textContent = isActive ? 'Inactive' : 'Active';
            statusBadge.className = 'status-badge ' + (isActive ? 'inactive' : 'active');
          }
          if (window.msToast)
            window.msToast.success(isActive ? 'Knowledge deactivated.' : 'Knowledge activated.');
        } else {
          var errMsg = payload?.errors?.[0]?.message || 'Something went wrong.';
          if (window.msToast) window.msToast.error(errMsg);
        }
      } catch {
        if (window.msToast)
          window.msToast.error('Something went wrong. Check your connection and try again.');
      } finally {
        toggleBtn.disabled = false;
      }
    });
  }

  // Reindex
  var reindexBtn = document.getElementById('btn-reindex');
  if (reindexBtn) {
    reindexBtn.addEventListener('click', async function () {
      if (!canWrite) return;
      var selectedCard = grid?.querySelector('[aria-pressed="true"]');
      if (!selectedCard) return;

      reindexBtn.disabled = true;
      try {
        var result = await gqlMutate(
          'mutation($id:ID!){reindexKnowledge(id:$id){success errors{code message}}}',
          { id: selectedCard.dataset.kbId },
        );
        var payload = result.data?.reindexKnowledge;
        if (payload?.success) {
          reindexBtn.textContent = 'Reindexed';
          if (window.msToast) window.msToast.success('Reindex started.');
          setTimeout(function () {
            reindexBtn.textContent = 'Reindex';
          }, 2000);
        } else {
          var errMsg = payload?.errors?.[0]?.message || "Couldn't start the reindex. Try again.";
          if (window.msToast) window.msToast.error(errMsg);
        }
      } catch {
        if (window.msToast)
          window.msToast.error('Something went wrong. Check your connection and try again.');
      } finally {
        reindexBtn.disabled = false;
      }
    });
  }

  // Edit form
  var editForm = document.getElementById('kb-edit-form');
  var editFeedback = document.getElementById('edit-feedback');

  if (editForm) {
    editForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      if (!canWrite) return;
      var btn = document.getElementById('save-kb-btn');
      if (btn) btn.disabled = true;
      hideEditFeedback();

      try {
        var kbId = editForm.elements.kbId.value;
        var name = editForm.elements.name.value.trim();
        var description = editForm.elements.description.value.trim();

        if (!name) {
          showEditFeedback('Name is required.', 'error');
          return;
        }

        var input = { name: name, description: description };

        var endpointField = document.getElementById('edit-endpoint-field');
        if (endpointField && !endpointField.hidden) {
          input.sourceEndpoint = editForm.elements.sourceEndpoint.value.trim();
        }

        var result = await gqlMutate(
          'mutation($id:ID!,$input:UpdateKnowledgeInput!){updateKnowledge(id:$id,input:$input){success errors{code message field} knowledge{id name description}}}',
          { id: kbId, input: input },
        );

        var payload = result.data?.updateKnowledge;
        if (payload?.success) {
          showEditFeedback('Changes saved.', 'success');
          var card = grid?.querySelector('[data-kb-id="' + kbId + '"]');
          if (card) {
            card.dataset.kbName = name;
            card.dataset.kbDescription = description;
            var titleEl = card.querySelector('.card-title');
            if (titleEl) titleEl.textContent = name;
            var descEl = card.querySelector('.card-desc');
            if (descEl) descEl.textContent = description || 'No description';
          }
          var detailNameEl = document.getElementById('detail-name');
          if (detailNameEl) detailNameEl.textContent = name;
          var detailDescEl = document.getElementById('detail-description');
          if (detailDescEl) detailDescEl.textContent = description;
        } else {
          showEditFeedback(
            payload?.errors?.[0]?.message || "Couldn't save your changes. Try again.",
            'error',
          );
        }
      } catch {
        showEditFeedback('Something went wrong. Check your connection and try again.', 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  function showEditFeedback(msg, type) {
    if (!editFeedback) return;
    editFeedback.textContent = msg;
    editFeedback.className = 'editor-feedback ' + type;
    editFeedback.hidden = false;
  }

  function hideEditFeedback() {
    if (editFeedback) editFeedback.hidden = true;
  }

  // New knowledge form
  var newForm = document.getElementById('kb-new-form');
  var newFeedback = document.getElementById('new-feedback');
  var newKindSelect = document.getElementById('new-kind');

  if (newKindSelect) {
    newKindSelect.addEventListener('change', updateNewEndpointVisibility);
  }

  function updateNewEndpointVisibility() {
    var endpointField = document.getElementById('new-endpoint-field');
    if (endpointField && newKindSelect) {
      endpointField.hidden = newKindSelect.value !== 'connected_source';
    }
  }

  if (newForm) {
    newForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      if (!canWrite) return;
      var btn = document.getElementById('create-kb-btn');
      if (btn) btn.disabled = true;
      hideNewFeedback();

      try {
        var name = newForm.elements.name.value.trim();
        var kind = newForm.elements.kind.value;
        var description = newForm.elements.description.value.trim();

        if (!name) {
          showNewFeedback('Name is required.', 'error');
          return;
        }

        var input = { name: name, kind: kind, description: description };

        if (kind === 'connected_source') {
          input.sourceEndpoint = newForm.elements.sourceEndpoint.value.trim();
          if (!input.sourceEndpoint) {
            showNewFeedback('Source endpoint is required.', 'error');
            return;
          }
        } else {
          showNewFeedback('Uploads are not available from this screen yet.', 'error');
          return;
        }

        var result = await gqlMutate(
          'mutation($input:CreateKnowledgeInput!){createKnowledge(input:$input){success errors{code message field} knowledge{id name}}}',
          { input: input },
        );

        var payload = result.data?.createKnowledge;
        if (payload?.success) {
          showNewFeedback('Knowledge created. Reloading…', 'success');
          setTimeout(function () {
            location.reload();
          }, 600);
        } else {
          showNewFeedback(
            payload?.errors?.[0]?.message ||
              "Couldn't add the knowledge source. Check the fields and try again.",
            'error',
          );
        }
      } catch {
        showNewFeedback('Something went wrong. Check your connection and try again.', 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  function showNewFeedback(msg, type) {
    if (!newFeedback) return;
    newFeedback.textContent = msg;
    newFeedback.className = 'editor-feedback ' + type;
    newFeedback.hidden = false;
  }

  function hideNewFeedback() {
    if (newFeedback) newFeedback.hidden = true;
  }

  // Helpers
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

  function formatSize(raw) {
    var bytes = parseInt(raw, 10);
    if (isNaN(bytes) || bytes === 0) return '—';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  function formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }
})();
