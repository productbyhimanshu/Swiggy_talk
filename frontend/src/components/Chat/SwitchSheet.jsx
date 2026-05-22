export default function SwitchSheet({ pending, current, basketCount, onConfirm, onCancel }) {
  if (!pending) return null;
  return (
    <div className="switch-sheet-overlay" onClick={onCancel}>
      <div className="switch-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="switch-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path d="M3 12a9 9 0 0 1 15.5-6.3M21 4v5h-5M21 12a9 9 0 0 1-15.5 6.3M3 20v-5h5"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="switch-title">switch restaurants?</div>
        <div className="switch-body">
          your basket has <b>{basketCount} {basketCount === 1 ? "item" : "items"}</b> from{" "}
          <b>{current}</b>. swiggy carts are single-restaurant — adding{" "}
          <b>{pending.name.toLowerCase()}</b> from <b>{pending.restaurant}</b> will clear it.
        </div>
        <div className="switch-actions">
          <button className="ghost" onClick={onCancel}>
            keep {current?.split(" ")[0].toLowerCase()}
          </button>
          <button className="primary" onClick={onConfirm}>
            switch &amp; add
          </button>
        </div>
      </div>
    </div>
  );
}
