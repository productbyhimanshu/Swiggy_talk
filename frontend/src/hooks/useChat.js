import { useState, useCallback, useRef } from "react";
import { streamChat } from "./useSSE";

let _uid = 0;
const uid = () => `m${++_uid}`;

// message shapes:
//   { id, type: 'user', text }
//   { id, type: 'ai', text, quickReplies, qrConsumed }
//   { id, type: 'cards', dishes, refine }
//   { id, type: 'system', text, kind }  — kind: 'stale' | 'error'

export function useChat() {
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const sessionId = useRef(uid());

  // push returns the id of the new message so the caller can later remove
  // or update it (e.g. the placeholder "thinking" bubble).
  const push = useCallback((msg) => {
    const id = uid();
    setMessages((prev) => [...prev, { id, ...msg }]);
    return id;
  }, []);

  const consumeOlderQR = useCallback(() => {
    setMessages((prev) =>
      prev.map((m) =>
        m.quickReplies && !m.qrConsumed ? { ...m, qrConsumed: true } : m
      )
    );
  }, []);

  const sendMessage = useCallback(
    async (text) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      consumeOlderQR();
      push({ type: "user", text: trimmed });
      setIsTyping(true);
      let firstBubble = false;

      let thinkingMsgId = null;

      try {
        for await (const event of streamChat(trimmed, sessionId.current)) {
          if (event.type === "thinking") {
            // Placeholder shown immediately so the user sees activity while
            // the backend runs intent → search → menus → persona. Replaced
            // by the first real bubble.
            if (!thinkingMsgId) {
              setIsTyping(false);
              thinkingMsgId = push({ type: "ai", text: event.text, pending: true });
            }
          } else if (event.type === "bubble") {
            if (!firstBubble) {
              firstBubble = true;
              setIsTyping(false);
            }
            // Drop the placeholder once the real reply arrives.
            if (thinkingMsgId) {
              setMessages((prev) => prev.filter((m) => m.id !== thinkingMsgId));
              thinkingMsgId = null;
            }
            push({
              type: "ai",
              text: event.text,
              quickReplies: event.quick_replies?.length ? event.quick_replies : null,
            });
          } else if (event.type === "cards") {
            if (thinkingMsgId) {
              setMessages((prev) => prev.filter((m) => m.id !== thinkingMsgId));
              thinkingMsgId = null;
            }
            push({ type: "cards", dishes: event.dishes || [], refine: true });
          }
        }
      } catch {
        push({
          type: "system",
          text: "swiggy's taking a nap — try again in a sec? 😴",
          kind: "error",
        });
      } finally {
        setIsTyping(false);
      }
    },
    [push, consumeOlderQR]
  );

  const markQRConsumed = useCallback((msgId) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, qrConsumed: true } : m))
    );
  }, []);

  const reset = useCallback(() => {
    sessionId.current = uid();
    setMessages([]);
    setIsTyping(false);
  }, []);

  // Expose sessionId.current — re-read on every render so callers always
  // get the current value (changes on reset() which also triggers a re-render
  // via setMessages).
  return { messages, isTyping, sessionId: sessionId.current, sendMessage, markQRConsumed, reset };
}
