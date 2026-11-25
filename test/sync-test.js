const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Headless Chromium may report the page as hidden; the resume handler needs "visible".
Object.defineProperty(document, "visibilityState", { get: () => "visible", configurable: true });
const resume = () => document.dispatchEvent(new Event("visibilitychange"));

(async () => {
  const out = [], ok = (name, cond) => out.push((cond ? "PASS " : "FAIL ") + name);
  while (!cards.length) await sleep(100);  // cards.json is real I/O, not virtual time
  await sleep(300);
  const c = cards[0], pocket = c.el.querySelector(".pocket");
  const server = () => __db.find((r) => r.card_id === c.id)?.n;
  const queued = () => JSON.parse(localStorage.getItem("rb-pending") || "{}");

  if (location.hash === "#restart") {
    await sleep(1000);
    ok("a change queued before closing the app saves on the next start", server() === 5 && qty(c) === 5 && !Object.keys(queued()).length);
  } else {
    ok("signed-out view is read-only", document.body.classList.contains("ro") && !$("#login").hidden);

    $("#email").value = "me@example.com"; $("#password").value = "pw"; $("#login").requestSubmit();
    await sleep(10);
    pocket.click();
    await sleep(1000);
    ok("taps before the first load on a new device are ignored", qty(c) === 2 && server() === 2 && __calls === 0);
    ok("loads all 1201 saved rows across 1000-row pages", Object.keys(saved).length === 1201);

    pocket.click(); pocket.click(); pocket.click();
    await sleep(1000);
    ok("three quick taps saved in one request", __calls === 1 && server() === 5);
    ok("three or more copies shows the playset ring", c.el.classList.contains("playset") && c.n.textContent === "5");
    ok("filter count follows taps", $("#count").textContent.endsWith("· 1 owned"));

    pocket.click(); await sleep(620); pocket.click();  // second tap lands while the first save is in flight
    await sleep(1000);
    ok("a tap during a save is not lost", server() === 7 && qty(c) === 7 && !Object.keys(queued()).length);

    __latency = 700;  // a slow load; the save below would finish first without serialising
    resume(); await sleep(10); pocket.click();
    await sleep(4000);
    __latency = 50;
    ok("a load running during a save doesn't bring back old counts", server() === 8 && qty(c) === 8);

    __fail = true; pocket.click();
    await sleep(1000);
    ok("a failed save keeps the change on the device and says so", queued()[c.id] === 9 && server() === 8 && $("#status").classList.contains("err"));
    __fail = false; resume();
    await sleep(500);
    ok("the queued change saves when the app comes back", server() === 9 && !Object.keys(queued()).length);

    __signOutFail = true; $("#signout").click();
    await sleep(300);
    ok("a failed sign-out keeps the device copy", JSON.parse(localStorage.getItem("rb-saved"))[c.id] === 9 && editable());
    __signOutFail = false; $("#signout").click();
    await sleep(300);
    ok("sign-out clears the device copy", !localStorage.getItem("rb-saved").includes(c.id) && document.body.classList.contains("ro"));
  }
  const pre = document.createElement("pre"); pre.id = "result"; pre.textContent = out.join("\n"); document.body.append(pre);
})();
