// In-memory stand-in for the supabase-js calls the page makes, with latency
// and switchable failures. "?restart" simulates reopening the app with a
// signed-in session, a change still queued on the device, and a link to a
// deck this device has never loaded.
window.__latency = 50; window.__fail = false; window.__signOutFail = false; window.__calls = 0;
window.__db = [
  { card_id: "ogn-001-298", n: 2 },
  ...Array.from({ length: 1200 }, (_, i) => ({ card_id: "x" + String(i).padStart(4, "0"), n: 1 })),
];
window.__decks = [];
const restart = location.search.includes("restart");
localStorage.clear();
if (restart) {
  localStorage.setItem("rb-owner", JSON.stringify("u1"));
  localStorage.setItem("rb-saved", JSON.stringify({ "ogn-001-298": 2 }));
  localStorage.setItem("rb-pending", JSON.stringify({ "ogn-001-298": 5 }));
  __decks = [{ id: "33333333-3333-4333-8333-333333333333", user_id: "u1", name: "Linked deck", legend: null, champion: null, cards: {}, updated_at: "2026-11-25T00:00:00Z" }];
}
const wait = () => new Promise((r) => setTimeout(r, __latency));
const offline = { message: "TypeError: Failed to fetch", code: "" };

window.supabase = { createClient() {
  let cb; const session = { user: { id: "u1", email: "me@example.com" } };
  const auth = {
    onAuthStateChange(fn) { cb = fn; setTimeout(() => fn("INITIAL_SESSION", restart ? session : null), 0); return { data: { subscription: { unsubscribe() {} } } }; },
    async signInWithPassword() { setTimeout(() => cb("SIGNED_IN", session), 0); return { error: null }; },
    async signOut() {
      if (__signOutFail) return { error: { message: "Failed to fetch" } };
      setTimeout(() => cb("SIGNED_OUT", null), 0);
      return { error: null };
    },
  };
  const from = (table) => {
    const key = table === "decks" ? "id" : "card_id";
    const rows = () => (table === "decks" ? __decks : __db);
    const filters = []; let lim = Infinity;
    const q = {
      select: () => q,
      gt: (col, v) => { filters.push([col, v]); return q; },
      order: () => q,
      limit: (n) => { lim = n; return q; },
      then(resolve, reject) {
        return wait().then(() => __fail ? { data: null, error: offline } : {
          data: rows().filter((r) => filters.every(([c, v]) => r[c] > v))
            .sort((a, b) => (a[key] < b[key] ? -1 : 1)).slice(0, lim).map((r) => structuredClone(r)),
          error: null,
        }).then(resolve, reject);
      },
      async upsert(list) {
        __calls++;
        await wait();
        if (__fail) return { error: offline };
        for (const r of list) {
          const i = rows().findIndex((x) => x[key] === r[key]);
          if (i >= 0) rows()[i] = structuredClone(r); else rows().push(structuredClone(r));
        }
        return { error: null };
      },
      delete: () => ({
        async in(col, ids) {
          await wait();
          if (__fail) return { error: offline };
          __decks = __decks.filter((r) => !ids.includes(r[col]));
          return { error: null };
        },
      }),
    };
    return q;
  };
  return { auth, from };
} };
