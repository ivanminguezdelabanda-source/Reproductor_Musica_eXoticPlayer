-- =============================================================================
-- eXoticPlayer · ACTUALIZACIÓN v22  (PARTE 7 del esquema)
-- =============================================================================
-- Si ya tienes la base de datos funcionando: ejecuta SOLO este archivo en
-- Supabase -> SQL Editor. Se puede ejecutar más de una vez sin romper nada.
-- (supabase_schema.sql ya lo incluye al final, para bases de datos nuevas.)
--
-- Añade:
--   7.1  Chat, reacciones y "votar para saltar" dentro de una jam
--   7.2  Actividad de amigos (qué está escuchando cada uno ahora)
--   7.3  Playlists colaborativas con amigos
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 7.1 MENSAJES DE LA JAM (chat · reacción · voto)
-- -----------------------------------------------------------------------------
create table if not exists public.jam_messages (
  id bigint generated always as identity primary key,
  jam_id uuid not null references public.jams(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  kind text not null check (kind in ('chat', 'reaction', 'vote')),
  body text not null check (char_length(body) between 1 and 300),
  created_at timestamptz not null default now()
);
create index if not exists jam_messages_por_jam on public.jam_messages (jam_id, id);
alter table public.jam_messages enable row level security;
-- Sin políticas: solo se lee y escribe con las funciones de abajo (que comprueban que eres miembro).

create or replace function public.jam_mensaje(j uuid, p_kind text, p_body text)
returns bigint language plpgsql security definer set search_path = public as $$
declare
  nuevo bigint;
begin
  if not public.es_miembro_jam(j) then
    raise exception 'no_permitido';
  end if;
  if p_kind not in ('chat', 'reaction', 'vote') or coalesce(btrim(p_body), '') = '' then
    raise exception 'no_permitido';
  end if;
  -- antispam: como mucho 15 mensajes cada 10 segundos por persona
  if (select count(*) from public.jam_messages
      where jam_id = j and user_id = auth.uid() and created_at > now() - interval '10 seconds') >= 15 then
    raise exception 'demasiados_mensajes';
  end if;
  -- un voto por persona y canción
  if p_kind = 'vote' and exists (select 1 from public.jam_messages
      where jam_id = j and user_id = auth.uid() and kind = 'vote' and body = p_body) then
    return 0;
  end if;
  insert into public.jam_messages (jam_id, user_id, kind, body)
  values (j, auth.uid(), p_kind, left(btrim(p_body), 300))
  returning id into nuevo;
  -- limpieza: la jam solo guarda los 300 últimos mensajes
  delete from public.jam_messages
  where jam_id = j and id < (select coalesce(min(id), 0) from (
      select id from public.jam_messages where jam_id = j order by id desc limit 300) ultimos);
  return nuevo;
end;
$$;

create or replace function public.jam_mensajes(j uuid, p_desde bigint default 0)
returns table (id bigint, user_id uuid, nombre text, kind text, body text, created_at timestamptz)
language sql stable security definer set search_path = public as $$
  select m.id, m.user_id, p.username || '#' || coalesce(p.tag, '????'), m.kind, m.body, m.created_at
  from public.jam_messages m
  join public.profiles p on p.id = m.user_id
  where m.jam_id = j and m.id > coalesce(p_desde, 0) and public.es_miembro_jam(j)
  order by m.id
  limit 150;
$$;

-- -----------------------------------------------------------------------------
-- 7.2 ACTIVIDAD DE AMIGOS (solo la ven tus amigos)
-- -----------------------------------------------------------------------------
create table if not exists public.friend_activity (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  song jsonb,
  updated_at timestamptz not null default now()
);
alter table public.friend_activity enable row level security;
-- Sin políticas: se usa con las funciones de abajo.

create or replace function public.actividad_publicar(p_song jsonb)
returns void language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then
    raise exception 'no_permitido';
  end if;
  insert into public.friend_activity (user_id, song, updated_at)
  values (auth.uid(), p_song, now())
  on conflict (user_id) do update set song = excluded.song, updated_at = now();
end;
$$;

create or replace function public.actividad_amigos()
returns table (user_id uuid, nombre text, song jsonb, updated_at timestamptz)
language sql stable security definer set search_path = public as $$
  select a.user_id, p.username || '#' || coalesce(p.tag, '????'), a.song, a.updated_at
  from public.friend_activity a
  join public.profiles p on p.id = a.user_id
  where a.song is not null
    and a.updated_at > now() - interval '20 minutes'
    and public.es_amigo(auth.uid(), a.user_id);
$$;

-- -----------------------------------------------------------------------------
-- 7.3 PLAYLISTS COLABORATIVAS
-- -----------------------------------------------------------------------------
create table if not exists public.shared_playlists (
  id uuid primary key default gen_random_uuid(),
  owner uuid not null references public.profiles(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 60),
  tracks jsonb not null default '[]'::jsonb,
  rev int not null default 0,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create table if not exists public.shared_playlist_members (
  playlist_id uuid not null references public.shared_playlists(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  added_at timestamptz not null default now(),
  primary key (playlist_id, user_id)
);
alter table public.shared_playlists enable row level security;
alter table public.shared_playlist_members enable row level security;
-- Sin políticas: todo pasa por las funciones de abajo.

create or replace function public.es_miembro_pl(pl uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.shared_playlist_members where playlist_id = pl and user_id = auth.uid());
$$;

create or replace function public.pl_crear(p_nombre text)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  nuevo uuid;
begin
  if auth.uid() is null or not exists (select 1 from public.profiles where id = auth.uid()) then
    raise exception 'sin_perfil';
  end if;
  if char_length(btrim(coalesce(p_nombre, ''))) not between 1 and 60 then
    raise exception 'nombre_invalido';
  end if;
  if (select count(*) from public.shared_playlists where owner = auth.uid()) >= 30 then
    raise exception 'demasiadas_playlists';
  end if;
  insert into public.shared_playlists (owner, name) values (auth.uid(), btrim(p_nombre)) returning id into nuevo;
  insert into public.shared_playlist_members (playlist_id, user_id) values (nuevo, auth.uid());
  return nuevo;
end;
$$;

create or replace function public.pl_mias()
returns table (id uuid, name text, duenio text, es_duenio boolean, canciones int, miembros int, rev int,
               updated_at timestamptz)
language sql stable security definer set search_path = public as $$
  select s.id, s.name, p.username || '#' || coalesce(p.tag, '????'), s.owner = auth.uid(),
         jsonb_array_length(s.tracks),
         (select count(*)::int from public.shared_playlist_members m2 where m2.playlist_id = s.id),
         s.rev, s.updated_at
  from public.shared_playlists s
  join public.shared_playlist_members m on m.playlist_id = s.id and m.user_id = auth.uid()
  join public.profiles p on p.id = s.owner
  order by s.updated_at desc;
$$;

create or replace function public.pl_ver(pl uuid)
returns jsonb language sql stable security definer set search_path = public as $$
  select case when public.es_miembro_pl(pl) then
    jsonb_build_object(
      'id', s.id, 'name', s.name, 'rev', s.rev, 'tracks', s.tracks, 'es_duenio', s.owner = auth.uid(),
      'miembros', (select coalesce(jsonb_agg(p.username || '#' || coalesce(p.tag, '????') order by m.added_at), '[]'::jsonb)
                   from public.shared_playlist_members m join public.profiles p on p.id = m.user_id
                   where m.playlist_id = s.id))
  end
  from public.shared_playlists s where s.id = pl;
$$;

create or replace function public.pl_invitar(pl uuid, u uuid)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.es_miembro_pl(pl) or not public.es_amigo(auth.uid(), u) then
    raise exception 'no_permitido';
  end if;
  if (select count(*) from public.shared_playlist_members where playlist_id = pl) >= 20 then
    raise exception 'demasiados_miembros';
  end if;
  insert into public.shared_playlist_members (playlist_id, user_id) values (pl, u) on conflict do nothing;
end;
$$;

create or replace function public.pl_agregar(pl uuid, p_items jsonb)
returns int language plpgsql security definer set search_path = public as $$
declare
  actual jsonb;
  nuevos jsonb;
  quien text;
begin
  if not public.es_miembro_pl(pl) then
    raise exception 'no_permitido';
  end if;
  select username || '#' || coalesce(tag, '????') into quien from public.profiles where id = auth.uid();
  select tracks into actual from public.shared_playlists where id = pl for update;
  select coalesce(jsonb_agg(jsonb_build_object(
           'uid', gen_random_uuid()::text,
           'videoId', it->>'videoId', 'title', left(coalesce(it->>'title', ''), 200),
           'artist', left(coalesce(it->>'artist', ''), 200), 'coverUrl', it->>'coverUrl',
           'duration', coalesce((it->>'duration')::numeric, 0), 'by', quien)), '[]'::jsonb)
    into nuevos
  from jsonb_array_elements(coalesce(p_items, '[]'::jsonb)) it
  where coalesce(it->>'videoId', '') <> '' and left(it->>'videoId', 5) <> 'file:';
  if jsonb_array_length(actual) + jsonb_array_length(nuevos) > 500 then
    raise exception 'playlist_llena';
  end if;
  update public.shared_playlists
     set tracks = actual || nuevos, rev = rev + 1, updated_at = now()
   where id = pl;
  return jsonb_array_length(nuevos);
end;
$$;

create or replace function public.pl_quitar(pl uuid, p_uid text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.es_miembro_pl(pl) then
    raise exception 'no_permitido';
  end if;
  update public.shared_playlists
     set tracks = coalesce((select jsonb_agg(t) from jsonb_array_elements(tracks) t where t->>'uid' <> p_uid),
                           '[]'::jsonb),
         rev = rev + 1, updated_at = now()
   where id = pl;
end;
$$;

-- El dueño la borra para todos; los demás solo salen de ella.
create or replace function public.pl_salir(pl uuid)
returns void language plpgsql security definer set search_path = public as $$
begin
  if exists (select 1 from public.shared_playlists where id = pl and owner = auth.uid()) then
    delete from public.shared_playlists where id = pl;
  else
    delete from public.shared_playlist_members where playlist_id = pl and user_id = auth.uid();
  end if;
end;
$$;

grant execute on function public.jam_mensaje(uuid, text, text), public.jam_mensajes(uuid, bigint),
  public.actividad_publicar(jsonb), public.actividad_amigos(), public.pl_crear(text), public.pl_mias(),
  public.pl_ver(uuid), public.pl_invitar(uuid, uuid), public.pl_agregar(uuid, jsonb),
  public.pl_quitar(uuid, text), public.pl_salir(uuid), public.es_miembro_pl(uuid)
  to authenticated;
