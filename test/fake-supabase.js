// In-memory stand-in for the supabase-js calls the page makes: a small query
// engine over plain arrays, with latency and switchable failures. No access
// rules here; test/test_sql.py checks those against real Postgres.
// "?restart" simulates reopening the app with a signed-in session, a change
// still queued on the device, and a link to a deck this device never loaded.
// "?nodecks" simulates a project where the decks table was never created.
window.__latency = 50; window.__fail = false; window.__signOutFail = false; window.__calls = 0; window.__loads = 0;
window.__db = [
  { user_id: "u1", card_id: "ogn-001-298", n: 2 },
  ...Array.from({ length: 1200 }, (_, i) => ({ user_id: "u1", card_id: "x" + String(i).padStart(4, "0"), n: 1 })),
  { user_id: "u2", card_id: "ogn-002-298", n: 2 },  // a friend's collection
  { user_id: "u2", card_id: "ogn-003-298", n: 1 },
];
window.__decks = []; window.__signups = []; window.__resets = []; window.__newPassword = null; window.__rpc = [];
window.__profiles = [{ id: "u2", name: "Bruno", code: "BRUNO123" }];
window.__friendships = []; window.__trades = [];
const restart = location.search.includes("restart");
const noDecks = location.search.includes("nodecks");
localStorage.clear();
if (restart) {
  localStorage.setItem("rb-owner", JSON.stringify("u1"));
  localStorage.setItem("rb-saved", JSON.stringify({ "ogn-001-298": 2 }));
  localStorage.setItem("rb-pending", JSON.stringify({ "ogn-001-298": 5 }));
  __decks = [{ id: "33333333-3333-4333-8333-333333333333", user_id: "u1", name: "Linked deck", legend: null, champion: null, cards: {}, updated_at: "2026-11-25T00:00:00Z" }];
}
const wait = () => new Promise((r) => setTimeout(r, __latency));
const offline = { message: "TypeError: Failed to fetch", code: "" };
const KEYS = { owned: ["user_id", "card_id"], decks: ["id"], profiles: ["id"], trades: ["id"], friendships: ["requester", "addressee"] };
const TABLES = { owned: () => __db, decks: () => __decks, profiles: () => __profiles, friendships: () => __friendships, trades: () => __trades };
const setTable = { owned: (v) => { __db = v; }, decks: (v) => { __decks = v; }, profiles: (v) => { __profiles = v; }, friendships: (v) => { __friendships = v; }, trades: (v) => { __trades = v; } };

window.supabase = { createClient() {
  let cb; const session = { user: { id: "u1", email: "me@example.com" } };
  const auth = {
    onAuthStateChange(fn) { cb = fn; setTimeout(() => fn("INITIAL_SESSION", restart ? session : null), 0); return { data: { subscription: { unsubscribe() {} } } }; },
    async signInWithPassword() { setTimeout(() => cb("SIGNED_IN", session), 0); return { error: null }; },
    // With email confirmation on, sign-up returns a user but no session.
    async signUp({ email }) { __signups.push(email); return { data: { user: { id: "u9", email }, session: null }, error: null }; },
    async resetPasswordForEmail(email) { __resets.push(email); return { data: {}, error: null }; },
    async updateUser({ password }) { __newPassword = password; return { data: {}, error: null }; },
    async signOut() {
      if (__signOutFail) return { error: { message: "Failed to fetch" } };
      setTimeout(() => cb("SIGNED_OUT", null), 0);
      return { error: null };
    },
  };
  window.__recover = () => cb("PASSWORD_RECOVERY", session);  // what a reset-email link triggers
  const me = "u1";

  const from = (table) => {
    const st = { op: "select", filters: [], order: null, limit: Infinity, single: null, payload: null };
    const match = (r) => st.filters.every((f) => f(r));
    const run = () => {
      if (table === "decks" && noDecks) return { data: null, error: { code: "PGRST205", message: "Could not find the table 'public.decks' in the schema cache" } };
      if (__fail) return { data: null, error: offline };
      const rows = TABLES[table]();
      if (st.op === "select") {
        if (table === "owned" && st.filters.length) __loads++;
        let out = rows.filter(match).map((r) => structuredClone(r));
        if (st.order) out.sort((a, b) => (a[st.order.col] < b[st.order.col] ? -1 : 1) * (st.order.asc ? 1 : -1));
        out = out.slice(0, st.limit);
        if (st.single) return { data: out[0] ?? null, error: st.single === "single" && !out.length ? { code: "PGRST116", message: "no rows" } : null };
        return { data: out, error: null };
      }
      if (st.op === "delete") { setTable[table](rows.filter((r) => !match(r))); return { data: null, error: null }; }
      if (st.op === "update") { for (const r of rows.filter(match)) Object.assign(r, st.payload); return { data: null, error: null }; }
      // insert / upsert
      if (table === "owned") __calls++;
      const added = [];
      for (const raw of [].concat(st.payload)) {
        const r = structuredClone(raw);
        if (table === "profiles") Object.assign(r, { id: me, code: r.code || "ANA45678" });
        if (table === "trades") Object.assign(r, { id: r.id || `t${rows.length + 1}`, from_user: me, status: "open", created_at: new Date().toISOString() });
        const i = rows.findIndex((x) => KEYS[table].every((k) => x[k] === r[k]));
        if (i >= 0) rows[i] = r; else rows.push(r);
        added.push(structuredClone(r));
      }
      return { data: st.single ? added[0] : added, error: null };
    };
    const q = {
      select() { return q; },
      eq(col, v) { st.filters.push((r) => r[col] === v); return q; },
      gt(col, v) { st.filters.push((r) => r[col] > v); return q; },
      in(col, vs) { st.filters.push((r) => vs.includes(r[col])); return q; },
      order(col, opts = {}) { st.order = { col, asc: opts.ascending !== false }; return q; },
      limit(n) { st.limit = n; return q; },
      maybeSingle() { st.single = "maybe"; return q; },
      single() { st.single = "single"; return q; },
      insert(p) { st.op = "insert"; st.payload = p; return q; },
      upsert(p) { st.op = "upsert"; st.payload = p; return q; },
      update(p) { st.op = "update"; st.payload = p; return q; },
      delete() { st.op = "delete"; return q; },
      then(resolve, reject) { return wait().then(run).then(resolve, reject); },
    };
    return q;
  };

  // The two database functions, reduced to what the page relies on.
  const rpc = async (name, args) => {
    await wait();
    __rpc.push({ name, args });
    if (__fail) return { data: null, error: offline };
    if (name === "send_friend_request") {
      const t = __profiles.find((p) => p.code === args.friend_code.trim().toUpperCase());
      if (!t) return { data: null, error: { code: "P0001", message: `Nobody has the friend code ${args.friend_code}.` } };
      __friendships.push({ requester: me, addressee: t.id, accepted: false });
      return { data: t.name, error: null };
    }
    if (name === "answer_trade") {
      const t = __trades.find((x) => x.id === args.trade_id);
      t.status = args.answer;
      return { data: null, error: null };
    }
    return { data: null, error: { code: "42883", message: `no function ${name}` } };
  };
  return { auth, from, rpc };
} };
