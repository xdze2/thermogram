export async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status} ${r.statusText}`);
  return r.json();
}

export async function postRcModel(roomPayload) {
  const r = await fetch('/api/room/rc_model', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(roomPayload),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new ApiError(formatApiError(err));
  }
  return r.json();
}

function formatApiError(err) {
  if (err.detail && Array.isArray(err.detail)) return err.detail.map(d => d.msg).join('; ');
  return JSON.stringify(err);
}

class ApiError extends Error {}
