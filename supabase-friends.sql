-- Friends and trades. Run once in the Supabase SQL editor, after supabase.sql.
-- Everyone picks a display name (shown to friends) and gets a friend code;
-- friends find each other only by code, never by email.
create table public.profiles (
  id uuid primary key default auth.uid() references auth.users on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 40),
  code text not null unique default upper(substr(md5(gen_random_uuid()::text), 1, 8))
);

create table public.friendships (
  requester uuid not null references auth.users on delete cascade,
  addressee uuid not null references auth.users on delete cascade,
  accepted boolean not null default false,
  created_at timestamptz not null default now(),
  primary key (requester, addressee),
  check (requester <> addressee)
);
-- One friendship per pair, whichever way round it was asked.
create unique index friendships_pair on public.friendships (least(requester, addressee), greatest(requester, addressee));

create table public.trades (
  id uuid primary key default gen_random_uuid(),
  from_user uuid not null default auth.uid() references auth.users on delete cascade,
  to_user uuid not null references auth.users on delete cascade,
  give jsonb not null default '{}'::jsonb,  -- card id -> copies the proposer gives
  get jsonb not null default '{}'::jsonb,   -- card id -> copies the proposer gets
  note text check (char_length(note) <= 280),
  status text not null default 'open' check (status in ('open', 'accepted', 'declined', 'cancelled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Used inside the access rules below; security definer so a rule on one table
-- can look at friendships without recursing through friendships' own rules.
create function public.are_friends(a uuid, b uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from friendships f where f.accepted
    and ((f.requester = a and f.addressee = b) or (f.requester = b and f.addressee = a)))
$$;
revoke all on function public.are_friends(uuid, uuid) from public, anon;
grant execute on function public.are_friends(uuid, uuid) to authenticated;

alter table public.profiles enable row level security;
alter table public.friendships enable row level security;
alter table public.trades enable row level security;
revoke all on public.profiles, public.friendships, public.trades from anon;
grant select, insert, update on public.profiles to authenticated;
grant select, delete on public.friendships to authenticated;
grant update (accepted) on public.friendships to authenticated;
grant select, insert on public.trades to authenticated;

create policy "own profile" on public.profiles for all to authenticated
  using (id = auth.uid()) with check (id = auth.uid());
-- Names show for friends and for pending requests either way.
create policy "friends' profiles" on public.profiles for select to authenticated
  using (exists (select 1 from public.friendships f
    where (f.requester = auth.uid() and f.addressee = profiles.id) or (f.addressee = auth.uid() and f.requester = profiles.id)));
create policy "own friendships" on public.friendships for select to authenticated
  using (auth.uid() in (requester, addressee));
create policy "accept requests" on public.friendships for update to authenticated
  using (addressee = auth.uid()) with check (addressee = auth.uid());
create policy "end friendships" on public.friendships for delete to authenticated
  using (auth.uid() in (requester, addressee));
-- Friends see each other's collections; decks stay private.
create policy "friends read collections" on public.owned for select to authenticated
  using (public.are_friends(auth.uid(), user_id));
create policy "own trades" on public.trades for select to authenticated
  using (auth.uid() in (from_user, to_user));
create policy "offer to friends" on public.trades for insert to authenticated
  with check (from_user = auth.uid() and status = 'open' and public.are_friends(auth.uid(), to_user));

-- Sends a request to whoever has the code; if they already asked you, accepts it.
create function public.send_friend_request(friend_code text) returns text
language plpgsql security definer set search_path = public as $$
declare
  target uuid;
  target_name text;
begin
  if not exists (select 1 from profiles where id = auth.uid()) then
    raise exception 'Choose the name your friends will see first.';
  end if;
  select id, name into target, target_name from profiles where code = upper(btrim(friend_code));
  if target is null then raise exception 'Nobody has the friend code %.', upper(btrim(friend_code)); end if;
  if target = auth.uid() then raise exception 'That is your own friend code.'; end if;
  update friendships set accepted = true where requester = target and addressee = auth.uid();
  if not found then
    insert into friendships (requester, addressee) values (auth.uid(), target) on conflict do nothing;
  end if;
  return target_name;
end $$;
revoke all on function public.send_friend_request(text) from public, anon;
grant execute on function public.send_friend_request(text) to authenticated;

-- Accepting moves the cards both ways in one transaction, and is refused if
-- either side no longer has what it offered. Declining and cancelling only
-- change the status.
create function public.answer_trade(trade_id uuid, answer text) returns void
language plpgsql security definer set search_path = public as $$
declare
  t trades;
  card text;
  qty int;
begin
  select * into t from trades where id = trade_id for update;
  if t.id is null or auth.uid() not in (t.from_user, t.to_user) then raise exception 'Trade not found.'; end if;
  if t.status <> 'open' then raise exception 'This trade is already %.', t.status; end if;
  if answer = 'cancelled' and auth.uid() <> t.from_user then raise exception 'Only the person who made the offer can cancel it.'; end if;
  if answer in ('accepted', 'declined') and auth.uid() <> t.to_user then raise exception 'Only the person offered the trade can answer it.'; end if;
  if answer not in ('accepted', 'declined', 'cancelled') then raise exception 'Unknown answer %.', answer; end if;
  if answer = 'accepted' then
    for card, qty in select key, value::int from jsonb_each_text(t.give) loop
      if qty < 1 or coalesce((select o.n from owned o where o.user_id = t.from_user and o.card_id = card), 0) < qty then
        raise exception 'They no longer have every card they offered.';
      end if;
    end loop;
    for card, qty in select key, value::int from jsonb_each_text(t.get) loop
      if qty < 1 or coalesce((select o.n from owned o where o.user_id = t.to_user and o.card_id = card), 0) < qty then
        raise exception 'You no longer have every card they asked for.';
      end if;
    end loop;
    for card, qty in select key, value::int from jsonb_each_text(t.give) loop
      update owned set n = owned.n - qty where user_id = t.from_user and card_id = card;
      insert into owned (user_id, card_id, n) values (t.to_user, card, qty)
        on conflict (user_id, card_id) do update set n = owned.n + excluded.n;
    end loop;
    for card, qty in select key, value::int from jsonb_each_text(t.get) loop
      update owned set n = owned.n - qty where user_id = t.to_user and card_id = card;
      insert into owned (user_id, card_id, n) values (t.from_user, card, qty)
        on conflict (user_id, card_id) do update set n = owned.n + excluded.n;
    end loop;
  end if;
  update trades set status = answer, updated_at = now() where id = trade_id;
end $$;
revoke all on function public.answer_trade(uuid, text) from public, anon;
grant execute on function public.answer_trade(uuid, text) to authenticated;
