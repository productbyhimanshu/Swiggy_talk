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

  const push = useCallback((msg) =>
    setMessages((prev) => [...prev, { id: uid(), ...msg }]),
  []);

  // Mark all QR rows on older messages as consumed (stale)
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

      try {
        for await (const event of streamChat(trimmed, sessionId.current)) {
          if (event.type === "bubble") {
            if (!firstBubble) {
              firstBubble = true;
              setIsTyping(false);
            }
            push({
              type: "ai",
              text: event.text,
              quickReplies: event.quick_replies || null,
            });
          } else if (event.type === "cards") {
            push({ type: "cards", dishes: event.dishes || [], refine: true });
          }
          // cart_update handled in Phase 9
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
    setMessages([]);
    setIsTyping(false);
    sessionId.current = uid();
  }, []);

  return { messages, isTyping, sendMessage, markQRConsumed, reset };
}
