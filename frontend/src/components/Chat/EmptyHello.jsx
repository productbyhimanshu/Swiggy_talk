import { useEffect, useState } from "react";

// Fetches the proactive opener — time-aware + memory-driven greeting.
// Falls back to the seed chips if the backend isn't reachable.
export default function EmptyHello({ chips, onChip }) {
  const [opener, setOpener] = useState(null);

  useEffect(() => {
    fetch("/api/opener")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => data && setOpener(data))
      .catch(() => {});
  }, []);

  const greeting =
    opener?.text ||
    "hey 👋 i'm bhook — tell me what you're craving and i'll find it.";
  const quickReplies = opener?.quick_replies || [];

  return (
    <div className="bubble-row ai">
      <div className="avatar">B</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: "82%" }}>
        <div className="bubble ai">{greeting}</div>

        {/* Proactive chips from /api/opener */}
        {quickReplies.length > 0 && (
          <div className="qr-row" style={{ paddingLeft: 0 }}>
            {quickReplies.map((text, i) => (
              <button key={i} className="qr" onClick={() => onChip(text)}>
                {text}
              </button>
            ))}
          </div>
        )}

        {/* Seed-chip suggestions (still useful when opener is generic) */}
        {chips?.length > 0 && (
          <>
            <div className="bubble ai" style={{ marginTop: 4 }}>
              or try one of these:
            </div>
            <div className="qr-row" style={{ paddingLeft: 0 }}>
              {chips.map((c, i) => (
                <button key={i} className="qr" onClick={() => onChip(c.text)}>
                  <span className="em">{c.emoji}</span>
                  {c.text}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
