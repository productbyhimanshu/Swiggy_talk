import QuickReplies from "./QuickReplies";

export default function MessageBubble({ message, isLastAi, onQuickReply, onQRConsumed }) {
  if (message.type === "system") {
    return (
      <div className="bubble-row system">
        <div className={"bubble system" + (message.kind === "error" ? " error" : "")}>
          <div className="row">{message.text}</div>
        </div>
      </div>
    );
  }

  if (message.type === "user") {
    return (
      <div className="bubble-row user">
        <div className="bubble user">{message.text}</div>
      </div>
    );
  }

  // ai bubble
  return (
    <div>
      <div className="bubble-row ai">
        <div className="avatar">B</div>
        <div className="bubble ai">{message.text}</div>
      </div>
      {message.quickReplies && (
        <QuickReplies
          options={message.quickReplies}
          stale={message.qrConsumed || !isLastAi}
          onSelect={(label) => {
            onQRConsumed?.(message.id);
            onQuickReply(label);
          }}
        />
      )}
    </div>
  );
}
