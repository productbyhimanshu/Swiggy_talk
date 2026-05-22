import { useState } from "react";

export default function QuickReplies({ options, stale, onSelect }) {
  const [selected, setSelected] = useState(null);

  if (!options?.length || selected) return null;

  return (
    <div className="qr-row">
      {options.map((opt) => {
        const label = typeof opt === "string" ? opt : opt.label;
        const emoji = typeof opt === "string" ? null : opt.emoji;
        const key   = typeof opt === "string" ? opt : (opt.id ?? opt.label);
        return (
          <button
            key={key}
            className={"qr" + (stale ? " stale" : "")}
            disabled={stale}
            onClick={() => {
              if (stale) return;
              setSelected(key);
              onSelect(label);
            }}
          >
            {emoji && <span className="em">{emoji}</span>}
            {label}
          </button>
        );
      })}
    </div>
  );
}
