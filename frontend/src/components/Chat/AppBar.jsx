import { Cart, More, Pin } from "../../icons/index.jsx";

export default function AppBar({ cartCount, onCart, address, onAddressClick }) {
  const label = address?.chip || address?.label;

  return (
    <div className="app-bar">
      <div className="crest">B</div>
      <div className="who">
        <div className="name">bhook</div>
        <button className="address-cta" onClick={onAddressClick}>
          <Pin />
          <span>{label || "Select Address"}</span>
          <span className="address-cta-arrow">›</span>
        </button>
      </div>
      <div className="right">
        <button className="icon-btn" aria-label="cart" onClick={onCart}>
          <Cart />
          {cartCount > 0 && <span className="badge">{cartCount}</span>}
        </button>
        <button className="icon-btn" aria-label="more">
          <More />
        </button>
      </div>
    </div>
  );
}
