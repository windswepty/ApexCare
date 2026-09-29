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
            "react/jsx-no-undef": "error",
            // JSX 안에서 쓴 컴포넌트·아이콘을 '쓰임' 으로 센다. 이게 없으면 no-unused-vars 가
            // JSX 로만 쓰는 import 를 전부 오류로 잡아, 진짜로 안 쓰는 import 가 그 속에 묻혔다.
            "react/jsx-uses-vars": "error",
            // 자동 JSX 런타임이라 React 를 import 하지 않아도 된다. 남아 있는 import 는 오류로 보지 않는다.
            "no-unused-vars": ["error", { varsIgnorePattern: "^React$", caughtErrors: "none" }],
            "react-hooks/rules-of-hooks": "error",
            "react-hooks/exhaustive-deps": "warn"
        }
    }
];
