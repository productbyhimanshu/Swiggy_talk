export default function EmptyHello({ chips, onChip }) {
  return (
    <div className="bubble-row ai">
      <div className="avatar">B</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: "82%" }}>
        <div className="bubble ai">
          hey 👋 i'm <b>bhook</b> — tell me what you're craving and i'll find it.
        </div>
        {chips?.length > 0 && (
          <>
            <div className="bubble ai">try one of these or type your own:</div>
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
