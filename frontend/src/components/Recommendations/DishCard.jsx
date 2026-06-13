import { Star, Clock, Plus } from "../../icons/index.jsx";

export default function DishCard({ dish, qty, lockedRestaurant, onAdd, onInc, onDec }) {
  const switches = lockedRestaurant && dish.restaurant !== lockedRestaurant;
  const sameRest  = lockedRestaurant && dish.restaurant === lockedRestaurant;
  // eta may be int (minutes) or string like "25 min" — normalise to just the number
  const etaRaw = dish.eta ?? dish.deliveryTime ?? "—";
  const eta = typeof etaRaw === "number" ? etaRaw : String(etaRaw).replace(/\s*min.*/, "").trim();
  // Dish cards (have itemId) lead with the restaurant name so the user knows
  // where it comes from; restaurant cards just show cuisines.
  const isDish = Boolean(dish.itemId);
  const subtitle = isDish
    ? `from ${dish.restaurant || "—"}`
    : (dish.cuisines || dish.restaurant || "");

  return (
    <div className={"dish-card" + (switches ? " switches" : "")}>
      <div className="img">
        <div className="stripe" />
        {dish.imageUrl ? (
          <img className="dish-img" src={dish.imageUrl} alt={dish.name} loading="lazy" />
        ) : (
          <div className="cuisine-emoji" aria-hidden="true">{dish.placeholder || "🍽️"}</div>
        )}
        {dish.why && <div className="why">{dish.why}</div>}
        <div className="rating-pill">
          <Star /> {dish.rating ?? "new"}
        </div>
        {sameRest && qty === 0 && <div className="card-flag in-basket">same restaurant</div>}
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
