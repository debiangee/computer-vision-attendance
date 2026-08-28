(() => {
  let token = '';
  const $ = (id) => document.getElementById(id);
  const status = $('admin-status');
  const demoStatusMessage = $('demo-status-message');

  class ApiError extends Error {
    constructor(statusCode, code) {
      super('Admin API request failed.');
      this.statusCode = statusCode;
      this.code = code;
    }
  }

  function say(text, kind = 'neutral') {
    if (!status) return;
    status.textContent = text;
    status.className = `status ${kind}`;
  }

  function demoSay(text, kind = 'neutral') {
    if (!demoStatusMessage) return;
    demoStatusMessage.textContent = text;
    demoStatusMessage.className = `status ${kind}`;
  }

  function authHeaders() {
    return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  }

  async function api(path, options = {}) {
    if (!token) throw new ApiError(401, 'missing-token');
    let response;
    try {
      response = await fetch(path, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } });
    } catch (_error) {
      throw new ApiError(0, 'network');
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiError(response.status, typeof data.error === 'string' ? data.error : 'request-failed');
    return data;
  }

  function safeErrorMessage(error) {
    if (!(error instanceof ApiError)) return 'The operation could not be completed. Retry or ask the system operator.';
    if (error.statusCode === 401 || error.statusCode === 403) return 'Admin authorization was not accepted. Check the token or permissions.';
    if (error.statusCode === 400) return 'Check the entered values and try again.';
    if (error.statusCode === 404) return 'This admin operation is not available in the current mode.';
    if (error.statusCode === 409) return 'The operation conflicts with the current enrollment state.';
    if (error.statusCode === 503 || error.statusCode === 0) return 'The service is unavailable. Ask the system operator to check the device and retry.';
    return 'The operation could not be completed. Retry or ask the system operator.';
  }

  function requireToken() {
    if (!token) {
      say('Enter an admin token first.', 'warning');
      return false;
    }
    return true;
  }

  function cell(row, value) {
    const td = document.createElement('td');
    td.textContent = value == null ? '' : String(value);
    row.appendChild(td);
  }

  function table(target, columns, rows) {
    target.replaceChildren();
    const output = document.createElement('table');
    const head = document.createElement('tr');
    columns.forEach((column) => cell(head, column));
    output.appendChild(head);
    rows.forEach((item) => {
      const row = document.createElement('tr');
      columns.forEach((column) => cell(row, item[column]));
      output.appendChild(row);
    });
    target.appendChild(output);
  }

  function setBusy(control, busy, label) {
    if (!control) return;
    if (busy) {
      control.dataset.idleLabel = control.textContent;
      control.disabled = true;
      control.setAttribute('aria-busy', 'true');
      control.textContent = label;
    } else {
      control.disabled = false;
      control.removeAttribute('aria-busy');
      control.textContent = control.dataset.idleLabel || control.textContent;
      delete control.dataset.idleLabel;
    }
  }

  function setDemoValue(id, value) {
    const element = $(id);
    if (element) element.textContent = value;
  }

  function safeState(value, allowed) {
    return allowed.includes(value) ? value : 'Unavailable';
  }

  function renderDemoStatus(data) {
    const enabled = data && data.enabled === true;
    const disabled = data && data.enabled === false;
    const state = safeState(data && data.state, ['ready', 'unavailable', 'disabled']);
    const compliance = safeState(data && data.compliance_gate, ['approved', 'pending']);
    const liveness = safeState(data && data.liveness, ['enabled', 'disabled']);
    const templates = Number.isInteger(data && data.templates) && data.templates >= 0 ? String(data.templates) : 'Unavailable';

    setDemoValue('demo-status-enabled', enabled ? 'Enabled' : disabled ? 'Disabled' : 'Unavailable');
    setDemoValue('demo-status-state', state);
    setDemoValue('demo-status-compliance', compliance);
    setDemoValue('demo-status-liveness', liveness);
    setDemoValue('demo-status-templates', templates);

    const legacy = $('legacy-template-contract');
    if (legacy) legacy.hidden = enabled;
    if (enabled && state === 'ready') {
      demoSay('Executive demo is ready for a server-webcam enrollment.', 'success');
    } else if (disabled) {
      demoSay('Executive demo mode is disabled. Legacy workflows remain available.', 'neutral');
    } else {
      demoSay('Executive demo is unavailable; ask the system operator to check readiness.', 'warning');
    }
  }

  function showDemoStatusUnavailable(message) {
    ['demo-status-enabled', 'demo-status-state', 'demo-status-compliance', 'demo-status-liveness', 'demo-status-templates'].forEach((id) => setDemoValue(id, 'Unavailable'));
    demoSay(message, 'warning');
  }

  async function loadDemoStatus() {
    if (!requireToken()) {
      showDemoStatusUnavailable('Enter an admin token to check demo readiness.');
      return;
    }
    const refresh = $('demo-status-refresh');
    setBusy(refresh, true, 'Refreshing…');
    try {
      const data = await api('/api/admin/demo/status');
      renderDemoStatus(data);
    } catch (error) {
      showDemoStatusUnavailable(safeErrorMessage(error));
    } finally {
      setBusy(refresh, false);
    }
  }

  $('save-token').addEventListener('click', () => {
    token = $('admin-token').value;
    $('admin-token').value = '';
    say(token ? 'Token is active in memory for this page.' : 'Token is not set.', token ? 'success' : 'warning');
    if (token) loadDemoStatus();
    else showDemoStatusUnavailable('Enter an admin token to check demo readiness.');
  });

  $('demo-status-refresh').addEventListener('click', loadDemoStatus);

  $('demo-enrollment-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!requireToken()) return;
    const button = $('demo-enroll');
    if (button.disabled) return;
    setBusy(button, true, 'Capturing on server…');
    demoSay('Capturing bounded samples from the server-attached webcam. Keep the consenting participant ready.', 'neutral');
    try {
      await api('/api/admin/demo/enrollment', {
        method: 'POST',
        body: JSON.stringify({
          user_id: $('demo-user-id').value.trim(),
          display_name: $('demo-display-name').value.trim(),
        }),
      });
      $('demo-enrollment-form').reset();
      demoSay('Demo enrollment recorded. The participant is active for this server run.', 'success');
      await loadDemoStatus();
    } catch (error) {
      demoSay(safeErrorMessage(error), 'error');
    } finally {
      setBusy(button, false);
    }
  });

  $('demo-reset-confirm').addEventListener('change', (event) => {
    $('demo-reset').disabled = !event.target.checked;
  });

  $('demo-reset-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!requireToken() || !$('demo-reset-confirm').checked) return;
    const button = $('demo-reset');
    if (button.disabled) return;
    setBusy(button, true, 'Resetting…');
    demoSay('Resetting in-memory demo enrollment.', 'neutral');
    try {
      const userId = $('demo-reset-user-id').value.trim();
      await api('/api/admin/demo/reset', {
        method: 'POST',
        body: JSON.stringify(userId ? { confirm: true, user_id: userId } : { confirm: true }),
      });
      $('demo-reset-form').reset();
      $('demo-reset').disabled = true;
      demoSay('Demo enrollment reset. The demo user is suspended and its active metadata is retired; event history is preserved.', 'success');
      await loadDemoStatus();
    } catch (error) {
      demoSay(safeErrorMessage(error), 'error');
    } finally {
      setBusy(button, false);
      $('demo-reset').disabled = !$('demo-reset-confirm').checked;
    }
  });

  $('user-form').addEventListener('submit', async (event) => { event.preventDefault(); if (!requireToken()) return; try { await api('/api/admin/users', { method: 'POST', body: JSON.stringify({ user_id: $('user-id').value, display_name: $('display-name').value }) }); say('User created suspended.', 'success'); event.target.reset(); } catch (error) { say(safeErrorMessage(error), 'error'); } });
  $('status-form').addEventListener('submit', async (event) => { event.preventDefault(); if (!requireToken()) return; try { await api(`/api/admin/users/${encodeURIComponent($('status-user').value)}/status`, { method: 'POST', body: JSON.stringify({ status: $('user-status').value }) }); say('Enrollment status updated.', 'success'); } catch (error) { say(safeErrorMessage(error), 'error'); } });
  $('role-form').addEventListener('submit', async (event) => { event.preventDefault(); if (!requireToken()) return; try { await api(`/api/admin/users/${encodeURIComponent($('role-user').value)}/roles`, { method: 'POST', body: JSON.stringify({ role: $('role').value }) }); say('Role assigned.', 'success'); } catch (error) { say(safeErrorMessage(error), 'error'); } });
  $('template-form').addEventListener('submit', async (event) => { event.preventDefault(); if (!requireToken()) return; try { await api('/api/admin/templates', { method: 'POST', body: JSON.stringify({ template_id: $('template-id').value, user_id: $('template-user').value, model_version: $('model-version').value, template_version: $('template-version').value, protected_template_hash: $('template-hash').value }) }); say('Template metadata registered; raw template data was not sent.', 'success'); event.target.reset(); } catch (error) { say(safeErrorMessage(error), 'error'); } });
  async function loadQueue(action = 'queue') { if (!requireToken()) return; try { const data = action === 'queue' ? await api('/api/admin/queue') : await api(`/api/admin/queue/${action}`, { method: 'POST' }); $('queue-output').textContent = JSON.stringify(data.queue || data, null, 2); say('Queue state loaded.', 'success'); } catch (error) { say(safeErrorMessage(error), 'error'); } }
  document.querySelectorAll('[data-queue-action]').forEach((button) => button.addEventListener('click', () => loadQueue(button.dataset.queueAction)));
  $('load-events').addEventListener('click', async () => { if (!requireToken()) return; try { const data = await api('/api/admin/events'); table($('events-output'), ['event_id', 'user_id', 'occurred_at', 'site_id', 'camera_id', 'source'], data.events); } catch (error) { say(safeErrorMessage(error), 'error'); } });
  $('load-audit').addEventListener('click', async () => { if (!requireToken()) return; try { const data = await api('/api/admin/audit'); table($('audit-output'), ['audit_id', 'occurred_at', 'actor_id', 'action', 'outcome', 'resource_type', 'resource_id'], data.audit); } catch (error) { say(safeErrorMessage(error), 'error'); } });
})();
