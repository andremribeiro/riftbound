"""Runs supabase.sql and supabase-friends.sql on a throwaway local Postgres and
checks the access rules and the trade function as three users would hit them.

Run: uv run --python 3.12 --with pgserver --with "psycopg[binary]" python -I test/test_sql.py
(pgserver bundles Postgres binaries; nothing is installed system-wide.)
Supabase's auth.uid() and the anon/authenticated roles are stubbed the way
Supabase defines them: auth.uid() reads the request's JWT subject.
"""
import pathlib
import tempfile
import uuid

import pgserver
import psycopg
from psycopg.types.json import Jsonb

ROOT = pathlib.Path(__file__).resolve().parent.parent
A, B, C = (str(uuid.uuid4()) for _ in range(3))
results = []


def ok(name, cond):
    results.append(("PASS " if cond else "FAIL ") + name)


def as_user(conn, uid, sql, params=(), fetch=True):
    """One statement as a signed-in user, the way PostgREST runs it."""
    with conn.transaction():
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (uid,))
        cur = conn.execute(sql, params)
        return cur.fetchall() if fetch and cur.description else cur.rowcount


def refused(conn, uid, sql, params=(), contains=""):
    try:
        as_user(conn, uid, sql, params)
    except psycopg.Error as e:
        return contains.lower() in str(e).lower()
    return False


def count(conn, uid, card, owner):
    rows = as_user(conn, uid, "select n from owned where user_id = %s and card_id = %s", (owner, card))
    return rows[0][0] if rows else None


with tempfile.TemporaryDirectory() as tmp:
    srv = pgserver.get_server(tmp, cleanup_mode="stop")
    with psycopg.connect(srv.get_uri(), autocommit=True) as conn:
        conn.execute("""
            create schema auth;
            create table auth.users (id uuid primary key);
            create function auth.uid() returns uuid language sql stable as
              $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
            create role anon nologin; create role authenticated nologin;
            grant usage on schema public, auth to anon, authenticated;
        """)
        conn.execute((ROOT / "supabase.sql").read_text())
        conn.execute((ROOT / "supabase-friends.sql").read_text())
        for u in (A, B, C):
            conn.execute("insert into auth.users values (%s)", (u,))

        for u, name in ((A, "Ana"), (B, "Bruno"), (C, "Carla")):
            as_user(conn, u, "insert into profiles (name) values (%s)", (name,))
        code = {u: as_user(conn, u, "select code from profiles where id = %s", (u,))[0][0] for u in (A, B, C)}
        as_user(conn, A, "insert into owned (card_id, n) values ('x', 2)")
        as_user(conn, B, "insert into owned (card_id, n) values ('y', 1)")

        ok("strangers can't see each other's collections", count(conn, A, "y", B) is None)
        ok("strangers can't see each other's profiles", not as_user(conn, C, "select name from profiles where id = %s", (A,)))
        ok("you can't edit someone else's profile", as_user(conn, C, "update profiles set name = 'hacked' where id = %s", (A,)) == 0)
        ok("a friend code that doesn't exist is refused", refused(conn, A, "select send_friend_request('NOPE1234')", contains="Nobody has"))
        ok("your own friend code is refused", refused(conn, A, "select send_friend_request(%s)", (code[A],), contains="own friend code"))

        name = as_user(conn, A, "select send_friend_request(%s)", (code[B].lower() + " ",))[0][0]
        ok("a friend request by code names the friend", name == "Bruno")
        ok("a pending request doesn't share collections", count(conn, A, "y", B) is None)
        ok("both sides see the pending request's names", as_user(conn, B, "select name from profiles where id = %s", (A,)) == [("Ana",)])
        ok("you can't accept your own request", as_user(conn, A, "update friendships set accepted = true where requester = %s", (A,)) == 0)
        as_user(conn, B, "update friendships set accepted = true where requester = %s and addressee = %s", (A, B))
        ok("an accepted request shares collections", count(conn, A, "y", B) == 1 and count(conn, B, "x", A) == 2)
        ok("friends still can't write each other's collections",
           as_user(conn, A, "update owned set n = 9 where user_id = %s", (B,)) == 0 and count(conn, B, "y", B) == 1)
        ok("a third person still sees nothing", count(conn, C, "x", A) is None and count(conn, C, "y", B) is None)
        ok("asking again doesn't duplicate the friendship",
           as_user(conn, B, "select send_friend_request(%s)", (code[A],))[0][0] == "Ana"
           and len(as_user(conn, A, "select 1 from friendships")) == 1)

        ok("only friends can be offered trades", refused(conn, C, "insert into trades (to_user, give, get) values (%s, %s, %s)",
                                                          (A, Jsonb({}), Jsonb({"x": 1})), contains="row-level security"))
        tid = as_user(conn, A, "insert into trades (to_user, give, get) values (%s, %s, %s) returning id",
                      (B, Jsonb({"x": 1}), Jsonb({"y": 1})))[0][0]
        ok("the proposer can't accept their own offer", refused(conn, A, "select answer_trade(%s, 'accepted')", (tid,), contains="Only the person offered"))
        ok("a third person can't touch the trade", refused(conn, C, "select answer_trade(%s, 'accepted')", (tid,), contains="Trade not found"))
        as_user(conn, B, "select answer_trade(%s, 'accepted')", (tid,))
        ok("accepting moves the cards both ways",
           (count(conn, A, "x", A), count(conn, A, "y", A), count(conn, B, "x", B), count(conn, B, "y", B)) == (1, 1, 1, 0))
        ok("an answered trade can't be answered again", refused(conn, B, "select answer_trade(%s, 'accepted')", (tid,), contains="already accepted"))

        big = as_user(conn, A, "insert into trades (to_user, give, get) values (%s, %s, %s) returning id",
                      (B, Jsonb({"x": 5}), Jsonb({})))[0][0]
        ok("accepting is refused when the cards aren't there any more",
           refused(conn, B, "select answer_trade(%s, 'accepted')", (big,), contains="no longer have")
           and count(conn, A, "x", A) == 1 and count(conn, B, "x", B) == 1
           and as_user(conn, A, "select status from trades where id = %s", (big,)) == [("open",)])
        ok("only the receiver can decline", refused(conn, A, "select answer_trade(%s, 'declined')", (big,), contains="Only the person offered"))
        ok("only the proposer can cancel", refused(conn, B, "select answer_trade(%s, 'cancelled')", (big,), contains="Only the person who made"))
        as_user(conn, A, "select answer_trade(%s, 'cancelled')", (big,))
        ok("the proposer can cancel an open offer", as_user(conn, B, "select status from trades where id = %s", (big,)) == [("cancelled",)])
        ok("a third person can't see the trades", not as_user(conn, C, "select 1 from trades"))

        as_user(conn, B, "delete from friendships")
        ok("ending the friendship stops sharing collections", count(conn, A, "x", B) is None and count(conn, B, "x", A) is None)
        ok("signed-out visitors see nothing", refused(conn, None, "set local role anon; select * from owned", contains="permission denied")
           or refused(conn, A, "set local role anon; select * from profiles", contains="permission denied"))
    srv.cleanup()

print("\n".join(results))
raise SystemExit(any(r.startswith("FAIL") for r in results))
