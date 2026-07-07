/** @type {import('tailwindcss').Config} */
module.exports = {
  // <html class="dark"> — pakai strategi class (bukan prefers-color-scheme).
  darkMode: 'class',
  // index.html memuat markup + JS inline; semua nama class utuh ada di file ini.
  content: ['./static/**/*.html'],
  theme: {
    extend: {},
  },
  plugins: [],
};
