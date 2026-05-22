import { Star, Clock, Plus } from "../../icons/index.jsx";

export default function DishCard({ dish, qty, lockedRestaurant, onAdd, onInc, onDec }) {
  const switches = lockedRestaurant && dish.restaurant !== lockedRestaurant;
  const sameRest  = lockedRestaurant && dish.restaurant === lockedRestaurant;
  const eta = dish.eta ?? dish.deliveryTime ?? "—";

  return (
    <div className={"dish-card" + (switches ? " switches" : "")}>
      <div className="img">
        <div className="stripe" />
        <div className="placeholder">{dish.placeholder || dish.name}</div>
        {dish.why && <div className="why">{dish.why}</div>}
        <div className="rating-pill">
          <Star /> {dish.rating}
        </div>
        {sameRest && qty === 0 && <div className="card-flag in-basket">in your basket</div>}
        {switches && <div className="card-flag switches-cart">switches basket</div>}
      </div>
      <div className="body">
        <div className="name-row">
          <span className={"veg-dot" + (dish.veg ? "" : " nonveg")} />
          <span>{dish.name}</span>
        </div>
        <div className="rest">
          <span>{dish.restaurant}</span>
          <span>·</span>
          <span className="eta"><Clock /> {eta} min</span>
        </div>
        <div className="footer-row">
          <div className="price">
            {dish.mrp && <span className="strike">₹{dish.mrp}</span>}
            ₹{dish.price}
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
