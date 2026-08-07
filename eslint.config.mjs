import js from "@eslint/js";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import globals from "globals";

export default [
    js.configs.recommended,
    {
        files: ["**/*.{js,jsx}"],
        languageOptions: {
            parserOptions: {
                ecmaFeatures: { jsx: true },
                ecmaVersion: "latest",
                sourceType: "module"
            },
            globals: {
                ...globals.browser,
                ...globals.es2021
            }
        },
        plugins: {
            react: reactPlugin,
            "react-hooks": reactHooksPlugin
        },
        rules: {
            "no-undef": "error",
            "react/jsx-no-undef": "error"
        }
    }
];
