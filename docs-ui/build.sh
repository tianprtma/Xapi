#!/usr/bin/env bash
# Build docs UI: pre-compile JSX → bundle.js, drop babel-standalone.
#
# Usage:
#   ./docs-ui/build.sh              # production build
#   ./docs-ui/build.sh --watch      # rebuild on file change
#
# Output: docs-ui/dist/bundle.js + docs-ui/dist/index.html
# Server (main.py) auto-detects dist/ dan prefer dari source kalau ada.
#
# Requirement: npx (ships dengan Node.js).
set -euo pipefail

cd "$(dirname "$0")"

OUT="dist"
mkdir -p "$OUT"

# Bundle 4 JSX file → satu bundle.js. data.js dibuild as separate IIFE
# (deklarasi window.XDOC_DATA) supaya ke-load duluan, baru bundle.
WATCH_FLAG=""
if [[ "${1:-}" == "--watch" ]]; then
  WATCH_FLAG="--watch"
fi

# Sumber dalam urutan dependency: design-canvas → tweaks-panel → docs-app → app shell
cat > "$OUT/_entry.jsx" <<'EOF'
// Auto-generated entrypoint. Loads JSX modules dalam urutan + mounts App.
import './design-canvas.jsx';
import './tweaks-panel.jsx';
import './docs-app.jsx';

const { DocsApp } = window;

const TWEAKS = {
  accent: '#5ef38c',
  fontPair: 'plex',
  codeTheme: 'neutral',
  density: 'comfortable',
  sidebar: 'tree',
  hero: 'prompt',
};

function App() {
  return React.createElement(
    'div',
    { className: 'docs-host' },
    React.createElement(DocsApp, { variant: 'console', tweaks: TWEAKS })
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  React.createElement(App)
);
EOF

# Symlink JSX source ke dist untuk relative import.
for f in design-canvas.jsx tweaks-panel.jsx docs-app.jsx; do
  ln -sf "../$f" "$OUT/$f"
done

# Bundle dengan esbuild — JSX, no minify (buat debugging), source map inline.
echo "[build] bundling JSX..."
npx --yes esbuild "$OUT/_entry.jsx" \
  --bundle \
  --format=iife \
  --jsx=transform \
  --jsx-factory=React.createElement \
  --jsx-fragment=React.Fragment \
  --target=es2020 \
  --outfile="$OUT/bundle.js" \
  --minify \
  --sourcemap=inline \
  --define:process.env.NODE_ENV='"production"' \
  $WATCH_FLAG

# Production index.html: include React UMD + data.js + bundle.js (skip Babel).
cat > "$OUT/index.html" <<'EOF'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Xapi — X (Twitter) Cookie API · Reference</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<meta name="description" content="Mirror endpoint X API v2 lewat cookie auth_token. Reference + try-it console untuk Xapi (FastAPI)." />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
<link rel="stylesheet" href="../styles.css" />
<style>
  html, body, #root {
    width: 100%;
    height: 100%;
    margin: 0;
    background: #0b0d12;
    color: #dde2ec;
    font-family: "IBM Plex Sans", system-ui, sans-serif;
    overflow: hidden;
  }
  #root { display: flex; }
  .docs-host { flex: 1 1 auto; display: flex; min-width: 0; min-height: 0; }
</style>
</head>
<body>
<div id="root"></div>
<script crossorigin src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"></script>
<script src="../data.js"></script>
<script src="bundle.js"></script>
</body>
</html>
EOF

# Copy data.js + styles.css ke dist supaya bisa di-serve standalone juga.
cp data.js "$OUT/data.js"
cp styles.css "$OUT/styles.css"

# Update production index.html untuk reference dist-local data.js + styles.css.
sed -i.bak 's|../styles.css|styles.css|; s|../data.js|data.js|' "$OUT/index.html"
rm -f "$OUT/index.html.bak"

# Cleanup symlinks (esbuild already inlined them).
rm -f "$OUT/design-canvas.jsx" "$OUT/tweaks-panel.jsx" "$OUT/docs-app.jsx" "$OUT/_entry.jsx"

echo "[build] done. dist/bundle.js = $(du -h $OUT/bundle.js | cut -f1)"
echo "[build] mount dist/ via DOCS_UI_DIST=1 atau biarin main.py auto-detect"
