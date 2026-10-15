import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: { 0: "#111110", 1: "#1a1a19", 2: "#232321", 3: "#2e2e2b" },
        ink: { 1: "#f0efec", 2: "#c3c2b7", 3: "#8f8e86" },
        line: "#34342f",
        accent: "#3987e5",
        good: "#1baf7a",
        warn: "#eda100",
        bad: "#e66767",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
