const base = ''

async function req(method, url, body) {
  const r = await fetch(base + url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : `HTTP ${r.status}`)
  return data
}

export const api = {
  roots: () => req('GET', '/api/roots'),
  createRoot: (name) => req('POST', '/api/roots', { name }),
  scan: (name) => req('POST', `/api/roots/${encodeURIComponent(name)}/scan`),
  graph: (name) => req('GET', `/api/roots/${encodeURIComponent(name)}/graph`),
  accept: (name, object_ids) => req('POST', `/api/roots/${encodeURIComponent(name)}/accept`, { object_ids }),
  changes: (name) => req('GET', `/api/roots/${encodeURIComponent(name)}/changes`),
  clearChanges: (name) => req('DELETE', `/api/roots/${encodeURIComponent(name)}/changes`),
  collection: (name) => req('GET', `/api/roots/${encodeURIComponent(name)}/collection`),
  clearCollection: (name) => req('DELETE', `/api/roots/${encodeURIComponent(name)}/collection`),
  mutate: (name, duration = 10, interval = 0.05) =>
    req('POST', `/api/roots/${encodeURIComponent(name)}/mutate`, { duration, interval }),
  manifestUrl: (name) => `/api/roots/${encodeURIComponent(name)}/manifest/download`,
}
