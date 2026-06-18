import { useEffect, useState } from "react";
import { Close } from "../../icons/index.jsx";

/**
 * Phase 13 — Post-order status screen.
 *
 * Shown after `place_order` returns OK. Polls /api/order/status/{order_id}
 * every 20s while open so the user sees the status chase real Swiggy state.
 * `placed` is the raw response from /api/order/place (used for instant render
 * while the first poll is in flight).
 */
export default function OrderStatus({ open, onClose, placed }) {
  const [status, setStatus] = useState(null);
  const [err, setErr]       = useState(null);

  const orderId = placed?.order_id;

  useEffect(() => {
    if (!open || !orderId) return;
    let alive = true;

    async function poll() {
      try {
        const r = await fetch(`/api/order/status/${encodeURIComponent(orderId)}`);
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || `status ${r.status}`);
        }
        const data = await r.json();
        if (alive) setStatus(data);
      } catch (e) {
        if (alive) setErr(e.message);
      }
    }

    poll();
    const id = setInterval(poll, 20000);
    return () => { alive = false; clearInterval(id); };
  }, [open, orderId]);

  if (!open) return null;

  const stage = readStage(status);

  return (
    <div className="basket-overlay" onClick={onClose}>
      <div className="basket" onClick={(e) => e.stopPropagation()} style={{ maxHeight: "85vh" }}>
        <div className="grabber" />
        <div className="head">
          <div className="from">
            <div className="top">order placed</div>
            <div className="rest">{placed?.restaurant?.name || "your kitchen"}</div>
          </div>
          <button className="close" onClick={onClose}><Close /></button>
        </div>

        <div style={hero}>
          <div style={tick}>✓</div>
          <div style={heroTitle}>you're sorted</div>
          <div style={heroSub}>
            {orderId ? <>order id <code style={code}>{orderId}</code></> : "confirmation incoming"}
          </div>
          {placed?.eta && (
            <div style={etaText}>~{placed.eta} min · COD ₹{placed?.total?.toFixed?.(0) ?? placed?.total}</div>
          )}
        </div>

        <div style={timelineBox}>
          {STAGES.map((s, i) => (
            <div key={s.key} style={{ ...stageRow, opacity: i <= stage ? 1 : 0.35 }}>
              <div style={{ ...stageDot, background: i <= stage ? "var(--accent, #2bb24c)" : "#ccc" }} />
              <div>
                <div style={stageLabel}>{s.label}</div>
                <div style={stageSub}>{s.sub}</div>
              </div>
            </div>
          ))}
        </div>

        {err && (
          <div style={{ margin: "8px 16px", fontSize: 12, color: "var(--mute)" }}>
            (last status check failed: {err})
          </div>
        )}

        <div className="cta-row">
          <button className="primary" onClick={onClose}>back to chat</button>
        </div>
      </div>
    </div>
  );
}

const STAGES = [
  { key: "confirmed", label: "order confirmed",     sub: "kitchen got the ticket" },
  { key: "preparing", label: "preparing",           sub: "stove's on" },
  { key: "picked",    label: "picked up",           sub: "rider's heading your way" },
  { key: "delivered", label: "delivered",           sub: "enjoy" },
];

function readStage(status) {
  const raw = (status?.raw?.status || status?.raw?.orderStatus || "").toString().toLowerCase();
  if (raw.includes("deliver")) return 3;
  if (raw.includes("pick"))    return 2;
  if (raw.includes("prepar") || raw.includes("cook")) return 1;
  return 0; // confirmed by default — order has just been placed
}

const hero       = { padding: "24px 16px 12px", textAlign: "center" };
const tick       = { fontSize: 38, color: "var(--accent, #2bb24c)", fontWeight: 700 };
const heroTitle  = { fontSize: 22, fontWeight: 700, marginTop: 6 };
const heroSub    = { fontSize: 13, color: "var(--mute)", marginTop: 4 };
const etaText    = { fontSize: 14, fontWeight: 600, marginTop: 8 };
const code       = { background: "#f4f0e9", padding: "2px 6px", borderRadius: 6, fontFamily: "monospace" };
const timelineBox = { padding: "16px", display: "flex", flexDirection: "column", gap: 14 };
const stageRow   = { display: "flex", gap: 12, alignItems: "flex-start" };
const stageDot   = { width: 12, height: 12, borderRadius: 999, marginTop: 4, flexShrink: 0 };
const stageLabel = { fontSize: 14, fontWeight: 600 };
const stageSub   = { fontSize: 12, color: "var(--mute)" };
