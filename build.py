"""Build the card catalogue and sprite sheets for the Riftbound collection page.

Run from anywhere:  uv run --with pillow python -I build.py [out_dir]
Re-run when a new set is released; the page needs no change.

Card data and art come from the community Riftcodex API (api.riftcodex.com),
which mirrors Riot's card gallery. The art has to ship with the site because
Riot's image CDN answers 403 to requests from other sites; it is packed into
sprite sheets so the page loads 33 files instead of one per card.
"""

import hashlib
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
    rich = re.sub(r"<li>", "\u2022 ", re.sub(r"</p>|<br\s*/?>|</li>", "\n", rich.replace("\r", "")))
    return re.sub(r"\n{2,}", "\n", html.unescape(re.sub(r"<[^>]+>", "", rich))).strip()


GALLERY = "https://playriftbound.com/en-us/card-gallery/"


def parse_gallery(page, skip_sets):
    """Cards from Riot's own card gallery page, shaped like Riftcodex records,
    for the sets Riftcodex doesn't carry yet (Radiance, when this was written).

    The gallery has no supertype, so it comes from tags: a unit named after one
    of its own tags is a champion unit (Jinx, tagged Jinx), which also gives the
    set of champion names; any other non-legend card tagged with a champion is
    a Signature card (Super Mega Death Rocket!, tagged Jinx). Legend tags can't
    serve: some are tribes (Yordle) and some champions have no legend. Tokens
    are made by effects, never played, so they have no energy cost. Checked against Riftcodex on the sets both have: 928 cards, all
    agree but one whose gallery tags are wrong.
    """
    data = json.loads(re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S).group(1))

    def find(x):  # the card list is the one whose records carry a publicCode
        if isinstance(x, list) and x and isinstance(x[0], dict) and "publicCode" in x[0]:
            return x
        for v in x.values() if isinstance(x, dict) else x if isinstance(x, list) else []:
            if (found := find(v)) is not None:
                return found
        return None

    items = find(data)
    assert items, "the card gallery's layout changed: no card list found"
    num = lambda c, k: c[k]["value"]["id"] if k in c else None
    def types_of(c):  # some new cards lack a type; their image description names it ("Riftbound Spell: ...")
        types = [t["label"] for t in c["cardType"]["type"]]
        m = re.match(r"Riftbound ([A-Za-z]+)\b", c["cardImage"].get("accessibilityText", ""))
        return types or ([m.group(1)] if m else [])
    tags_of = lambda c: c.get("tags", {}).get("tags", [])
    token = lambda c: types_of(c)[:1] in ([], ["Unit"], ["Gear"], ["Spell"]) and "energy" not in c
    champions = {c["name"] for c in items if types_of(c)[:1] == ["Unit"] and c["name"] in tags_of(c) and not token(c)}
    cards, sets = [], {}
    for c in items:
        set_id, set_name = c["set"]["value"]["id"], c["set"]["value"]["label"]
        if set_id in skip_sets:
            continue
        sets[set_id] = set_name
        types, tags, sub = types_of(c), tags_of(c), c.get("subtitle")
        champ = [t for t in tags if t in champions]
        if token(c):
            supertype = "Token"
        elif types[0] == "Unit" and c["name"] in tags:
            supertype = "Champion"
        elif types[0] != "Legend" and champ:
            supertype = "Signature"
        else:
            supertype = None
        # Name champion cards "Champion, Title" whichever way round the gallery splits them.
        if sub and c["name"] in champions:
            name = f"{c['name']}, {sub}"
        elif sub and sub in champions and supertype != "Signature":
            name = f"{sub}, {c['name']}"
        elif not sub and champ and (types[:1] == ["Legend"] or supertype == "Champion") and c["name"] not in champions:
            name = f"{champ[0]}, {c['name']}"
        else:
            name = c["name"]
        cards.append({
            "riftbound_id": c["id"], "name": name, "collector_number": c["collectorNumber"], "tags": tags,
            "attributes": {"energy": num(c, "energy"), "might": num(c, "might"), "power": num(c, "power")},
            "classification": {"type": types[0] if types else "Unit", "supertype": supertype,
                               "rarity": c["rarity"]["value"]["label"], "domain": [d["label"] for d in c["domain"]["values"]]},
            "text": {"rich": c.get("text", {}).get("richText", {}).get("body", ""), "plain": ""},
            "set": {"set_id": set_id, "label": set_name},
            "media": {"image_url": c["cardImage"]["url"]},
            "orientation": c["orientation"],
            "metadata": {"clean_name": name, "alternate_art": False, "overnumbered": False, "signature": False},
        })
    return cards, sets


def official_cards(skip_sets):
    req = urllib.request.Request(GALLERY, headers={"User-Agent": "Mozilla/5.0 (riftbound-collection-build)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return parse_gallery(r.read().decode("utf-8"), skip_sets)


TCG = "https://tcgcsv.com/tcgplayer/89"  # TCGplayer's Riftbound catalogue, mirrored daily by tcgcsv.com
IMPLIED = {"signature", "overnumbered", "alternate art"}  # labels the collector number already encodes


def tcg_cards(known_ids, known_tcg):
    """Printings TCGplayer lists that neither Riftcodex nor Riot's gallery has:
    some sets' runes and tokens, signature legends, tournament promos (Top 8,
    Champion), oversized cards and small releases. Ids follow Riftcodex's
    pattern (set-number[-total]), so a card Riftcodex adds later keeps its id;
    a printing label the number doesn't encode ("Oversized", "Top 8") is
    appended the way Riftcodex appends "|metal"."""
    ext = lambda p: {e["name"]: e["value"] for e in p.get("extendedData", [])}
    cards, sets, used = [], {}, set(known_ids)
    for g in get_json(f"{TCG}/groups")["results"]:
        abbr = re.sub(r"[^A-Z0-9]", "", g["abbreviation"].upper())
        for p in get_json(f"{TCG}/{g['groupId']}/products")["results"]:
            e = ext(p)
            if not e.get("Number") or str(p["productId"]) in known_tcg:
                continue  # sealed product, or a card Riftcodex already has
            front, _, back = e["Number"].lower().replace(" ", "").partition("//")  # double-sided tokens: "t01//t05"
            n, _, total = front.partition("/")
            m = re.match(r"(.*?)\s*\(([^)]*)\)\s*$", p["name"])
            name, label = (m.group(1), m.group(2)) if m else (p["name"], "")
            if label.lower() == n or label.lower() in IMPLIED:
                label = ""  # "Fury Rune (R01a)", "(Signature)": already in the number
            key = f"{abbr.lower()}-{n}" + (f"-{total}" if total else "") + (f"-{back}" if back else "")
            if label:
                key += "|" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
            elif key in known_ids:
                continue  # the same card, just without a TCGplayer id on our side
            if key in used:
                key += f"|tcg{p['productId']}"
            used.add(key)
            types = e.get("Card Type", "")
            kind = next((t for t in ("Legend", "Battlefield", "Rune", "Unit", "Spell", "Gear") if t in types), "Unit")
            supertype = ("Token" if "Token" in types else "Champion" if "Champion" in types
                         else "Signature" if "Signature" in types else "Basic" if kind == "Rune" else None)
            num = lambda k: int(e[k]) if e.get(k, "").isdigit() else None
            playable = kind in ("Unit", "Spell", "Gear")
            cards.append({
                "riftbound_id": key.split("|")[0], "key": key, "name": name,
                "collector_number": int(re.sub(r"\D", "", n) or 0),
                "tags": [t for t in e.get("Tag", "").split(";") if t],
                "attributes": {"energy": num("Energy Cost") if playable else None,
                               "might": num("Might") if kind == "Unit" else None, "power": num("Power Cost") or None},
                "classification": {"type": kind, "supertype": supertype, "rarity": e.get("Rarity", "Promo"),
                                   "domain": [d for d in e.get("Domain", "").split(";") if d and d != "None"] or ["Colorless"]},
                "text": {"rich": e.get("Description", ""), "plain": ""},
                "set": {"set_id": abbr, "label": g["name"]},
                "media": {"image_url": p["imageUrl"].replace("_200w.jpg", "_in_1000x1000.jpg")},
                "orientation": "landscape" if kind == "Battlefield" else "portrait",
                "metadata": {"clean_name": name, "alternate_art": False, "overnumbered": False, "signature": False, "label": label},
            })
            sets[abbr] = {"set_id": abbr, "name": g["name"], "published_on": g["publishedOn"][:10], "main": False}
    return cards, sets


def main(out):
    sets = get_json(f"{API}/sets")["items"]
    for s in sets:
        s["main"] = "Promotional" not in s["name"]
    raw = fetch_cards()
    # Card ids stay Riftcodex's, so saved collections keep matching; Riot's
    # gallery only fills in sets Riftcodex hasn't added yet.
    extra, extra_sets = official_cards({s["set_id"] for s in sets})
    raw += extra
    # A set only in the gallery has no release date here; it sorts after the known ones.
    sets += [{"set_id": k, "name": v, "published_on": "9999", "main": True} for k, v in extra_sets.items()]
    print(f"from Riot's gallery: {len(extra)} cards in {', '.join(extra_sets) or 'no new sets'}")

    # The API carries stale copies of some cards (clean_name unset, same
    # riftbound_id as the current record): drop them. Metal promos really
    # share their base card's id and art, so they get a key suffix instead.
    curated = {c["riftbound_id"] for c in raw if c["metadata"]["clean_name"]}
    known_tcg = {str(c["tcgplayer_id"]) for c in raw if c.get("tcgplayer_id")}
    raw = [c for c in raw if c["metadata"]["clean_name"] or c["riftbound_id"] not in curated]
    for c in raw:
        c["key"] = c["riftbound_id"] + ("|metal" if c["name"].endswith("(Metal)") else "")
    more, more_sets = tcg_cards({c["key"] for c in raw}, known_tcg)
    raw += more
    sets += [s for k, s in more_sets.items() if k not in {x["set_id"] for x in sets}]
    print(f"from TCGplayer: {len(more)} printings missing elsewhere")
    # Main releases first in release order; promos and small releases after them.
    sets.sort(key=lambda s: (not s["main"], s["published_on"], s["set_id"]))
    order = {s["set_id"]: i for i, s in enumerate(sets)}
    # Numbered cards first, then the ones whose number has a prefix, grouped by
    # it (runes r01, spirits sp1, tokens t03); a signature (229*) after its
    # overnumbered twin (229).
    prefix = lambda c: re.match(r"[a-z]*", c["riftbound_id"].split("-")[1]).group(0)
    raw.sort(key=lambda c: (order.get(c["set"]["set_id"], 99), prefix(c), c["collector_number"], "*" in c["riftbound_id"], c["key"]))
    keys = [c["key"] for c in raw]
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"duplicate card keys, extend the dedupe rule above: {sorted(dupes)}"

    with ThreadPoolExecutor(16) as pool:
        futures = [pool.submit(fetch_art, c["media"]["image_url"]) if c["media"].get("image_url") else None for c in raw]

    images = []
    for c, f in zip(raw, futures):
        try:
            images.append(f.result() if f else None)
        except Exception as e:  # TCGplayer has no picture yet for some new or promo printings (403)
            images.append(None)
            print(f"WARN no art for {c['key']}: {e}", file=sys.stderr)
    # A printing without a picture borrows one from another printing of the same
    # card, same set first: promo stamps (Top 8, Prize Wall) reuse the base art.
    # The page says where the picture came from.
    name_key = lambda c: re.sub(r"\s*\((overnumbered|alternate art|signature|metal)\)\s*$", "", c["name"].lower()).replace(" - ", ", ")
    donors = {}
    for i, c in enumerate(raw):
        if images[i] is not None:
            donors.setdefault((c["set"]["set_id"], name_key(c)), i)
            donors.setdefault(name_key(c), i)
    art_from = {}
    for i, c in enumerate(raw):
        if images[i] is None:
            d = donors.get((c["set"]["set_id"], name_key(c)), donors.get(name_key(c)))
            if d is not None:
                images[i], art_from[c["key"]] = images[d], raw[d]
    missing = [c["key"] for c, im in zip(raw, images) if im is None]

    (out / "sheets").mkdir(parents=True, exist_ok=True)
    for old in (out / "sheets").glob("*.webp"):
        old.unlink()
    for first in range(0, len(raw), PER_SHEET):
        sheet = Image.new("RGB", (COLS * TILE_W, ROWS * TILE_H), (20, 22, 30))
        for p, im in enumerate(images[first:first + PER_SHEET]):
            if im is not None:
                sheet.paste(im, ((p % COLS) * TILE_W, (p // COLS) * TILE_H))
        sheet.save(out / "sheets" / f"{first // PER_SHEET}.webp", quality=72, method=6)

    def variant(c):
        # The id is more reliable than the metadata flags, which are unset on
        # newer sets: "unl-229*-219" signature, "ven-042a-166" alt art,
        # "ven-189-166" overnumbered (number above the set size).
        # Runes and specials have no total ("sfd-r06a"); their letter suffix still marks the alt art.
        m, parts = c["metadata"], c["riftbound_id"].split("-")
        no, total = parts[1], parts[2] if len(parts) == 3 else ""
        if "*" in no or m["signature"]:
            return "Signature"
        if no[-1:].isalpha() or m["alternate_art"]:
            return "Alt art"
        if (no.isdigit() and total.isdigit() and int(no) > int(total)) or m["overnumbered"]:
            return "Overnumbered"
        return "Metal" if c["key"].endswith("|metal") else m.get("label", "")

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
            "image": (art_from[c["key"]]["media"]["image_url"] if c["key"] in art_from else c["media"].get("image_url")) or "",
            "landscape": c["orientation"] == "landscape",
            "art": c["key"] not in missing,
            **({"artFrom": art_from[c["key"]]["key"]} if c["key"] in art_from else {}),
            # The page derives sheet and slot from the card's index in this list.
        }
        for c in raw
    ]
    set_meta = [{"id": s["set_id"], "name": s["name"], "main": s["main"]} for s in sets if s["set_id"] in {c["set"] for c in cards}]
    with open(out / "cards.json", "w") as fh:
        # The page adds the build id to sheet URLs, so a phone never pairs new card data with cached old sheets.
        build_id = hashlib.sha1("\n".join(c["id"] for c in cards).encode()).hexdigest()[:10]
        fh.write('{"build":"%s","sets":' % build_id + json.dumps(set_meta) + ',"tile":[%d,%d,%d,%d],"cards":[\n' % (TILE_W, TILE_H, COLS, ROWS))
        fh.write(",\n".join(json.dumps(c, ensure_ascii=False) for c in cards))
        fh.write("\n]}\n")
    print(f"{len(cards)} cards, {len(set_meta)} sets, {-(-len(cards) // PER_SHEET)} sheets, "
          f"{len(art_from)} showing another printing's art, {len(missing)} without art")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "docs"))
