import { useState } from "react";
import ChatPanel from "./components/Chat/ChatPanel";
import DesktopShell from "./components/Layout/DesktopShell";

const DEFAULT = {
  device:  "mobile",   // "mobile" | "desktop"
  shape:   "rounded",  // "rounded" | "squircle" | "sharp"
  layout:  "carousel", // "carousel" | "stack" | "grid"
  density: "default",  // "cozy" | "default" | "compact"
};

export default function App() {
  const [cfg, setCfg] = useState(DEFAULT);
  const set = (k, v) => setCfg((prev) => ({ ...prev, [k]: v }));

  const screenProps = { shape: cfg.shape, layout: cfg.layout, density: cfg.density };

  return (
    <div className="app">
      {cfg.device === "desktop" ? (
        <DesktopShell {...screenProps} />
      ) : (
        <div className="mobile-frame">
          <ChatPanel {...screenProps} />
        </div>
      )}

      {/* Floating tweaks pill */}
      <div style={tweakBarStyle}>
        <TweakPill
          label="Device"
          options={["mobile", "desktop"]}
          value={cfg.device}
          onChange={(v) => set("device", v)}
        />
        <TweakPill
          label="Cards"
          options={["carousel", "stack", "grid"]}
          value={cfg.layout}
          onChange={(v) => set("layout", v)}
        />
        <TweakPill
          label="Bubbles"
          options={["rounded", "squircle", "sharp"]}
          value={cfg.shape}
          onChange={(v) => set("shape", v)}
        />
        <TweakPill
          label="Density"
          options={["cozy", "default", "compact"]}
          value={cfg.density}
          onChange={(v) => set("density", v)}
        />
      </div>
    </div>
  );
}

function TweakPill({ label, options, value, onChange }) {
  return (
    <div style={tweakGroupStyle}>
      <span style={tweakLabelStyle}>{label}</span>
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          style={{
            ...tweakBtnStyle,
            ...(o === value ? tweakBtnActive : {}),
          }}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

const tweakBarStyle = {
  position: "fixed",
  bottom: 20,
  left: "50%",
  transform: "translateX(-50%)",
  display: "flex",
  alignItems: "center",
  gap: 8,
  background: "oklch(0.20 0.012 60)",
  color: "#fff",
  borderRadius: 999,
  padding: "6px 10px",
  boxShadow: "0 8px 30px rgba(31,26,20,.18)",
  fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
  fontSize: 12,
  zIndex: 9999,
  flexWrap: "wrap",
  maxWidth: "calc(100vw - 40px)",
  justifyContent: "center",
};

const tweakGroupStyle = {
  display: "flex",
  alignItems: "center",
  gap: 4,
  paddingRight: 8,
  borderRight: "1px solid rgba(255,255,255,0.12)",
};

const tweakLabelStyle = {
  opacity: 0.5,
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginRight: 2,
};

const tweakBtnStyle = {
  border: "none",
  background: "rgba(255,255,255,0.08)",
  color: "rgba(255,255,255,0.7)",
  borderRadius: 999,
  padding: "4px 10px",
  fontSize: 11,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "inherit",
  transition: "all 0.15s",
};

const tweakBtnActive = {
  background: "oklch(0.62 0.20 35)",
  color: "#fff",
};
