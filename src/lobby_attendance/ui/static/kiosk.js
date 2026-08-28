(() => {
  const message = document.getElementById('status-message');
  const video = document.getElementById('camera');
  const fallback = document.getElementById('camera-fallback');
  let token;
  let busy = false;
  let resetTimer;
  const successStates = new Set(['recognized-event-recorded', 'duplicate-suppressed', 'cooldown-suppressed', 'event-queued-locally']);
  const warningStates = new Set(['unknown', 'ambiguous', 'liveness-failed', 'low-quality', 'no-face', 'multiple-faces']);

  function show(state, text, kind) {
    message.textContent = text;
    message.className = `status ${kind}`;
    clearTimeout(resetTimer);
    if (state !== 'neutral') resetTimer = setTimeout(() => show('neutral', 'Ready', 'neutral'), 4500);
  }

  function tokenForKiosk() {
    if (!token) token = window.prompt('Enter the configured kiosk service token. It remains in memory only.') || '';
    return token;
  }

  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      fallback.textContent = 'Camera access is unavailable on this device.';
      show('camera-unavailable', 'Camera unavailable. Ask an operator for help.', 'error');
      return;
    }
    try {
      video.srcObject = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
      fallback.hidden = true;
    } catch (_) {
      fallback.textContent = 'Camera permission is required for this kiosk.';
      show('camera-unavailable', 'Camera unavailable. Ask an operator for help.', 'error');
    }
  }

  async function interact() {
    if (busy || !tokenForKiosk()) return;
    busy = true;
    try {
      const response = await fetch('/api/kiosk/interaction', {
        method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: '{}'
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok && data.error === 'configuration-error') {
        show('operator-attention', 'Kiosk configuration needs operator attention.', 'error');
      } else {
        const state = data.state || 'unavailable';
        const kind = successStates.has(state) ? 'success' : warningStates.has(state) ? 'warning' : state === 'neutral' ? 'neutral' : 'error';
        show(state, data.message || 'Recognition is temporarily unavailable.', kind);
      }
    } catch (_) {
      show('unavailable', 'Recognition service is unavailable. Ask an operator for help.', 'error');
    } finally { busy = false; }
  }

  startCamera();
  setTimeout(interact, 1200);
  setInterval(interact, 6500);
})();
