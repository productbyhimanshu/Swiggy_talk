import { useRef, useEffect, useState } from "react";
import { useChat } from "../../hooks/useChat";
import { useCart } from "../../hooks/useCart";
import { SEED_CHIPS, COMPOSER_SEEDS } from "../../data/seed.js";
import { Pin, Refresh } from "../../icons/index.jsx";
import MessageBubble from "../Chat/MessageBubble";
import TypingIndicator from "../Chat/TypingIndicator";
import EmptyHello from "../Chat/EmptyHello";
import Composer from "../Chat/Composer";
import SwitchSheet from "../Chat/SwitchSheet";
import DishCardList from "../Recommendations/DishCardList";
import DesktopCart from "../Cart/DesktopCart";

export default function DesktopShell({ shape = "rounded", layout = "carousel", density = "default" }) {
  const chat = useChat();
  const cartState = useCart();
  const [input, setInput] = useState("");
  const streamRef = useRef();

  const isEmpty = chat.messages.length === 0;
  const lastAiId = [...chat.messages].reverse().find((m) => m.type === "ai")?.id;

  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.messages, chat.isTyping]);

  function handleSend() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    chat.sendMessage(text);
  }

  function handleAdd(dish) {
    const added = cartState.addToCart(dish);
    if (added) chat.sendMessage(`add ${dish.name.toLowerCase()}`);
  }

  function handleResuggest() {
    chat.sendMessage("re-suggest");
  }

  function handleReset() {
    chat.reset();
    cartState.clearCart();
  }

  return (
    <div className="desktop-shell">
      {/* Rail */}
      <div className="ds-rail">
        <div className="brand">
          <div className="crest">B</div>
          <div>
            <div className="name">bhook</div>
            <div className="tag">talk yourself fed</div>
          </div>
        </div>

        <div className="rail-card">
          <div className="rail-card-label"><Pin /> delivering to</div>
          <div className="rail-card-title">Home</div>
          <div className="rail-card-sub">Indiranagar, 12th Main · 560038</div>
          <button className="rail-link">change address →</button>
        </div>

        <div className="sec-label">try one of these</div>
        <div className="seed-chips">
          {SEED_CHIPS.map((c, i) => (
            <button key={i} className="seed-chip" onClick={() => chat.sendMessage(c.text)}>
              <span className="em">{c.emoji}</span>
              {c.text}
            </button>
          ))}
        </div>

        <div className="rail-foot">
          <div className="session-line">
            <span className="dot live" />
            <span>session active · 30 min before refresh</span>
          </div>
          <button className="new-chat" onClick={handleReset}>
            <Refresh /> start a new chat
          </button>
        </div>
      </div>

      {/* Chat pane */}
      <div
        className="ds-chat"
        data-shape={shape}
        data-layout={layout}
        data-density={density !== "default" ? density : undefined}
      >
        <div className="ds-bar">
          <div className="title">bhook</div>
          <div className="subtitle">talk yourself fed</div>
          <div className="tag"><span className="live" />online</div>
        </div>
        <div className="stream" ref={streamRef}>
          {isEmpty && <EmptyHello chips={null} onChip={chat.sendMessage} />}
          {chat.messages.map((msg) => {
            if (msg.type === "cards") {
              return (
                <DishCardList
                  key={msg.id}
                  dishes={msg.dishes}
                  cart={cartState.cart}
                  lockedRestaurant={cartState.cartRest}
                  onAdd={handleAdd}
                  onInc={cartState.incCart}
                  onDec={cartState.decCart}
                  onResuggest={msg.refine ? handleResuggest : null}
                />
              );
            }
            return (
              <MessageBubble
                key={msg.id}
                message={msg}
                isLastAi={msg.id === lastAiId}
                onQuickReply={(label) => {
                  chat.markQRConsumed(msg.id);
                  chat.sendMessage(label);
                }}
                onQRConsumed={chat.markQRConsumed}
              />
            );
          })}
          {chat.isTyping && <TypingIndicator />}
        </div>
        <Composer
          value={input}
          onChange={setInput}
          onSend={handleSend}
          disabled={chat.isTyping}
          seeds={isEmpty ? COMPOSER_SEEDS : null}
          onSeed={chat.sendMessage}
        />
      </div>

      {/* Cart sidebar */}
      <DesktopCart
        cart={cartState.cart}
        restaurant={cartState.cartRest}
        incCart={cartState.incCart}
        decCart={cartState.decCart}
      />

      {cartState.pendingSwitch && (
        <SwitchSheet
          pending={cartState.pendingSwitch.dish}
          current={cartState.cartRest}
          basketCount={cartState.cartCount}
          onConfirm={() => {
            const dish = cartState.pendingSwitch.dish;
            cartState.confirmSwitch();
            chat.sendMessage(`add ${dish.name.toLowerCase()}`);
          }}
          onCancel={cartState.cancelSwitch}
        />
      )}
    </div>
  );
}
