import { useState, useRef, useEffect } from "react";
import { useChat } from "../../hooks/useChat";
import { useCart } from "../../hooks/useCart";
import { SEED_CHIPS, COMPOSER_SEEDS } from "../../data/seed.js";
import MessageBubble from "./MessageBubble";
import TypingIndicator from "./TypingIndicator";
import EmptyHello from "./EmptyHello";
import AppBar from "./AppBar";
import AddressPill from "./AddressPill";
import Composer from "./Composer";
import SwitchSheet from "./SwitchSheet";
import DishCardList from "../Recommendations/DishCardList";
import CartBar from "../Cart/CartBar";
import BasketSheet from "../Cart/BasketSheet";

export default function ChatPanel({ shape = "rounded", layout = "carousel", density = "default" }) {
  const chat = useChat();
  const cartState = useCart();
  const [input, setInput] = useState("");
  const [basketOpen, setBasketOpen] = useState(false);
  const streamRef = useRef();

  const isEmpty = chat.messages.length === 0;

  // last AI message id (for stale QR logic)
  const lastAiId = [...chat.messages].reverse().find((m) => m.type === "ai")?.id;

  // scroll to bottom on new messages
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
    if (added) {
      chat.sendMessage(`add ${dish.name.toLowerCase()}`);
    }
  }

  function handleResuggest() {
    chat.sendMessage("re-suggest");
  }

  return (
    <div
      className="screen"
      data-shape={shape}
      data-layout={layout}
      data-density={density !== "default" ? density : undefined}
    >
      <AppBar cartCount={cartState.cartCount} onCart={() => setBasketOpen(true)} />
      <AddressPill />

      <div className="stream" ref={streamRef}>
        {isEmpty && (
          <EmptyHello
            chips={SEED_CHIPS}
            onChip={(text) => { chat.sendMessage(text); }}
          />
        )}

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

      {cartState.cartCount > 0 && !basketOpen && (
        <CartBar
          count={cartState.cartCount}
          total={cartState.cartTotal}
          restaurant={cartState.cartRest}
          onOpen={() => setBasketOpen(true)}
        />
      )}

      <Composer
        value={input}
        onChange={setInput}
        onSend={handleSend}
        disabled={chat.isTyping}
        seeds={isEmpty ? COMPOSER_SEEDS : null}
        onSeed={(text) => { chat.sendMessage(text); }}
      />

      <BasketSheet
        open={basketOpen}
        onClose={() => setBasketOpen(false)}
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
