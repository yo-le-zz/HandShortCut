/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "../src/handshortcut/webui/templates/**/*.html",
    "../src/handshortcut/webui/static/**/*.js",
  ],
  // Classes construites dynamiquement dans le JS (cat-<categorie>) : jamais purgees.
  safelist: [{ pattern: /^cat-(windows|input|media|web|files|system|logic|chip|text|edge|hover|active)$/ }],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Geist Variable", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono Variable", "ui-monospace", "monospace"],
      },
      colors: {
        background: "#0b0b0f",
        surface: "#131317",
        "surface-low": "#0e0e12",
        "surface-container": "#1b1b1f",
        "surface-high": "#232228",
        "on-surface": "#e4e1e7",
        "on-surface-variant": "#a9a2b8",
        outline: "#2d2d39",
        "outline-strong": "#494454",
        primary: "#8b5cf6",
        "primary-container": "#3c0091",
        "on-primary-container": "#e9ddff",
        accent: "#a78bfa",
        error: "#ff5c72",
        success: "#34d399",
        warning: "#fbbf24",
      },
      boxShadow: { glow: "0 8px 24px rgba(139, 92, 246, 0.15)" },
      borderRadius: { xl2: "1rem" },
    },
  },
  plugins: [],
};
