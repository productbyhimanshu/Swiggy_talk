import { useEffect, useState } from "react";
import { onReauthRequired } from "../../api/fetch";

// Shown as a sticky banner when any /api call returns 401 reauth_required.
// Clicking "Reconnect Swiggy" sends the user back through /auth/swiggy/login.
export default function ReconnectBanner() {
  const [show, setShow] = useState(false);

  useEffect(() => onReauthRequired(() => setShow(true)), []);

  if (!show) return null;

  return (
    <div style={bar} role="alert">
      <span>Your Swiggy session ended. Reconnect to keep ordering.</span>
      <a href="/auth/swiggy/login" style={btn}>Reconnect Swiggy</a>
    </div>
  );
}

const bar = {
  position: "fixed",
  top: 0,
  left: 0,
  right: 0,
  padding: "10px 16px",
  background: "#fff4e6",
  color: "#a85d00",
  fontSize: 13,
  fontWeight: 600,
  display: "flex",
  gap: 12,
  alignItems: "center",
  justifyContent: "center",
  flexWrap: "wrap",
  borderBottom: "1px solid #f3d9b0",
  zIndex: 10000,
  fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
};
const btn = {
  background: "#a85d00",
  color: "#fff",
  padding: "4px 12px",
  borderRadius: 999,
  textDecoration: "none",
  fontSize: 12,
};
