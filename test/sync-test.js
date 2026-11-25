const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Headless Chromium may report the page as hidden; the resume handler needs "visible".
Object.defineProperty(document, "visibilityState", { get: () => "visible", configurable: true });
const resume = () => document.dispatchEvent(new Event("visibilitychange"));

// A legal deck built from the real card data, so checkDeck is tested on real cards.
function legalDeck() {
  const reps = Object.values(firstOf);
  for (const L of reps.filter((c) => c.type === "Legend" && c.tags.length)) {
    const champ = reps.find((c) => isChampionFor(c, L) && !BANNED.has(nameKey(c.name)));
    if (!champ) continue;
    const ok = (c) => allowedIn(c, L) && !BANNED.has(nameKey(c.name)) && c !== champ;
    const main = reps.filter((c) => ok(c) && MAIN_TYPES.has(c.type) && c.super !== "Signature" && !isChampionFor(c, L)).slice(0, 13);
    const rune = reps.find((c) => ok(c) && c.type === "Rune");
    const fields = reps.filter((c) => ok(c) && c.type === "Battlefield").slice(0, 3);
    if (main.length < 13 || !rune || fields.length < 3) continue;
    return { L, champ, deck: { id: "t", name: "Test", legend: L.id, champion: champ.id,
      cards: Object.fromEntries([...main.map((c) => [c.id, 3]), [rune.id, 12], ...fields.map((c) => [c.id, 1])]) } };
  }
  throw new Error("no legend in the data can make a legal test deck");
}

(async () => {
  const out = [], ok = (name, cond) => out.push((cond ? "PASS " : "FAIL ") + name);
  try {
    while (!cards.length) await sleep(100);  // cards.json is real I/O, not virtual time
    await sleep(300);
    const c = byId["ogn-001-298"], add = c.t.add;
    const server = () => __db.find((r) => r.card_id === c.id)?.n;
    const queued = () => JSON.parse(localStorage.getItem("rb-pending") || "{}");
    const removeOne = () => { c.t.tile.querySelector(".art").click(); $("#card-body .stepper button").click(); $("#card").close(); };

    if (location.search.includes("nodecks")) {
      $("#email").value = "me@example.com"; $("#password").value = "pw"; $("#login").requestSubmit();
      await sleep(1000);
      add.click();
      await sleep(1000);
      ok("a missing decks table doesn't stop the collection saving", server() === 3 && editable());
      location.hash = "decks"; await sleep(100);
      ok("with no decks table, New deck is off and the reason is shown", $("#new-deck").disabled && !$("#no-decks").hidden
        && $("#no-decks").textContent.includes("public.decks"));
    } else if (location.search.includes("restart")) {
      await sleep(1000);
      ok("a deck link opened before the decks load shows the deck", location.hash === "#deck-33333333-3333-4333-8333-333333333333"
        && !$("#view-deck").hidden && $("#deck-name").value === "Linked deck");
      __recover(); await sleep(50);
      ok("a reset link opens the new-password form", !$("#login").hidden && $("#email").hidden && $("#login-go").textContent === "Save password");
      $("#password").value = "evenlonger"; $("#login").requestSubmit(); await sleep(100);
      ok("the new password is saved and the form closes", __newPassword === "evenlonger" && $("#login").hidden);
      ok("a change queued before closing the app saves on the next start", server() === 5 && qty(c) === 5 && !Object.keys(queued()).length);
    } else {
      // Deck rules on real cards
      const { L, champ, deck } = legalDeck();
      const chk = (d) => checkDeck(d);
      ok("a 40-card deck with 12 runes and 3 battlefields is legal", chk(deck).legal && chk(deck).main === 40);
      const four = structuredClone(deck); four.cards[Object.keys(deck.cards)[0]] = 4;
      ok("four copies of one card is flagged", chk(four).issues.some((t) => t.includes("limit is 3")));
      const outside = Object.values(firstOf).find((x) => x.type === "Unit" && !fitsDomains(x, L));
      const off = structuredClone(deck); off.cards[outside.id] = 1;
      ok("a card outside the legend's domains is flagged", chk(off).issues.some((t) => t.includes("is outside")));
      const runeId = Object.keys(deck.cards).find((id) => byId[id].type === "Rune");
      const shortRunes = structuredClone(deck); shortRunes.cards[runeId] = 11;
      ok("11 runes is flagged", chk(shortRunes).issues.some((t) => t.includes("exactly 12")));
      const fieldId = Object.keys(deck.cards).find((id) => byId[id].type === "Battlefield");
      const twice = structuredClone(deck); twice.cards[fieldId] = 2;
      ok("a repeated battlefield is flagged", chk(twice).issues.some((t) => t.includes("all be different")));
      const otherSig = Object.values(firstOf).find((x) => x.super === "Signature" && !x.tags.some((t) => L.tags.includes(t)));
      const sig = structuredClone(deck); sig.cards[otherSig.id] = 1;
      ok("another champion's Signature card is flagged", chk(sig).issues.some((t) => t.includes("another champion")));
      const noChamp = structuredClone(deck); noChamp.champion = null;
      ok("a deck without a Chosen Champion is flagged", chk(noChamp).issues.some((t) => t.includes("Chosen Champion")));

      ok("signed-out view is read-only", document.body.classList.contains("ro") && !$("#login").hidden);
      const mode = (m) => document.querySelector(`.login-alt [data-mode="${m}"]`).click();
      mode("signup"); $("#email").value = "new@example.com"; $("#password").value = "longenough"; $("#login").requestSubmit();
      await sleep(100);
      ok("Create account signs up and asks to confirm by email", __signups.includes("new@example.com")
        && $("#status").textContent.includes("confirmation link") && $("#login-go").textContent === "Sign in");
      mode("reset");
      ok("the reset form asks only for an email", $("#password").hidden && !$("#email").hidden);
      $("#email").value = "me@example.com"; $("#login").requestSubmit();
      await sleep(100);
      ok("Forgot password sends a reset link", __resets.includes("me@example.com") && $("#status").textContent.includes("on its way"));
      $("#email").value = "me@example.com"; $("#password").value = "pw"; $("#login").requestSubmit();
      await sleep(10);
      add.click();
      await sleep(1000);
      ok("taps before the first load on a new device are ignored", qty(c) === 2 && server() === 2 && __calls === 0);
      ok("loads all 1201 saved rows across 1000-row pages", Object.keys(saved).length === 1201);

      add.click(); add.click(); add.click();
      await sleep(1000);
      ok("three quick taps saved in one request", __calls === 1 && server() === 5);
      ok("the tile shows the count", c.t.qty.textContent === "5" && !c.t.tile.classList.contains("missing"));
      ok("the shown count follows taps", $("#count").textContent.endsWith(", 1 owned"));

      add.click(); await sleep(620); add.click();  // second tap lands while the first save is in flight
      await sleep(1000);
      ok("a tap during a save is not lost", server() === 7 && qty(c) === 7 && !Object.keys(queued()).length);

      removeOne();
      await sleep(1000);
      ok("the card sheet removes a copy", server() === 6);
      c.t.tile.querySelector(".art").click();
      const link = document.querySelector('#card-body a[href*="cardmarket.com"]');
      const term = (a) => new URL(a.href).searchParams.get("searchString");
      ok("the card sheet links to a Cardmarket search for the card", term(link) === "Blazing Scorcher" && link.target === "_blank");
      $("#card").close();
      const legend = Object.values(firstOf).find((x) => x.type === "Legend" && x.name.includes(" - "));
      openCard(legend);
      ok("legend names are searched the way Cardmarket writes them",
        term(document.querySelector('#card-body a[href*="cardmarket.com"]')) === plainName(legend).replace(/ - /g, ", ") && !term(document.querySelector('#card-body a[href*="cardmarket.com"]')).includes(" - "));
      $("#card").close();

      __latency = 700;  // a slow load; the save below would finish first without serialising
      resume(); await sleep(10); add.click();
      await sleep(4000);
      __latency = 50;
      ok("a load running during a save doesn't bring back old counts", server() === 7 && qty(c) === 7);

      __fail = true; add.click();
      await sleep(1000);
      ok("a failed save keeps the change on the device and says so", queued()[c.id] === 8 && server() === 7 && $("#status").classList.contains("err"));
      __fail = false; resume();
      await sleep(500);
      ok("the queued change saves when the app comes back", server() === 8 && !Object.keys(queued()).length);

      // Deck builder flow
      location.hash = "decks"; await sleep(100);
      $("#new-deck").click(); await sleep(100);
      const id = location.hash.slice(6);
      ok("New deck opens the legend picker", location.hash.startsWith("#deck-") && !$("#legend-pick").hidden);
      document.querySelector(`#legend-grid .art[data-id="${L.id}"]`).click(); await sleep(50);
      ok("picking a legend shows only cards that fit it", !$("#editor").hidden && pool.tiles.size > 0
        && [...pool.tiles.keys()].every((k) => allowedIn(firstOf[k], L)));
      pool.tiles.get(nameKey(champ.name)).add.click(); await sleep(50);
      ok("the first champion added becomes the Chosen Champion", deckOf(id).champion === champ.id);
      await sleep(1000);
      ok("the deck saves to the database", __decks.find((x) => x.id === id)?.legend === L.id);
      window.confirm = () => true;
      $("#delete-deck").click(); await sleep(1000);
      ok("deleting a deck removes it", !__decks.some((x) => x.id === id) && location.hash === "#decks" && !deckOf(id));

      location.hash = "%E0%A4%A"; await sleep(50);
      ok("a malformed address opens the collection instead of breaking the page", !$("#view-collection").hidden);

      __signOutFail = true; $("#signout").click();
      await sleep(300);
      ok("a failed sign-out keeps the device copy", JSON.parse(localStorage.getItem("rb-saved"))[c.id] === 8 && editable());
      __signOutFail = false; $("#signout").click();
      await sleep(300);
      ok("sign-out clears the device copy", !localStorage.getItem("rb-saved").includes(c.id) && document.body.classList.contains("ro"));
    }
  } catch (e) {
    out.push(`FAIL test crashed: ${e.message}`);
  }
  const pre = document.createElement("pre"); pre.id = "result"; pre.textContent = out.join("\n"); document.body.append(pre);
})();
