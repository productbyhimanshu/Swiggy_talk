import { useState } from "react";
import ChatPanel from "./components/Chat/ChatPanel";
import DesktopShell from "./components/Layout/DesktopShell";

export default function App() {
  const [device, setDevice] = useState("desktop"); // "mobile" | "desktop"

  return (
    <div className="app">
      {device === "desktop" ? (
        <DesktopShell />
      ) : (
        <div className="mobile-frame">
          <ChatPanel />
        </div>
      )}

      {/* Single device toggle, bottom-right, out of the way of cart/composer CTAs */}
      <button
        onClick={() => setDevice((d) => (d === "mobile" ? "desktop" : "mobile"))}
        aria-label={`Switch to ${device === "mobile" ? "desktop" : "mobile"} view`}
        style={deviceToggleStyle}
        title={`Currently ${device} — click to switch`}
      >
        {device === "mobile" ? "📱 mobile" : "🖥️ desktop"}
      </button>
    </div>
  );
}

const deviceToggleStyle = {
  position: "fixed",
  right: 20,
  bottom: 20,
  background: "oklch(0.20 0.012 60)",
  color: "#fff",
  border: "none",
  borderRadius: 999,
  padding: "8px 14px",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
  boxShadow: "0 6px 24px rgba(31,26,20,.20)",
  zIndex: 9999,
  letterSpacing: "0.02em",
};
