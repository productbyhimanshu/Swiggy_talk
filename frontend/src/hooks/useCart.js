import { useState, useCallback, useRef } from "react";
import { apiFetch } from "../api/fetch";

// Optimistic cart (architecture §9): the UI updates instantly and the whole
// basket is mirrored to Swiggy in the background via /api/cart/sync —
// Swiggy's cart API replaces the entire cart on every update, so we always
// send everything. Items carry a `synced` flag (null = in flight, false =
// Swiggy didn't take it). The order step re-validates the real Swiggy cart
// server-side, so a failed sync never results in a wrong order.
export function useCart(sessionId) {
  // cart: { [dishId]: { dish, qty, synced } }
  const [cart, setCart] = useState({});
  const [cartRest, setCartRest] = useState(null);
  const [pendingSwitch, setPendingSwitch] = useState(null);
  const cartRef = useRef({});   // always the latest basket, even between renders
  const seq = useRef(0);        // newest sync wins; older responses are ignored

  const cartCount = Object.values(cart).reduce((s, it) => s + it.qty, 0);
  const cartTotal = Object.values(cart).reduce((s, it) => s + it.dish.price * it.qty, 0);

  const markSynced = useCallback((fn) => {
    setCart((prev) => {
      const next = Object.fromEntries(Object.entries(prev).map(([id, it]) => [id, { ...it, synced: fn(it) }]));
      cartRef.current = next;
      return next;
    });
  }, []);

  const syncToBackend = useCallback(
    (nextCart) => {
      if (!sessionId) return;
      const mySeq = ++seq.current;
      const entries = Object.values(nextCart);
      const first = entries[0]?.dish;
      apiFetch("/api/cart/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          seq: mySeq,
          restaurant_id: first ? String(first.restaurantId || first.restaurant_id || "") : null,
          restaurant_name: first?.restaurant || null,
          items: entries.map(({ dish, qty }) => ({
            id: String(dish.id),
            quantity: qty,
            price: dish.price,
            name: dish.name,
          })),
        }),
      })
        .then(async (res) => {
          if (mySeq !== seq.current) return; // a newer basket is already on its way
          const data = res.ok ? await res.json().catch(() => ({})) : {};
          if (data.stale) return;
          const missing = new Set(data.missing || []);
          markSynced((it) => res.ok && !missing.has(String(it.dish.id)));
          if (!res.ok) console.warn(`cart sync returned ${res.status} — basket kept locally`);
          else if (missing.size) console.warn("Swiggy didn't keep some items", [...missing]);
        })
        .catch((err) => {
          if (mySeq !== seq.current) return;
          markSynced(() => false);
          console.warn("cart sync failed — basket kept locally", err);
        });
    },
    [sessionId, markSynced]
  );

  const apply = useCallback(
    (next, restaurant) => {
      cartRef.current = next;
      setCart(next);
      setCartRest(restaurant);
      syncToBackend(next);
    },
    [syncToBackend]
  );

  const _commit = useCallback(
    (dish, qty = 1) => {
      const prev = cartRef.current;
      const nextQty = (prev[dish.id]?.qty || 0) + qty;
      apply({ ...prev, [dish.id]: { dish, qty: nextQty, synced: null } }, dish.restaurant);
    },
    [apply]
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
    // Sending only the new restaurant's dish replaces Swiggy's old cart.
    apply({ [dish.id]: { dish, qty: 1, synced: null } }, dish.restaurant);
  }, [pendingSwitch, apply]);

  const cancelSwitch = useCallback(() => setPendingSwitch(null), []);

  const incCart = useCallback(
    (id) => {
      const prev = cartRef.current;
      if (!prev[id]) return;
      apply({ ...prev, [id]: { ...prev[id], qty: prev[id].qty + 1, synced: null } }, cartRest);
    },
    [apply, cartRest]
  );

  const decCart = useCallback(
    (id) => {
      const prev = cartRef.current;
      if (!prev[id]) return;
      const q = prev[id].qty - 1;
      let next;
      if (q <= 0) {
        const { [id]: _removed, ...rest } = prev;
        next = rest;
      } else {
        next = { ...prev, [id]: { ...prev[id], qty: q, synced: null } };
      }
      apply(next, Object.keys(next).length ? cartRest : null);
    },
    [apply, cartRest]
  );

  const clearCart = useCallback(() => apply({}, null), [apply]);

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
