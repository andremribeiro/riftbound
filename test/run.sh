#!/usr/bin/env bash
# Runs the page's sync logic against an in-memory Supabase stand-in in headless
# Chromium and prints PASS/FAIL lines. Needs Playwright's chromium headless shell
# (pnpm dlx playwright install chromium-headless-shell) and python3.
set -u
here=$(cd "$(dirname "$0")" && pwd); site="$here/../docs"; tmp=$(mktemp -d); port=8766
trap 'kill "$srv" 2>/dev/null; rm -rf "$tmp"' EXIT
ln -s "$site/cards.json" "$tmp/cards.json"; ln -s "$site/sheets" "$tmp/sheets"; ln -s "$site/prices.json" "$tmp/prices.json"
cp "$here/fake-supabase.js" "$here/sync-test.js" "$tmp/"
# Swap the CDN client for the fake (dropping its integrity line), point the page at it, append the test.
sed -e '/supabase-js@/,/<\/script>/c\<script src="fake-supabase.js"></script>' \
    -e 's#^const SUPABASE_URL = ".*";#const SUPABASE_URL = "fake";#' \
    -e 's#^</body>#<script src="sync-test.js"></script></body>#' "$site/index.html" > "$tmp/index.html"
python3 -m http.server "$port" --bind 127.0.0.1 --directory "$tmp" >/dev/null 2>&1 & srv=$!
sleep 1
shell=$(ls -d ~/.cache/ms-playwright/chromium_headless_shell-*/*/headless_shell | tail -1)
out=$(for page in "" "?nodecks" "?restart#deck-33333333-3333-4333-8333-333333333333"; do
  "$shell" --no-sandbox --virtual-time-budget=30000 --dump-dom "http://127.0.0.1:$port/$page" 2>/dev/null | sed -n '/<pre id="result">/,/<\/pre>/p' | sed 's/<[^>]*>//g'
done)
echo "$out"
[ -n "$out" ] && ! grep -q '^FAIL' <<<"$out"
