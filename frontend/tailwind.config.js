/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#F3EEE6",
        muted: "#B4B0A8",
        paper: "#3A3A40",
        canvas: "#2F2F33",
        surface: "#3A3A40",
        line: "#52525A",
        accent: "#C45C26",
        onAccent: "#FFF6EE",
        warm: "#E8A87C",
        signal: "#7EB8B0",
        danger: "#E06B63",
      },
      fontFamily: {
        vazir: ["Vazirmatn", "sans-serif"],
        sozan: ["Estedad", "Tahoma", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgb(0 0 0 / 28%), 0 10px 28px rgb(0 0 0 / 22%)",
      },
    },
  },
  plugins: [],
};
