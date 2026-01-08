import { tanstackConfig } from "@tanstack/eslint-config";
import reactPlugin from "eslint-plugin-react";
import reactCompiler from "eslint-plugin-react-compiler";
import hooksPlugin from "eslint-plugin-react-hooks";

export default [
  // Ignore config files and generated files
  {
    ignores: [
      "**/*.config.*",
      "**/worker-configuration.d.ts",
      "**/.nitro/**",
      "**/.output/**",
      "**/dist/**",
      "**/dist-types/**",
    ],
  },
  // TanStack config includes React Query, Router, Form, etc. rules
  ...tanstackConfig,
  {
    files: ["**/*.ts", "**/*.tsx"],
    plugins: {
      react: reactPlugin,
      "react-hooks": hooksPlugin,
      "react-compiler": reactCompiler,
    },
    rules: {
      ...reactPlugin.configs["jsx-runtime"].rules,
      ...hooksPlugin.configs.recommended.rules,
      "@typescript-eslint/array-type": "off",
      "sort-imports": "off",
      "import/order": "off",
    },
    languageOptions: {
      globals: {
        React: "writable",
      },
    },
  },
];
