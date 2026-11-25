"""Match Cardmarket's daily Riftbound price guide to the cards in cards.json.

Run:  python3 prices.py [site_dir]      (stdlib only; the deploy workflow runs it daily)
Writes <site_dir>/prices.json: {"updated": ..., "trend": {card id: euros}}.

Cardmarket publishes the price guide once a day and its files carry no CORS
headers, so the page can't fetch them itself. The product list has names and
expansions but no collector numbers, so cards are matched by name within the
expansion that shares the most names with each set. Alternate printings share a
name; when Cardmarket lists as many products under a name as the set has cards,
they are paired in order (collector number against product id, which follows
the order Cardmarket added them). Anything ambiguous is left without a price
rather than given a wrong one.
"""

import json
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CM = "https://downloads.s3.cardmarket.com/productCatalog"
GAME = 22  # Riftbound's game id on Cardmarket


def get_json(url, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": "riftbound-collection-prices"})
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except OSError:
            if attempt == tries:
                raise
            time.sleep(10 * attempt)


def norm(name):
    name = re.sub(r"\s*\((overnumbered|alternate art|signature)\)\s*$", "", name.lower())
    return re.sub(r"\s+", " ", name.replace(" - ", ", ")).strip()


def pair(cards, products, trend):
    """{card id: product id} for every name both sides list the same number of times."""
    ours, theirs, out = defaultdict(list), defaultdict(list), {}
    for c in cards:
        ours[norm(c["name"])].append(c)
    for p in products:
        theirs[norm(p["name"])].append(p)
    for name, cs in ours.items():
        ps = sorted(theirs.get(name, []), key=lambda p: p["idProduct"])
        if len(ps) != len(cs):
            continue
        pairs = list(zip(cs, ps))
        # Variants are rarer and dearer; a standard printing priced well above
        # one of its variants means the order-based pairing is probably swapped.
        std = [trend[p["idProduct"]] for c, p in pairs if not c["variant"] and p["idProduct"] in trend]
        var = [trend[p["idProduct"]] for c, p in pairs if c["variant"] and p["idProduct"] in trend]
        if std and var and std[0] > 2 * min(var) and std[0] - min(var) > 1:
            print(f"WARN {name}: standard printing priced above its variants; left unpriced")
            continue
        out.update({c["id"]: p["idProduct"] for c, p in pairs})
    return out


def main(site):
    data = json.loads((site / "cards.json").read_text())
    products = get_json(f"{CM}/productList/products_singles_{GAME}.json")["products"]
    guide = get_json(f"{CM}/priceGuide/price_guide_{GAME}.json")
    trend = {g["idProduct"]: g["trend"] for g in guide["priceGuides"] if g.get("trend")}

    by_exp = defaultdict(list)
    for p in products:
        by_exp[p["idExpansion"]].append(p)
    by_set = defaultdict(list)
    for c in data["cards"]:  # list order is collector order
        by_set[c["set"]].append(c)

    promo = {s["id"] for s in data["sets"] if "Promotional" in s["name"]}
    product_of, claimed = {}, set()
    for s in sorted(set(by_set) - promo, key=lambda s: -len(by_set[s])):
        names = {norm(c["name"]) for c in by_set[s]}
        overlap = lambda e: len(names & {norm(p["name"]) for p in by_exp[e]})
        exp = max((e for e in by_exp if e not in claimed), key=overlap, default=None)
        if exp is None or overlap(exp) < len(names) / 2:
            print(f"WARN {s}: no Cardmarket expansion shares half its card names; left unpriced")
            continue
        claimed.add(exp)
        product_of.update(pair(by_set[s], by_exp[exp], trend))
    # Promo cards are spread over many small expansions: match them against
    # everything the main sets didn't claim, one promo set at a time.
    rest = [p for e, ps in by_exp.items() if e not in claimed for p in ps]
    for s in sorted(promo & set(by_set)):
        got = pair(by_set[s], rest, trend)
        product_of.update(got)
        used = set(got.values())  # one product prices one card
        rest = [p for p in rest if p["idProduct"] not in used]

    prices = {cid: trend[pid] for cid, pid in product_of.items() if pid in trend}
    # Cardmarket writes the offset as +0100, which Safari's date parser rejects.
    updated = datetime.strptime(guide["createdAt"], "%Y-%m-%dT%H:%M:%S%z").isoformat()
    (site / "prices.json").write_text(json.dumps({"updated": updated, "trend": prices}, separators=(",", ":")))
    for s in by_set:
        n = sum(1 for c in by_set[s] if c["id"] in prices)
        print(f"{s}: {n}/{len(by_set[s])} priced")
    print(f"{len(prices)}/{len(data['cards'])} cards priced, guide of {updated}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "docs"))
