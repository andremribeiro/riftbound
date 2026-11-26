"""Checks prices.pair on the case that swapped prices: a signature (299*) and
its overnumbered twin (299) share a collector number, so collector order puts
the signature first, while Cardmarket lists them overnumbered, then signature.
Run: python3 -I test/test_prices.py (test/run.sh runs it too)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import prices  # noqa: E402

cards = [  # in collector order, as cards.json lists them
    {"id": "ogn-247-298", "name": "Kai'Sa - Daughter of the Void", "variant": ""},
    {"id": "ogn-299*-298", "name": "Kai'Sa - Daughter of the Void (Signature)", "variant": "Signature"},
    {"id": "ogn-299-298", "name": "Kai'Sa - Daughter of the Void (Overnumbered)", "variant": "Overnumbered"},
]
products = [{"idProduct": i, "name": "Kai'Sa, Daughter of the Void"} for i in (10, 11, 12)]  # standard, overnumbered, signature
got = prices.pair(cards, products, {10: 0.32, 11: 95.0, 12: 1100.0})
assert got == {"ogn-247-298": 10, "ogn-299-298": 11, "ogn-299*-298": 12}, got
print("PASS printings pair with Cardmarket products in rarity order")
