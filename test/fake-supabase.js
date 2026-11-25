// In-memory stand-in for the supabase-js calls the page makes, with latency
// and switchable failures. "#restart" simulates reopening the app with a
// signed-in session and a change still queued on the device.
window.__latency = 50; window.__fail = false; window.__signOutFail = false; window.__calls = 0;
window.__db = [
  { card_id: "ogn-001-298", n: 2 },
  ...Array.from({ length: 1200 }, (_, i) => ({ card_id: "x" + String(i).padStart(4, "0"), n: 1 })),
];
const restart = location.hash === "#restart";
localStorage.clear();
if (restart) {
  localStorage.setItem("rb-owner", JSON.stringify("u1"));
  localStorage.setItem("rb-saved", JSON.stringify({ "ogn-001-298": 2 }));
  localStorage.setItem("rb-pending", JSON.stringify({ "ogn-001-298": 5 }));
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
  const from = () => {
    const filters = []; let lim = Infinity;
    const q = {
      select: () => q,
      gt: (col, v) => { filters.push([col, v]); return q; },
      order: () => q,
      limit: (n) => { lim = n; return q; },
      then(resolve, reject) {
        return wait().then(() => __fail ? { data: null, error: offline } : {
          data: __db.filter((r) => filters.every(([c, v]) => r[c] > v))
            .sort((a, b) => (a.card_id < b.card_id ? -1 : 1)).slice(0, lim).map((r) => ({ ...r })),
          error: null,
        }).then(resolve, reject);
      },
      async upsert(rows) {
        __calls++;
        await wait();
        if (__fail) return { error: offline };
        for (const r of rows) {
          const i = __db.findIndex((x) => x.card_id === r.card_id);
          if (i >= 0) __db[i] = { card_id: r.card_id, n: r.n }; else __db.push({ card_id: r.card_id, n: r.n });
        }
        return { error: null };
      },
    };
    return q;
  };
  return { auth, from };
} };
