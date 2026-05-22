import { useState, useCallback } from "react";

export function useCart() {
  // cart: { [dishId]: { dish, qty } }
  const [cart, setCart] = useState({});
  const [cartRest, setCartRest] = useState(null);
  const [pendingSwitch, setPendingSwitch] = useState(null);

  const cartCount = Object.values(cart).reduce((s, it) => s + it.qty, 0);
  const cartTotal = Object.values(cart).reduce((s, it) => s + it.dish.price * it.qty, 0);

  const _commit = useCallback((dish, qty = 1, replace = false) => {
    setCart((prev) => {
      if (replace) return { [dish.id]: { dish, qty } };
      const ex = prev[dish.id];
      return { ...prev, [dish.id]: { dish, qty: (ex?.qty || 0) + qty } };
    });
    setCartRest(dish.restaurant);
  }, []);

  // Returns true if item was added immediately, false if switch confirmation needed
  const addToCart = useCallback(
    (dish, opts = {}) => {
      if (cartRest && cartRest !== dish.restaurant) {
        setPendingSwitch({ dish, ...opts });
        return false;
      }
      _commit(dish);
      return true;
    },
    [cartRest, _commit]
  );

  const confirmSwitch = useCallback(() => {
    if (!pendingSwitch) return;
    const { dish } = pendingSwitch;
    setPendingSwitch(null);
    setCart({ [dish.id]: { dish, qty: 1 } });
    setCartRest(dish.restaurant);
  }, [pendingSwitch]);

  const cancelSwitch = useCallback(() => setPendingSwitch(null), []);

  const incCart = useCallback((id) => {
    setCart((prev) =>
      prev[id]
        ? { ...prev, [id]: { ...prev[id], qty: prev[id].qty + 1 } }
        : prev
    );
  }, []);

  const decCart = useCallback((id) => {
    setCart((prev) => {
      if (!prev[id]) return prev;
      const q = prev[id].qty - 1;
      if (q <= 0) {
        const { [id]: _, ...rest } = prev;
        if (Object.keys(rest).length === 0) setCartRest(null);
        return rest;
      }
      return { ...prev, [id]: { ...prev[id], qty: q } };
    });
  }, []);

  const clearCart = useCallback(() => {
    setCart({});
    setCartRest(null);
  }, []);

  return {
    cart,
    cartRest,
    cartCount,
    cartTotal,
    pendingSwitch,
    addToCart,
    confirmSwitch,
    cancelSwitch,
    incCart,
    decCart,
    clearCart,
  };
}
