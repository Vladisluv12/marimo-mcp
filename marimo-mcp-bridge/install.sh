#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
npx tsc -p .
npx @vscode/vsce package --no-dependencies --out dist/bridge.vsix 2>/dev/null || \
  npx vsce package --no-dependencies --out dist/bridge.vsix
code --install-extension dist/bridge.vsix --force
echo "Bridge installed. Reload VS Code window (Developer: Reload Window)."
