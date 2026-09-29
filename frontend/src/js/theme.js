export function applyPalette(palette) {
  if (!palette || typeof palette !== "object") return;
  const root = document.documentElement;
  const mapping = {
    bg_base: "--sj-bg-base",
    bg_surface: "--sj-bg-surface",
    bg_card: "--sj-bg-card",
    border: "--sj-border",
    text_main: "--sj-text-main",
    text_muted: "--sj-text-muted",
    accent: "--sj-accent",
    accent_hover: "--sj-accent-hover",
    live: "--sj-live"
  };

  for (const [key, cssVar] of Object.entries(mapping)) {
    if (palette[key]) {
      root.style.setProperty(cssVar, palette[key]);
    }
  }
}

export const PALETTE_PRESETS = {
  obsidian: {
    bg_base: "#0a0c10",
    bg_surface: "#13161f",
    bg_card: "#1c202b",
    border: "#2a3040",
    text_main: "#f8fafc",
    text_muted: "#94a3b8",
    accent: "#10b981",
    accent_hover: "#059669",
    live: "#ef4444"
  },
  slate: {
    bg_base: "#0f172a",
    bg_surface: "#1e293b",
    bg_card: "#334155",
    border: "#475569",
    text_main: "#f8fafc",
    text_muted: "#94a3b8",
    accent: "#38bdf8",
    accent_hover: "#0284c7",
    live: "#f43f5e"
  },
  spotify_neon: {
    bg_base: "#121212",
    bg_surface: "#181818",
    bg_card: "#282828",
    border: "#3e3e3e",
    text_main: "#ffffff",
    text_muted: "#b3b3b3",
    accent: "#1ed760",
    accent_hover: "#1db954",
    live: "#e91429"
  },
  amber_retro: {
    bg_base: "#18130e",
    bg_surface: "#241d16",
    bg_card: "#342a20",
    border: "#4c3e30",
    text_main: "#fef3c7",
    text_muted: "#d97706",
    accent: "#f59e0b",
    accent_hover: "#d97706",
    live: "#dc2626"
  }
};
