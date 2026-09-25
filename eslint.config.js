// ESLint config for the frontend (app/static). Run: npm run lint
import js from "@eslint/js";
import globals from "globals";

export default [
  // app/static/vendor holds third-party builds (e.g. Plotly), not our code.
  { ignores: ["venv/**", "node_modules/**", "htmlcov/**", ".pytest_cache/**", "app/static/vendor/**"] },

  js.configs.recommended,

  {
    files: ["app/static/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.browser,
    },
    rules: {
      eqeqeq: ["error", "always", { null: "ignore" }], // `x != null` is the one allowed loose check
      "no-var": "error",
      "prefer-const": "error",
      "no-shadow": "error",
      "no-implicit-coercion": ["error", { allow: ["!!"] }],
      "object-shorthand": "error",
    },
  },

  {
    // This file itself runs in Node.
    files: ["eslint.config.js"],
    languageOptions: { globals: globals.node },
  },
];
