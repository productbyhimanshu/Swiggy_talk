import { useState, useCallback } from "react";

// Optimistic cart (architecture §9): UI updates instantly, Swiggy sync runs in
// the background via /api/cart/add | /api/cart/remove. Items carry a `synced`
// flag — sync failures keep the item local (order placement re-validates the
// real cart server-side, architecture §15), so the user is never blocked.
export function useCart(sessionId) {
  // cart: { [dishId]: { dish, qty, synced } }
  const [cart, setCart] = useState({});
  const [cartRest, setCartRest] = useState(null);
  const [pendingSwitch, setPendingSwitch] = useState(null);

  const cartCount = Object.values(cart).reduce((s, it) => s + it.qty, 0);
  const cartTotal = Object.values(cart).reduce((s, it) => s + it.dish.price * it.qty, 0);

  const syncToBackend = useCallback(
    (dish, qty) => {
      if (!sessionId) return;
      const endpoint = qty > 0 ? "/api/cart/add" : "/api/cart/remove";
      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          item: {
            id: String(dish.id),
            name: dish.name,
            price: dish.price,
            restaurant_id: String(dish.restaurantId || dish.restaurant_id || dish.id),
          },
          quantity: Math.max(qty, 0),
        }),
      })
        .then((res) => {
          setCart((prev) =>
            prev[dish.id] ? { ...prev, [dish.id]: { ...prev[dish.id], synced: res.ok } } : prev
          );
          if (!res.ok) console.warn(`cart sync ${endpoint} returned ${res.status} — item kept locally`);
        })
        .catch((err) => {
          setCart((prev) =>
            prev[dish.id] ? { ...prev, [dish.id]: { ...prev[dish.id], synced: false } } : prev
          );
          console.warn("cart sync failed — item kept locally", err);
        });
    },
    [sessionId]
  );

  const _commit = useCallback(
    (dish, qty = 1, replace = false) => {
      let nextQty = qty;
      setCart((prev) => {
        if (replace) return { [dish.id]: { dish, qty, synced: null } };
        const ex = prev[dish.id];
        nextQty = (ex?.qty || 0) + qty;
        return { ...prev, [dish.id]: { dish, qty: nextQty, synced: null } };
      });
      setCartRest(dish.restaurant);
      syncToBackend(dish, nextQty);
    },
    [syncToBackend]
  );

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
    setCart({ [dish.id]: { dish, qty: 1, synced: null } });
    setCartRest(dish.restaurant);
    // Backend flushes the old restaurant's Swiggy cart on restaurant switch
    syncToBackend(dish, 1);
  }, [pendingSwitch, syncToBackend]);

  const cancelSwitch = useCallback(() => setPendingSwitch(null), []);

  const incCart = useCallback(
    (id) => {
      const item = cart[id];
      if (!item) return;
      setCart((prev) =>
        prev[id] ? { ...prev, [id]: { ...prev[id], qty: prev[id].qty + 1, synced: null } } : prev
      );
      syncToBackend(item.dish, item.qty + 1);
    },
    [cart, syncToBackend]
  );

  const decCart = useCallback(
    (id) => {
      const item = cart[id];
      if (!item) return;
      const q = item.qty - 1;
      setCart((prev) => {
        if (!prev[id]) return prev;
        if (q <= 0) {
          const { [id]: _, ...rest } = prev;
          if (Object.keys(rest).length === 0) setCartRest(null);
          return rest;
        }
        return { ...prev, [id]: { ...prev[id], qty: q, synced: null } };
      });
      syncToBackend(item.dish, q);
    },
    [cart, syncToBackend]
  );

  const clearCart = useCallback(() => {
    Object.values(cart).forEach((it) => syncToBackend(it.dish, 0));
    setCart({});
    setCartRest(null);
  }, [cart, syncToBackend]);

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
