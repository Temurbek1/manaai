#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

for obsolete_path in \
  "$PROJECT_ROOT/admin-ui/vite.config.ts" \
  "$PROJECT_ROOT/admin-ui/index.html" \
  "$PROJECT_ROOT/admin-ui/nginx.conf" \
  "$PROJECT_ROOT/admin-ui/src/main.tsx"; do
  if [[ -e "$obsolete_path" ]]; then
    echo "Obsolete Vite runtime file remains: $obsolete_path" >&2
    exit 1
  fi
done

PROJECT_ROOT="$PROJECT_ROOT" node <<'NODE'
const path = require("node:path");
const root = process.env.PROJECT_ROOT;
if (!root) throw new Error("PROJECT_ROOT is unavailable");
const manifest = require(path.join(root, "admin-ui/package.json"));
const lock = require(path.join(root, "admin-ui/package-lock.json"));
const forbiddenPackages = new Set(["vite", "vitest", "@vitejs/plugin-react"]);
const declared = { ...manifest.dependencies, ...manifest.devDependencies };
const forbiddenDeclarations = Object.keys(declared).filter((name) => forbiddenPackages.has(name));
const forbiddenLockEntries = Object.keys(lock.packages ?? {}).filter((entry) =>
  [...forbiddenPackages].some((name) => entry === `node_modules/${name}`),
);
if (forbiddenDeclarations.length || forbiddenLockEntries.length) {
  throw new Error(
    `Vite dependencies remain: ${[...forbiddenDeclarations, ...forbiddenLockEntries].join(", ")}`,
  );
}
NODE

if rg -n "VITE_|from ['\"]vite|from ['\"]vitest" \
  "$PROJECT_ROOT/admin-ui/src" \
  "$PROJECT_ROOT/admin-ui/package.json" \
  "$PROJECT_ROOT/admin-ui/next.config.ts"; then
  echo "Vite-specific source configuration remains" >&2
  exit 1
fi

echo "Vite runtime, configuration, direct dependencies, and entry points are absent"
