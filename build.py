"""Build the card catalogue and sprite sheets for the Riftbound collection page.

Run from anywhere:  uv run --with pillow python -I build.py [out_dir]
Re-run when a new set is released; the page needs no change.

Card data and art come from the community Riftcodex API (api.riftcodex.com),
which mirrors Riot's card gallery. The art has to ship with the site because
Riot's image CDN answers 403 to requests from other sites; it is packed into
sprite sheets so the page loads 33 files instead of one per card.
"""

import html
import io
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

API = "https://api.riftcodex.com"
TILE_W, TILE_H = 200, 279  # card art is 744x1039; same aspect
COLS, ROWS = 8, 5  # 40 cards per sheet keeps each decode under 2 MP for phones
PER_SHEET = COLS * ROWS


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "riftbound-collection-build"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_cards():
    cards, page = [], 1
    while True:
        data = get_json(f"{API}/cards?size=100&page={page}")
        cards += data["items"]
        if page >= data["pages"]:
            return cards
        page += 1


def fetch_art(url):
    # The CDN resizes on request; fit=max bounds both sides, so landscape
    # battlefields come back 279x200 and get rotated into the portrait tile.
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(f"{url}{sep}w={TILE_H}&h={TILE_H}&fit=max&fm=webp&q=90")
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                im = Image.open(io.BytesIO(r.read())).convert("RGB")
            if im.width > im.height:
                im = im.rotate(90, expand=True)
            return im.resize((TILE_W, TILE_H), Image.LANCZOS)
        except Exception as e:  # retried, then reported by the caller
            last = e
    raise last


def rules_text(text):
    """The rich text as plain lines; the page draws the :rb_...: icon codes."""
    rich = text.get("rich") or ""
    if not rich:
        return text.get("plain") or ""
    rich = re.sub(r"<li>", "\u2022 ", re.sub(r"</p>|<br\s*/?>|</li>", "\n", rich))
    return re.sub(r"\n{2,}", "\n", html.unescape(re.sub(r"<[^>]+>", "", rich))).strip()


def main(out):
    sets = get_json(f"{API}/sets")["items"]
    # Main releases first in release order, promo sets after them.
    sets.sort(key=lambda s: ("Promotional" in s["name"], s["published_on"], s["set_id"]))
    order = {s["set_id"]: i for i, s in enumerate(sets)}

    raw = fetch_cards()
    # The API carries stale copies of some cards (clean_name unset, same
    # riftbound_id as the current record): drop them. Metal promos really
    # share their base card's id and art, so they get a key suffix instead.
    curated = {c["riftbound_id"] for c in raw if c["metadata"]["clean_name"]}
    raw = [c for c in raw if c["metadata"]["clean_name"] or c["riftbound_id"] not in curated]
    for c in raw:
        c["key"] = c["riftbound_id"] + ("|metal" if c["name"].endswith("(Metal)") else "")
    raw.sort(key=lambda c: (order.get(c["set"]["set_id"], 99), c["collector_number"], c["key"]))
    keys = [c["key"] for c in raw]
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"duplicate card keys, extend the dedupe rule above: {sorted(dupes)}"

    with ThreadPoolExecutor(16) as pool:
        futures = [pool.submit(fetch_art, c["media"]["image_url"]) if c["media"].get("image_url") else None for c in raw]

    (out / "sheets").mkdir(parents=True, exist_ok=True)
    for old in (out / "sheets").glob("*.webp"):
        old.unlink()
    missing, sheet = [], None
    for i, (c, f) in enumerate(zip(raw, futures)):
        if i % PER_SHEET == 0:
            if sheet:
                sheet.save(out / "sheets" / f"{i // PER_SHEET - 1}.webp", quality=72, method=6)
            sheet = Image.new("RGB", (COLS * TILE_W, ROWS * TILE_H), (20, 22, 30))
        try:
            im = f.result() if f else None
        except Exception as e:
            im = None
            print(f"WARN no art for {c['key']}: {e}", file=sys.stderr)
        if im is None:
            missing.append(c["key"])
            continue
        p = i % PER_SHEET
        sheet.paste(im, ((p % COLS) * TILE_W, (p // COLS) * TILE_H))
    sheet.save(out / "sheets" / f"{(len(raw) - 1) // PER_SHEET}.webp", quality=72, method=6)

    def variant(c):
        # The id is more reliable than the metadata flags, which are unset on
        # newer sets: "unl-229*-219" signature, "ven-042a-166" alt art,
        # "ven-189-166" overnumbered (number above the set size).
        m, parts = c["metadata"], c["riftbound_id"].split("-")
        no = parts[1] if len(parts) == 3 else ""
        if "*" in no or m["signature"]:
            return "Signature"
        if no[-1:].isalpha() or m["alternate_art"]:
            return "Alt art"
        if (no.isdigit() and parts[2].isdigit() and int(no) > int(parts[2])) or m["overnumbered"]:
            return "Overnumbered"
        return "Metal" if c["key"].endswith("|metal") else ""

    cards = [
        {
            "id": c["key"],
            "name": c["name"],
            "set": c["set"]["set_id"],
            "no": c["riftbound_id"].split("-")[1].upper(),
            "rarity": c["classification"]["rarity"],
            "type": c["classification"]["type"],
            "domain": c["classification"]["domain"] or [],
            "variant": variant(c),
            # Deck rules: Champion units and Signature cards are tied to a
            # legend through tags; Tokens can't go in a deck.
            "super": c["classification"]["supertype"],
            "tags": c["tags"] or [],
            "cost": c["attributes"]["energy"],
            "might": c["attributes"]["might"],
            "power": c["attributes"]["power"],
            "text": rules_text(c["text"]),
            "image": c["media"].get("image_url") or "",
            "landscape": c["orientation"] == "landscape",
            "art": c["key"] not in missing,
            # The page derives sheet and slot from the card's index in this list.
        }
        for c in raw
    ]
    set_meta = [{"id": s["set_id"], "name": s["name"]} for s in sets if s["set_id"] in {c["set"] for c in cards}]
    with open(out / "cards.json", "w") as fh:
        fh.write('{"sets":' + json.dumps(set_meta) + ',"tile":[%d,%d,%d,%d],"cards":[\n' % (TILE_W, TILE_H, COLS, ROWS))
        fh.write(",\n".join(json.dumps(c, ensure_ascii=False) for c in cards))
        fh.write("\n]}\n")
    print(f"{len(cards)} cards, {len(set_meta)} sets, {-(-len(cards) // PER_SHEET)} sheets, {len(missing)} without art")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "docs"))
