import { Pin } from "../../icons/index.jsx";

export default function AddressPill({ address, onClick }) {
  const label = address?.chip || address?.label || null;
  return (
    <button
      className="address-pill"
      onClick={onClick}
      title={address?.address || "Set delivery address"}
      aria-label="Change delivery address"
    >
      <span className="pin"><Pin /></span>
      {label ? (
        <>Deliver to <b>{label}</b></>
      ) : (
        <span className="address-pill-placeholder">Set delivery address</span>
      )}
      <span className="address-pill-caret">›</span>
    </button>
  );
}
