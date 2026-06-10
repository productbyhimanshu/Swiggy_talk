import { useState, useCallback, useRef } from "react";

/**
 * Manages delivery address state for the popup picker.
 *
 * Usage:
 *   const addr = useAddress(chat.sessionId);
 *   <AddressPill address={addr.selected} onClick={addr.open} />
 *   <AddressSheet {...addr} />
 */
export function useAddress(sessionId) {
  const [isOpen, setIsOpen]       = useState(false);
  const [addresses, setAddresses] = useState([]);
  const [selected, setSelected]   = useState(null); // { addressId, label, chip, address }
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState(null);
  const fetched = useRef(false);

  const open = useCallback(async () => {
    setIsOpen(true);
    if (fetched.current) return;          // already loaded — skip fetch
    setLoading(true);
    setError(null);
    try {
      const res  = await fetch(`/api/addresses?session_id=${encodeURIComponent(sessionId)}`);
      const data = await res.json();
      setAddresses(data.addresses || []);
      fetched.current = true;
    } catch (e) {
      setError("Couldn't load addresses — check your connection.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const close = useCallback(() => setIsOpen(false), []);

  const select = useCallback(async (addr) => {
    setSelected(addr);
    setIsOpen(false);
    // Tell backend so search_restaurants can use this addressId
    try {
      await fetch("/api/set-address", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          address_id: addr.addressId,
          label:      addr.label,
          chip:       addr.chip,
          address:    addr.address,
        }),
      });
    } catch {
      // Non-fatal — address is still stored locally; sync will retry on next search
    }
  }, [sessionId]);

  // Refetch on next open (e.g. after chat.reset())
  const resetFetch = useCallback(() => {
    fetched.current = false;
    setAddresses([]);
    setSelected(null);
  }, []);

  return { isOpen, open, close, select, addresses, selected, loading, error, resetFetch };
}
