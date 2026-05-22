import { Star, Clock, Plus } from "../../icons/index.jsx";

export default function DishCard({ dish, qty, lockedRestaurant, onAdd, onInc, onDec }) {
  const switches = lockedRestaurant && dish.restaurant !== lockedRestaurant;
  const sameRest  = lockedRestaurant && dish.restaurant === lockedRestaurant;
  // eta may be int (minutes) or string like "25 min" — normalise to just the number
  const etaRaw = dish.eta ?? dish.deliveryTime ?? "—";
  const eta = typeof etaRaw === "number" ? etaRaw : String(etaRaw).replace(/\s*min.*/, "").trim();
  // subtitle: cuisines for restaurant cards, or restaurant name for dish cards
  const subtitle = dish.cuisines || dish.restaurant || "";

  return (
    <div className={"dish-card" + (switches ? " switches" : "")}>
      <div className="img">
        <div className="stripe" />
        <div className="placeholder">{dish.placeholder || dish.name}</div>
        {dish.why && <div className="why">{dish.why}</div>}
        <div className="rating-pill">
          <Star /> {dish.rating ?? "—"}
        </div>
        {sameRest && qty === 0 && <div className="card-flag in-basket">in your basket</div>}
        {switches && <div className="card-flag switches-cart">switches basket</div>}
      </div>
      <div className="body">
        <div className="name-row">
          {/* Only show veg dot when veg status is known */}
          {dish.veg !== null && dish.veg !== undefined && (
            <span className={"veg-dot" + (dish.veg ? "" : " nonveg")} />
          )}
          <span>{dish.name}</span>
        </div>
        <div className="rest">
          <span className="cuisines">{subtitle}</span>
          {eta !== "—" && <><span>·</span><span className="eta"><Clock /> {eta} min</span></>}
        </div>
        <div className="footer-row">
          <div className="price">
            {dish.mrp && <span className="strike">₹{dish.mrp}</span>}
            ₹{dish.price}
            {dish.priceLabel && <span className="price-label"> {dish.priceLabel}</span>}
          </div>
          {qty > 0 ? (
            <div className="qty">
              <button onClick={onDec}>−</button>
              <span>{qty}</span>
              <button onClick={onInc}>+</button>
            </div>
          ) : (
            <button className={"add" + (switches ? " switches" : "")} onClick={onAdd}>
              <Plus /> Add
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
