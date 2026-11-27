// Shared fetch helper. Usage: const data = await api('/cims/api/accounts');
async function api(url, { method = 'GET', body } = {}) {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error || 'Request failed');
  return json.data;
}
