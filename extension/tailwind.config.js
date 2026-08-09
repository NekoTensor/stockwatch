/** @type {import('tailwindcss').Config} */
export default {
  content: ['./popup.html', './src/**/*.{ts,tsx}'],
  darkMode: 'media', // follow the browser; the popup should match the OS theme
  theme: {
    extend: {
      fontSize: {
        // A 380px popup needs a step between text-[10px] and text-xs.
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
    },
  },
  plugins: [],
};
