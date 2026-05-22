import { Close } from "../../icons/index.jsx";

export default function BasketSheet({ open, onClose, cart, restaurant, incCart, decCart }) {
  if (!open) return null;
  const items = Object.values(cart);
  const subtotal = items.reduce((s, it) => s + it.dish.price * it.qty, 0);
  const fee = items.length ? 28 : 0;
  const total = subtotal + fee;
  const over = total > 1000;

  return (
    <div className="basket-overlay" onClick={onClose}>
      <div className="basket" onClick={(e) => e.stopPropagation()}>
        <div className="grabber" />
        <div className="head">
          <div className="from">
            <div className="top">your basket from</div>
            <div className="rest">{restaurant || "—"}</div>
          </div>
          <button className="close" onClick={onClose}><Close /></button>
        </div>
        <div className="items">
          {items.length === 0 && (
            <div style={{ textAlign: "center", padding: "40px 16px", color: "var(--mute)", fontSize: 13 }}>
              basket's empty — go chat with bhook and add a few dishes.
            </div>
          )}
          {items.map((it) => (
            <div className="item" key={it.dish.id}>
              <div className="thumb" />
              <div className="info">
                <div className="n">
                  <span className={"veg-dot" + (it.dish.veg ? "" : " nonveg")} />
                  {it.dish.name}
                </div>
                <div className="p">₹{it.dish.price} · {it.dish.eta} min · {it.dish.restaurant}</div>
              </div>
              <div className="qty">
                <button onClick={() => decCart(it.dish.id)}>−</button>
                <span>{it.qty}</span>
                <button onClick={() => incCart(it.dish.id)}>+</button>
              </div>
            </div>
          ))}
        </div>
        {items.length > 0 && (
          <>
            <div className="totals">
              <div className="line"><span>Subtotal</span><span>₹{subtotal}</span></div>
              <div className="line"><span>Delivery + taxes</span><span>₹{fee}</span></div>
              <div className="line grand"><span>Total</span><span>₹{total}</span></div>
              <div className="cap-warn">
                {over
                  ? "⚠ over swiggy ₹1000 cap — remove an item"
                  : "cap: ₹1000 (Builders Club)"}
              </div>
            </div>
            <div className="cta-row">
              <button className="ghost" onClick={onClose}>Edit in chat</button>
              <button className="primary" disabled={over}>Review &amp; order →</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
