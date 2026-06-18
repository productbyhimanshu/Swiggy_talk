import { useEffect, useState } from "react";
import { Close } from "../../icons/index.jsx";

/**
 * Phase 13 — Review screen.
 *
 * Server is the single source of truth. We POST /api/order/review which
 * re-fetches the Swiggy cart and re-runs the ₹1000 cap + restaurant-OPEN gates.
 * On confirm, POST /api/order/place actually places the order (gated behind
 * ORDER_ENABLED + EVAL_SUITE_PASSED on the backend — a 403 means the gate is
 * closed and we surface the message verbatim).
 */
export default function ReviewSheet({ open, onClose, sessionId, onPlaced, cart, restaurant }) {
  const clientPayload = () => {
    const items = Object.values(cart || {}).map((it) => ({
      id:            String(it.dish.id),
      name:          it.dish.name,
      price:         Number(it.dish.price) || 0,
      quantity:      it.qty,
      veg:           !!it.dish.veg,
      restaurant_id: String(it.dish.restaurantId || it.dish.restaurant_id || ""),
      restaurant:    it.dish.restaurant || restaurant || "",
      image:         it.dish.image || null,
    }));
    const restId = items[0]?.restaurant_id || "";
    return { items, restaurant_id: restId, restaurant_name: restaurant || items[0]?.restaurant || "" };
  };
  const [summary, setSummary]   = useState(null);
  const [loading, setLoading]   = useState(false);
  const [placing, setPlacing]   = useState(false);
  const [error, setError]       = useState(null);
  const [placeErr, setPlaceErr] = useState(null);

  useEffect(() => {
    if (!open) {
      setSummary(null);
      setError(null);
      setPlaceErr(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    fetch("/api/order/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, ...clientPayload() }),
    })
      .then(async (r) => {
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || `review failed (${r.status})`);
        }
        return r.json();
      })
      .then((data) => alive && setSummary(data))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [open, sessionId]);

  async function placeOrder() {
    setPlacing(true);
    setPlaceErr(null);
    try {
      const r = await fetch("/api/order/place", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          confirmed: true,
          payment_method: "COD",
          ...clientPayload(),
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || `Order failed (${r.status})`);
      onPlaced?.(data);
    } catch (e) {
      setPlaceErr(e.message);
    } finally {
      setPlacing(false);
    }
  }

  if (!open) return null;

  return (
    <div className="basket-overlay" onClick={onClose}>
      <div className="basket" onClick={(e) => e.stopPropagation()} style={{ maxHeight: "92vh" }}>
        <div className="grabber" />
        <div className="head">
          <div className="from">
            <div className="top">review your order</div>
            <div className="rest">{summary?.restaurant?.name || "—"}</div>
          </div>
          <button className="close" onClick={onClose}><Close /></button>
        </div>

        {loading && (
          <div style={padState}>fetching live cart…</div>
        )}

        {error && (
          <div style={{ ...padState, color: "var(--err, #c0392b)" }}>
            couldn't load cart: {error}
          </div>
        )}

        {summary && !loading && (
          <>
            {/* delivery address */}
            <div style={addrBox}>
              <div style={addrLabel}>delivering to</div>
              <div style={addrText}>
                {summary.address?.label || summary.address?.chip || "your saved address"}
              </div>
              {summary.address?.text && (
                <div style={addrSub}>{summary.address.text}</div>
              )}
            </div>

            {/* items */}
            <div className="items" style={{ maxHeight: 240 }}>
              {summary.items.map((it) => (
                <div className="item" key={it.id}>
                  <div className="thumb" />
                  <div className="info">
                    <div className="n">
                      <span className={"veg-dot" + (it.veg ? "" : " nonveg")} />
                      {it.name}
                    </div>
                    <div className="p">₹{it.price} × {it.quantity}</div>
                  </div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>
                    ₹{(it.price * it.quantity).toFixed(0)}
                  </div>
                </div>
              ))}
            </div>

            {/* bill */}
            <div className="totals">
              <div className="line">
                <span>Subtotal</span>
                <span>₹{summary.subtotal.toFixed(0)}</span>
              </div>
              {summary.discount > 0 && (
                <div className="line">
                  <span>Discount</span>
                  <span>−₹{summary.discount.toFixed(0)}</span>
                </div>
              )}
              <div className="line">
                <span>Delivery</span>
                <span>₹{summary.delivery_fee.toFixed(0)}</span>
              </div>
              {summary.taxes > 0 && (
                <div className="line">
                  <span>Taxes</span>
                  <span>₹{summary.taxes.toFixed(0)}</span>
                </div>
              )}
              <div className="line grand">
                <span>Total</span>
                <span>₹{summary.total.toFixed(0)}</span>
              </div>
              <div style={metaRow}>
                <span style={codChip}>COD only</span>
                {summary.restaurant?.eta && (
                  <span style={etaChip}>~{summary.restaurant.eta} min</span>
                )}
              </div>
            </div>

            {/* issues */}
            {summary.issues?.length > 0 && (
              <div style={issuesBox}>
                {summary.issues.map((iss, i) => <div key={i}>⚠ {iss}</div>)}
              </div>
            )}

            {/* orders-disabled notice */}
            {!summary.orders_enabled && (
              <div style={disabledBox}>
                {summary.disabled_reason || "Orders are disabled in dev."}
              </div>
            )}

            {/* place-order error */}
            {placeErr && (
              <div style={{ ...issuesBox, color: "var(--err, #c0392b)" }}>
                {placeErr}
              </div>
            )}

            <div className="cta-row">
              <button className="ghost" onClick={onClose} disabled={placing}>
                Back to basket
              </button>
              <button
                className="primary"
                disabled={!summary.can_place_order || placing}
                onClick={placeOrder}
                style={!summary.can_place_order ? { opacity: 0.55 } : undefined}
              >
                {placing ? "Placing…" : `Place order · COD ₹${summary.total.toFixed(0)}`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const padState = { textAlign: "center", padding: "40px 16px", color: "var(--mute)", fontSize: 13 };
const addrBox  = { padding: "10px 16px", borderBottom: "1px solid var(--line, #eee)" };
const addrLabel = { fontSize: 10, color: "var(--mute)", textTransform: "uppercase", letterSpacing: ".06em" };
const addrText  = { fontSize: 14, fontWeight: 600, marginTop: 2 };
const addrSub   = { fontSize: 12, color: "var(--mute)", marginTop: 2 };
const metaRow   = { display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" };
const codChip   = { fontSize: 11, padding: "3px 8px", background: "#f5f1ea", borderRadius: 999, fontWeight: 600 };
const etaChip   = { fontSize: 11, padding: "3px 8px", background: "#eef6e8", borderRadius: 999, fontWeight: 600 };
const issuesBox = { margin: "8px 16px", padding: "10px 12px", background: "#fff4e6", borderRadius: 8, fontSize: 12, color: "#a85d00" };
const disabledBox = { margin: "8px 16px", padding: "10px 12px", background: "#fdecea", borderRadius: 8, fontSize: 12, color: "#a83232" };
