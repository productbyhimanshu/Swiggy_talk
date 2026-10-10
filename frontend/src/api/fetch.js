// Centralised fetch wrapper for all /api and /auth calls.
//
//  • Always sends the signed-cookie `bhook_uid` (credentials: 'include').
//  • Any JSON response body of shape { error: "reauth_required" } fires a global
//    'bhook:reauth' event that <ReconnectBanner/> listens for.
//  • Returns the raw Response so callers that need streaming (SSE chat) still
//    get the body — only the reauth sniffing is centralised.

const REAUTH_EVENT = "bhook:reauth";

export function onReauthRequired(handler) {
  const wrapped = (e) => handler(e.detail);
  window.addEventListener(REAUTH_EVENT, wrapped);
  return () => window.removeEventListener(REAUTH_EVENT, wrapped);
}

function fireReauth(detail = {}) {
  window.dispatchEvent(new CustomEvent(REAUTH_EVENT, { detail }));
}

export async function apiFetch(input, init = {}) {
  const opts = {
    ...init,
    credentials: "include",
    headers: {
      ...(init.headers || {}),
    },
  };
  const res = await fetch(input, opts);

  if (res.status === 401) {
    // Peek at the body WITHOUT consuming it — so callers can still read it.
    try {
      const cloned = res.clone();
      const data = await cloned.json();
      if (data && data.error === "reauth_required") {
        fireReauth({ path: typeof input === "string" ? input : input.url });
      }
    } catch {
      // Non-JSON 401 — ignore
    }
  }
  return res;
}

// Streaming variant for SSE. Still fires reauth on 401.
export async function apiStream(input, init = {}) {
  const res = await apiFetch(input, init);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res;
}
