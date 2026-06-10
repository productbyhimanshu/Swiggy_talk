import { Pin, Close } from "../../icons/index.jsx";

/**
 * AddressSheet — bottom-sheet popup for choosing / changing delivery address.
 *
 * Works in both mobile frame (390 px) and desktop shell (1280 px):
 * - Mobile: full-width bottom sheet, slides up.
 * - Desktop: max-width 460 px, centred in the overlay.
 *
 * Props come straight from useAddress():
 *   isOpen, close, addresses, selected, loading, error, select
 */
export default function AddressSheet({ isOpen, close, addresses, selected, loading, error, select }) {
  if (!isOpen) return null;

  return (
    <div className="addr-overlay" onClick={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div className="addr-sheet" role="dialog" aria-modal="true" aria-label="Choose delivery address">

        {/* Header */}
        <div className="addr-sheet-head">
          <div className="addr-grabber" />
          <div className="addr-sheet-title">
            <Pin /> Deliver to
          </div>
          <button className="addr-close" onClick={close} aria-label="Close">
            <Close />
          </button>
        </div>

        {/* Body */}
        <div className="addr-sheet-body">

          {loading && (
            <div className="addr-state">
              <div className="addr-spinner" />
              <span>Loading your addresses…</span>
            </div>
          )}

          {error && !loading && (
            <div className="addr-state addr-state-error">{error}</div>
          )}

          {!loading && !error && addresses.length === 0 && (
            <div className="addr-state">No saved addresses found on your Swiggy account.</div>
          )}

          {!loading && addresses.map((addr) => {
            const isSelected = selected?.addressId === addr.addressId;
            return (
              <button
                key={addr.addressId}
                className={"addr-item" + (isSelected ? " selected" : "")}
                onClick={() => select(addr)}
              >
                <span className="addr-item-icon">
                  <Pin />
                </span>
                <span className="addr-item-info">
                  <span className="addr-item-label">{addr.chip || addr.label}</span>
                  <span className="addr-item-addr">{addr.address}</span>
                </span>
                {isSelected && (
                  <span className="addr-item-check">
                    <CheckIcon />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
      <path d="M5 12l5 5 9-9" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
