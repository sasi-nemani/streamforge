/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        chalk: '#FAFAFA',
        jet: '#1A1A1A',
        tier1: '#10B981',  // Green - Info
        tier2: '#F59E0B',  // Amber - Warning
        tier3: '#EF4444',  // Red - Critical
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
