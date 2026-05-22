import DishCard from "./DishCard";
import { Refresh } from "../../icons/index.jsx";

export default function DishCardList({ dishes, cart, lockedRestaurant, onAdd, onInc, onDec, onResuggest }) {
  if (!dishes?.length) return null;
  return (
    <div className="dishes">
      <div className="dishes-header">
        <div className="label">Top {dishes.length} picks · scored for you</div>
        {onResuggest && (
          <button className="resuggest" onClick={onResuggest}>
            <Refresh /> Re-suggest
          </button>
        )}
      </div>
      <div className="dish-list">
        {dishes.map((d, i) => {
          const qty = cart?.[d.id]?.qty || 0;
          return (
            <DishCard
              key={d.id ?? i}
              dish={d}
              qty={qty}
              lockedRestaurant={lockedRestaurant}
              onAdd={() => onAdd(d)}
              onInc={() => onInc(d.id)}
              onDec={() => onDec(d.id)}
            />
          );
        })}
      </div>
    </div>
  );
}
