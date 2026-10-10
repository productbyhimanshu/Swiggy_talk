import { useEffect, useState } from "react";
import { apiFetch } from "../../api/fetch";

// Every page load starts on this screen.
//   • Not connected → "Continue with Swiggy" (OAuth happens on Swiggy's site).
//   • Connected     → one-tap "Continue", or switch to another Swiggy account.
// Returning from a fresh Swiggy login (?connected=1) skips straight to the app.
export default function AuthGate({ children }) {
  const [state, setState] = useState("checking"); // checking | needs_login | start | ready
  // Read once at first render: the effect below strips the flag from the URL,
  // and StrictMode re-runs effects, so it must not re-read the URL.
  const [justConnected] = useState(
    () => new URLSearchParams(window.location.search).has("connected")
  );
  const [authFailed] = useState(
    () => new URLSearchParams(window.location.search).has("auth_error")
  );

  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams(window.location.search);
    if (params.has("connected") || params.has("auth_error")) {
      params.delete("connected");
      params.delete("auth_error");
      const qs = params.toString();
      window.history.replaceState(null, "", window.location.pathname + (qs ? `?${qs}` : ""));
    }

    apiFetch("/auth/status")
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        if (!d.authenticated) setState("needs_login");
        else setState(justConnected ? "ready" : "start");
      })
      .catch(() => alive && setState("needs_login"));
    return () => { alive = false; };
  }, [justConnected]);

  async function switchAccount() {
    try { await apiFetch("/auth/logout", { method: "POST" }); } catch {}
    window.location.href = "/auth/swiggy/login";
  }

  if (state === "ready") return children;

  if (state === "checking") {
    return (
      <div style={wrap}>
        <div style={{ opacity: 0.6, fontSize: 14 }}>loading…</div>
      </div>
    );
  }

  return (
    <div style={wrap}>
      <div style={card}>
        <div style={{ fontSize: 32, marginBottom: 4 }}>👋</div>
        <h1 style={title}>bhook</h1>
        <p style={sub}>talk yourself fed</p>
        {state === "start" ? (
          <>
            <button style={cta} onClick={() => setState("ready")}>Continue</button>
            <p style={fine}>Your Swiggy account is connected.</p>
            <button style={link} onClick={switchAccount}>Use another Swiggy account</button>
          </>
        ) : (
          <>
            {authFailed && <p style={errorNote}>Sign-in didn't finish. Please try again.</p>}
            <a href="/auth/swiggy/login" style={cta}>Continue with Swiggy</a>
            <p style={fine}>You'll sign in on Swiggy.</p>
          </>
        )}
      </div>
    </div>
  );
}

const wrap = {
  minHeight: "100vh",
  display: "grid",
  placeItems: "center",
  background: "var(--bg, #faf8f3)",
  fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
};
const card = {
  background: "#fff",
  padding: "40px 36px",
  borderRadius: 20,
  boxShadow: "0 10px 40px rgba(31,26,20,.08)",
  textAlign: "center",
  maxWidth: 360,
  width: "90%",
};
const title = { margin: "4px 0 2px", fontSize: 28, fontWeight: 700, letterSpacing: "-0.02em" };
const sub   = { margin: "0 0 24px", color: "var(--mute, #8b8275)", fontSize: 14 };
const cta   = {
  display: "inline-block",
  background: "oklch(0.20 0.012 60)",
  color: "#fff",
  border: "none",
  padding: "12px 24px",
  borderRadius: 999,
  fontWeight: 600,
  fontSize: 14,
  fontFamily: "inherit",
  textDecoration: "none",
  cursor: "pointer",
};
const fine  = { margin: "16px 0 0", color: "var(--mute, #8b8275)", fontSize: 12 };
const errorNote = {
  margin: "0 0 16px",
  padding: "8px 12px",
  background: "#fdecea",
  color: "#a83232",
  borderRadius: 8,
  fontSize: 12,
};
const link  = {
  marginTop: 10,
  background: "none",
  border: "none",
  color: "var(--mute, #8b8275)",
  fontSize: 12,
  fontFamily: "inherit",
  textDecoration: "underline",
  cursor: "pointer",
};
