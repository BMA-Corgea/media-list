/** Thin wrapper over the API. One place decides what an error looks like. */

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    // FastAPI puts our own dicts under `detail`, so unwrap one level to get a real message.
    const detail = body?.detail;
    const message = typeof detail === 'string' ? detail : detail?.detail || detail?.error || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

/**
 * Read a newline-delimited-JSON stream, handing each event to `onEvent` as it arrives and
 * resolving with the terminal `result` event.
 *
 * `/api/import/preview` answers this way rather than with one blob at the end, so a
 * thousand-row preview reports where it is up to instead of being a spinner (T-15 AC3).
 * `request()` above cannot be used for it: that awaits `.json()`, which is the one thing
 * that has to not happen here.
 */
async function ndjson(path, payload, onEvent) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    // A failure BEFORE the first byte is still a normal HTTP error, so it is unwrapped the
    // same way request() unwraps one.
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const error = new Error(typeof detail === 'string' ? detail : detail?.detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }

  let result = null;
  const handle = (line) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    // Once the response has started, a failure cannot be a status code any more — the server
    // sends a terminal `error` event instead. Throwing here is what keeps a half-resolved
    // preview from rendering as a successful short one.
    if (event.event === 'error') throw new Error(event.detail || 'the preview failed part-way');
    if (event.event === 'result') result = event;
    else onEvent?.(event);
  };

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    // The last piece may be half a line; it waits for the rest of its chunk.
    buffer = lines.pop();
    lines.forEach(handle);
  }
  handle(buffer + decoder.decode());

  if (!result) throw new Error('the preview ended without a result — nothing was written');
  return result;
}

export const api = {
  health: () => request('/api/health'),
  search: (q, signal) => request(`/api/search?q=${encodeURIComponent(q)}`, { signal }),
  title: (id) => request(`/api/titles/${id}`),
  patch: (id, changes) => request(`/api/titles/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  titles: (status) => request(`/api/titles${status ? `?status=${status}` : ''}`),
  add: (candidate) => request('/api/titles', { method: 'POST', body: JSON.stringify(candidate) }),
  move: (id, neighbours) => request(`/api/titles/${id}/move`, { method: 'POST', body: JSON.stringify(neighbours) }),
  importPreview: (text, onProgress) => ndjson('/api/import/preview', { text }, onProgress),
  importCommit: (entries) => request('/api/import/commit', { method: 'POST', body: JSON.stringify({ entries }) }),
  remove: (id) => request(`/api/titles/${id}`, { method: 'DELETE' }),
};
