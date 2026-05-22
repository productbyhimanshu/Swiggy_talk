import { useEffect, useState } from "react";

export default function App() {
  const [health, setHealth] = useState(null);
  const [auth, setAuth] = useState(null);

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(console.error);
    fetch("/auth/status")
      .then((r) => r.json())
      .then(setAuth)
      .catch(console.error);
  }, []);

  return (
    <div className="app">
      <header>
        <h1>Swiggy Talk</h1>
        <p className="tagline">Talk your way to what you want to eat.</p>
      </header>

      <section className="card">
        <h2>Phase 0 — Setup</h2>
        <p>Backend health: {health ? health.status : "…"}</p>
        <p>Orders enabled: {health ? String(health.orders_allowed) : "…"}</p>
        <p>
          Swiggy OAuth:{" "}
          {auth?.authenticated ? "connected" : "not connected"}
        </p>
        {!auth?.authenticated && (
          <a className="btn" href="/auth/swiggy/login">
            Connect Swiggy account
          </a>
        )}
      </section>

      <section className="card muted">
        <p>Chat UI ships in Phase 8. Complete OAuth, then run:</p>
        <code>python scripts/swiggy_smoke.py</code>
      </section>
    </div>
  );
}
