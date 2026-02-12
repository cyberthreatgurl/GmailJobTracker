/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "../templates/**/*.html",
    "../../tracker/templates/**/*.html",
    "../../dashboard/templates/**/*.html",
    "../../**/templates/**/*.html",
    "../../**/*.py"
  ],
  theme: {
    extend: {}
  },
  plugins: []
};
