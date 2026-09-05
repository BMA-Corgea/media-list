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

export const api = {
  health: () => request('/api/health'),
  search: (q, signal) => request(`/api/search?q=${encodeURIComponent(q)}`, { signal }),
  title: (id) => request(`/api/titles/${id}`),
  patch: (id, changes) => request(`/api/titles/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  titles: (status) => request(`/api/titles${status ? `?status=${status}` : ''}`),
  add: (candidate) => request('/api/titles', { method: 'POST', body: JSON.stringify(candidate) }),
  move: (id, neighbours) => request(`/api/titles/${id}/move`, { method: 'POST', body: JSON.stringify(neighbours) }),
  importPreview: (text) => request('/api/import/preview', { method: 'POST', body: JSON.stringify({ text }) }),
  importCommit: (entries) => request('/api/import/commit', { method: 'POST', body: JSON.stringify({ entries }) }),
  remove: (id) => request(`/api/titles/${id}`, { method: 'DELETE' }),
};
