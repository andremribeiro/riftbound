-- Run once in the Supabase SQL editor, then supabase-friends.sql.
-- One row per card you own, per account.
create table public.owned (
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  card_id text not null,
  n smallint not null check (n between 0 and 999),  -- the page caps at the same 999
  primary key (user_id, card_id)
);

-- The page's key is public, so row level security is what keeps the data yours:
-- a signed-in account reads and writes only its own rows, nobody else sees any.
-- Grants are explicit so this doesn't depend on the project's default privileges.
alter table public.owned enable row level security;
revoke all on public.owned from anon;
grant select, insert, update, delete on public.owned to authenticated;
create policy "own rows" on public.owned for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Decks, one row each. cards maps card id -> copies (runes and battlefields
-- included); the Chosen Champion is kept apart because it starts the game in
-- its own zone. Ids are made on the device so decks can be created offline.
create table public.decks (
  id uuid primary key,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  name text not null default 'Untitled deck' check (char_length(name) <= 80),
  legend text,
  champion text,
  cards jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
alter table public.decks enable row level security;
revoke all on public.decks from anon;
grant select, insert, update, delete on public.decks to authenticated;
create policy "own decks" on public.decks for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
