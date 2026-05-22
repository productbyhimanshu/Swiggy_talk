import { useRef, useEffect } from "react";
import { Send } from "../../icons/index.jsx";

export default function Composer({ value, onChange, onSend, disabled, seeds, onSeed }) {
  const ref = useRef();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 110) + "px";
  }, [value]);

  return (
    <div className="composer-wrap">
      {seeds?.length > 0 && (
        <div className="composer-suggest">
          {seeds.map((s, i) => (
            <button key={i} className="seed" onClick={() => onSeed?.(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      <div className="composer">
        <textarea
          ref={ref}
          rows={1}
          placeholder="tell bhook what you're craving…"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          disabled={disabled}
        />
        <button
          className="send"
          onClick={onSend}
          disabled={!value.trim() || disabled}
        >
          <Send />
        </button>
      </div>
    </div>
  );
}
