import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypeScript,
  {
    files: ["vendor/bounded-braces/**/*.js"],
    // The pinned lint dependency consumes this MIT-licensed fork through CommonJS.
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
  globalIgnores([
    ".next/**",
    "coverage/**",
    "dist/**",
    "out/**",
    "src/api/schema.d.ts",
    "next-env.d.ts",
  ]),
]);
