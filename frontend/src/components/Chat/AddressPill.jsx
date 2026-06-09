import { Pin } from "../../icons/index.jsx";

/**
 * AddressPill — shows the current delivery address and lets the user change it.
 *
 * Props:
 *   address  — { label, chip } from useChat().deliveryAddress, or null
 *   onClick  — called when the user taps the pill to change address
 */
export default function AddressPill({ address, onClick }) {
  const label = address?.chip || address?.label || null;

  return (
    <button
      className={"address-pill" + (onClick ? " clickable" : "")}
      onClick={onClick}
      title={address?.address || "Tap to set delivery address"}
      aria-label="Change delivery address"
    >
      <span className="pin"><Pin /></span>
      {label ? (
        <>Deliver to <b>{label}</b></>
      ) : (
        <span className="address-pill-placeholder">Set delivery address</span>
      )}
      {onClick && <span className="address-pill-caret">›</span>}
    </button>
  );
}
