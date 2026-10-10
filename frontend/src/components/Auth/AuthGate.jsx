import { useEffect, useState } from "react";
import { apiFetch } from "../../api/fetch";

// Blocks the app until /auth/status says this cookie's user has a valid Swiggy
// token. On a fresh visit the user sees ONE screen with ONE button linking to
// /auth/swiggy/login; OAuth happens on Swiggy's own domain.
export default function AuthGate({ children }) {
  const [state, setState] = useState("checking"); // "checking" | "needs_login" | "ready"

  useEffect(() => {
    let alive = true;
    apiFetch("/auth/status")
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        setState(d.authenticated ? "ready" : "needs_login");
      })
      .catch(() => alive && setState("needs_login"));
    return () => { alive = false; };
  }, []);

  if (state === "checking") {
    return (
      <div style={wrap}>
        <div style={{ opacity: 0.6, fontSize: 14 }}>loading…</div>
      </div>
    );
  }

  if (state === "needs_login") {
    return (
      <div style={wrap}>
        <div style={card}>
          <div style={{ fontSize: 32, marginBottom: 4 }}>👋</div>
          <h1 style={title}>bhook</h1>
          <p style={sub}>talk yourself fed</p>
          <a href="/auth/swiggy/login" style={cta}>
            Continue with Swiggy
          </a>
          <p style={fine}>You'll sign in on Swiggy.</p>
        </div>
      </div>
    );
  }

  return children;
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
  padding: "12px 24px",
  borderRadius: 999,
  fontWeight: 600,
  fontSize: 14,
  textDecoration: "none",
};
const fine  = { margin: "16px 0 0", color: "var(--mute, #8b8275)", fontSize: 12 };
