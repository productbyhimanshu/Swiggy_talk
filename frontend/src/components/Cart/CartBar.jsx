import { Chevron } from "../../icons/index.jsx";

export default function CartBar({ count, total, restaurant, onOpen }) {
  return (
    <div className="cart-bar" onClick={onOpen}>
      <div className="count">{count}</div>
      <div className="sum">
        <b>₹{total} · view basket</b>
        <span>from {restaurant}</span>
      </div>
      <div className="arrow"><Chevron /></div>
    </div>
  );
}
