import { Cart, More } from "../../icons/index.jsx";

export default function AppBar({ cartCount, onCart }) {
  return (
    <div className="app-bar">
      <div className="crest">B</div>
      <div className="who">
        <div className="name">bhook</div>
        <div className="status">
          <span className="live" />
          online · talk yourself fed
        </div>
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
