import { Bag } from "../../icons/index.jsx";

export default function DesktopCart({ cart, restaurant, incCart, decCart }) {
  const items = Object.values(cart);
  const subtotal = items.reduce((s, it) => s + it.dish.price * it.qty, 0);
  const fee = items.length ? 28 : 0;
  const total = subtotal + fee;

  if (items.length === 0) {
    return (
      <div className="ds-cart">
        <div className="head">
          <div className="label">basket</div>
          <div className="title">empty</div>
          <div className="rest">add a dish from chat to start</div>
        </div>
        <div className="empty">
          <div className="ico"><Bag /></div>
          <div className="t">nothing in here yet</div>
          <div className="s">
            bhook fills this up as you add. items stay editable — quantity, swap, clear.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ds-cart">
      <div className="head">
        <div className="label">your basket from</div>
        <div className="title">{restaurant}</div>
        <div className="rest">single restaurant · COD</div>
      </div>
      <div className="items">
        {items.map((it) => (
          <div className="item" key={it.dish.id}>
            <div className="thumb" />
            <div className="info">
              <div className="n">
                <span className={"veg-dot" + (it.dish.veg ? "" : " nonveg")} />
                {it.dish.name}
              </div>
              <div className="p">₹{it.dish.price} · {it.dish.eta} min</div>
            </div>
            <div className="qty">
              <button onClick={() => decCart(it.dish.id)}>−</button>
              <span>{it.qty}</span>
              <button onClick={() => incCart(it.dish.id)}>+</button>
            </div>
          </div>
        ))}
      </div>
      <div className="totals">
        <div className="line"><span>Subtotal</span><span>₹{subtotal}</span></div>
        <div className="line"><span>Delivery + taxes</span><span>₹{fee}</span></div>
        <div className="line grand"><span>Total</span><span>₹{total}</span></div>
      </div>
      <div className="cta">
        <button>Review &amp; order →</button>
      </div>
    </div>
  );
}
