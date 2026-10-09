-- =============================================================================
-- eXoticPlayer · ESQUEMA COMPLETO DE SUPABASE (v21)
-- =============================================================================
-- Sustituye a social_schema.sql, social_schema_2.sql … social_schema_6.sql:
-- es exactamente lo mismo, en el mismo orden, en un solo archivo.
--
-- · Base de datos NUEVA: pega este archivo entero en Supabase -> SQL Editor y ejecútalo.
-- · Base de datos que YA TIENES funcionando: no hace falta ejecutar nada.
--   (Se puede volver a ejecutar sin romper nada, pero ojo con la PARTE 6, paso 3:
--    vuelve a numerar los # de los usuarios por orden de creación.)
-- =============================================================================

-- Las funciones se crean antes que algunas de las tablas que usan: sin esto, una base de
-- datos NUEVA daba "relation public.jam_members does not exist" en la parte 1.
set check_function_bodies = off;

-- -----------------------------------------------------------------------------
-- PARTE 0 · Datos de cada usuario (playlists, ♥, historial, ajustes)
-- La app guarda aquí todo con un upsert (user_id, data, updated_at).
-- Si ya tienes la tabla, esto no la toca.
-- -----------------------------------------------------------------------------
create table if not exists public.user_data (
  user_id uuid primary key references auth.users(id) on delete cascade,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
alter table public.user_data enable row level security;
drop policy if exists "user_data: propio" on public.user_data;
create policy "user_data: propio" on public.user_data
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);



-- #############################################################################
-- PARTE 1 · (antes social_schema.sql)
-- #############################################################################
-- eXoticPlayer: perfiles, amigos y jams
-- Ejecutar entero en Supabase -> SQL Editor. Se puede ejecutar más de una vez sin romper nada.
-- No toca la tabla donde ya guardas playlists/liked.

-- ---------------------------------------------------------------------------
-- 1) PERFILES (nombre de usuario público; el email nunca se expone)
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text unique not null check (username ~ '^[a-zA-Z0-9_]{3,20}$'),
  created_at timestamptz not null default now()
);
alter table public.profiles enable row level security;

drop policy if exists "perfiles: ver" on public.profiles;
create policy "perfiles: ver" on public.profiles
  for select to authenticated using (true);

drop policy if exists "perfiles: crear el mío" on public.profiles;
create policy "perfiles: crear el mío" on public.profiles
  for insert to authenticated with check (id = auth.uid());

drop policy if exists "perfiles: editar el mío" on public.profiles;
create policy "perfiles: editar el mío" on public.profiles
  for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

-- ---------------------------------------------------------------------------
-- 2) AMIGOS
-- ---------------------------------------------------------------------------
create table if not exists public.friendships (
  id bigint generated always as identity primary key,
  requester uuid not null references public.profiles(id) on delete cascade,
  addressee uuid not null references public.profiles(id) on delete cascade,
  status text not null default 'pending' check (status in ('pending', 'accepted')),
  created_at timestamptz not null default now(),
  check (requester <> addressee)
);
-- Solo una relación por pareja, da igual quién la pidió primero
create unique index if not exists friendships_par_unico
  on public.friendships (least(requester, addressee), greatest(requester, addressee));
alter table public.friendships enable row level security;

drop policy if exists "amigos: ver los míos" on public.friendships;
create policy "amigos: ver los míos" on public.friendships
  for select to authenticated using (requester = auth.uid() or addressee = auth.uid());

drop policy if exists "amigos: pedir" on public.friendships;
create policy "amigos: pedir" on public.friendships
  for insert to authenticated with check (requester = auth.uid() and status = 'pending');

-- Solo quien recibe la solicitud puede aceptarla, y solo puede cambiar "status"
drop policy if exists "amigos: aceptar" on public.friendships;
create policy "amigos: aceptar" on public.friendships
  for update to authenticated using (addressee = auth.uid()) with check (addressee = auth.uid());
revoke update on public.friendships from authenticated;
grant update (status) on public.friendships to authenticated;

-- Rechazar, cancelar o borrar amigo: cualquiera de los dos
drop policy if exists "amigos: borrar" on public.friendships;
create policy "amigos: borrar" on public.friendships
  for delete to authenticated using (requester = auth.uid() or addressee = auth.uid());

-- ---------------------------------------------------------------------------
-- 3) FUNCIONES AUXILIARES (security definer evita recursión infinita en las políticas)
-- ---------------------------------------------------------------------------
create or replace function public.es_amigo(a uuid, b uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.friendships
    where status = 'accepted'
      and ((requester = a and addressee = b) or (requester = b and addressee = a))
  );
$$;

create or replace function public.es_miembro_jam(j uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.jam_members where jam_id = j and user_id = auth.uid());
$$;

-- ---------------------------------------------------------------------------
-- 4) JAMS
--    state = {"video_id": "...", "playing": true, "position_ms": 12345,
--             "queue": [...], "sent_at": "..."}   (lo escribe el anfitrión)
-- ---------------------------------------------------------------------------
create table if not exists public.jams (
  id uuid primary key default gen_random_uuid(),
  host uuid not null references public.profiles(id) on delete cascade,
  name text not null default 'Jam',
  state jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table if not exists public.jam_members (
  jam_id uuid not null references public.jams(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  joined_at timestamptz not null default now(),
  primary key (jam_id, user_id)
);

alter table public.jams enable row level security;
alter table public.jam_members enable row level security;

-- Ven la jam: el anfitrión, los miembros y los amigos del anfitrión (para poder unirse)
drop policy if exists "jams: ver" on public.jams;
create policy "jams: ver" on public.jams
  for select to authenticated
  using (host = auth.uid() or public.es_miembro_jam(id) or public.es_amigo(host, auth.uid()));

drop policy if exists "jams: crear" on public.jams;
create policy "jams: crear" on public.jams
  for insert to authenticated with check (host = auth.uid());

-- Solo el anfitrión controla la reproducción
drop policy if exists "jams: actualizar (anfitrión)" on public.jams;
create policy "jams: actualizar (anfitrión)" on public.jams
  for update to authenticated using (host = auth.uid()) with check (host = auth.uid());

drop policy if exists "jams: borrar (anfitrión)" on public.jams;
create policy "jams: borrar (anfitrión)" on public.jams
  for delete to authenticated using (host = auth.uid());

drop policy if exists "miembros: ver" on public.jam_members;
create policy "miembros: ver" on public.jam_members
  for select to authenticated using (user_id = auth.uid() or public.es_miembro_jam(jam_id));

-- Unirse: tú mismo, y solo si eres el anfitrión o su amigo
drop policy if exists "miembros: unirse" on public.jam_members;
create policy "miembros: unirse" on public.jam_members
  for insert to authenticated
  with check (
    user_id = auth.uid()
    and exists (
      select 1 from public.jams j
      where j.id = jam_id and (j.host = auth.uid() or public.es_amigo(j.host, auth.uid()))
    )
  );

-- Salir de la jam, o que el anfitrión expulse a alguien
drop policy if exists "miembros: salir/expulsar" on public.jam_members;
create policy "miembros: salir/expulsar" on public.jam_members
  for delete to authenticated
  using (
    user_id = auth.uid()
    or exists (select 1 from public.jams j where j.id = jam_id and j.host = auth.uid())
  );


-- #############################################################################
-- PARTE 2 · (antes social_schema_2.sql)
-- #############################################################################
-- eXoticPlayer: parte 2 (sincronización de jams)
-- Ejecutar DESPUÉS de social_schema.sql, también en Supabase -> SQL Editor.

-- Nombres de usuario únicos sin distinguir mayúsculas ("Ana" y "ana" serían el mismo)
create unique index if not exists profiles_username_lower
  on public.profiles (lower(username));

-- updated_at lo pone SIEMPRE el servidor: así el reloj de cada PC no influye en la sincronización
create or replace function public.jams_tocar_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists jams_updated_at on public.jams;
create trigger jams_updated_at
  before update on public.jams
  for each row execute function public.jams_tocar_updated_at();

-- Estado de una jam + cuánto hace (en ms, reloj del servidor) que el anfitrión lo publicó.
-- security invoker: se aplican las políticas RLS de quien llama.
create or replace function public.jam_estado(j uuid)
returns jsonb
language sql volatile security invoker set search_path = public as $$
  select jsonb_build_object(
    'state', jm.state,
    'host',  jm.host,
    'name',  jm.name,
    'age_ms', extract(epoch from (clock_timestamp() - jm.updated_at)) * 1000
  )
  from public.jams jm
  where jm.id = j;
$$;

-- Jams de tus amigos cuyo anfitrión sigue conectado (publica cada pocos segundos)
drop function if exists public.jams_activas();
create or replace function public.jams_activas()
returns table (id uuid, name text, host uuid, host_username text, age_ms double precision)
language sql volatile security invoker set search_path = public as $$
  select jm.id, jm.name, jm.host, p.username,
         (extract(epoch from (clock_timestamp() - jm.updated_at)) * 1000)::double precision
  from public.jams jm
  join public.profiles p on p.id = jm.host
  where jm.host <> auth.uid()
    and jm.updated_at > now() - interval '2 minutes'
  order by jm.updated_at desc;
$$;

grant execute on function public.jam_estado(uuid) to authenticated;
grant execute on function public.jams_activas() to authenticated;


-- #############################################################################
-- PARTE 3 · (antes social_schema_3.sql)
-- #############################################################################
-- eXoticPlayer: parte 3 (jams con control compartido, públicas/privadas y aprobación del anfitrión)
-- Ejecutar DESPUÉS de social_schema.sql y social_schema_2.sql, en Supabase -> SQL Editor.
-- Se puede ejecutar más de una vez sin romper nada.
--
-- Qué cambia:
--   * jams.is_public          -> pública: entra cualquiera sin aprobación. Privada: solo amigos del
--                                anfitrión, y el anfitrión tiene que aceptarlos.
--   * jam_members.status      -> 'pending' (esperando aprobación) | 'accepted'
--   * Cualquier miembro ACEPTADO puede cambiar el estado de la jam (cola, canción, play/pausa, posición).
--     Para que dos personas no se pisen, cada cambio lleva un número de revisión ("rev"):
--     si alguien publica sobre una revisión vieja, el servidor lo rechaza y ese cliente adopta la nueva.
--   * Todas las escrituras de jams/miembros pasan por funciones (security definer) que validan permisos.

-- ---------------------------------------------------------------------------
-- 1) COLUMNAS NUEVAS
-- ---------------------------------------------------------------------------
alter table public.jams
  add column if not exists is_public boolean not null default false,
  add column if not exists last_seen timestamptz not null default now();

alter table public.jam_members
  add column if not exists status text not null default 'accepted';

-- los miembros que ya existían quedan como 'accepted' gracias al default
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'jam_members_status_check') then
    alter table public.jam_members
      add constraint jam_members_status_check check (status in ('pending', 'accepted'));
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- 2) FUNCIONES AUXILIARES
-- ---------------------------------------------------------------------------
-- Ahora "miembro" = miembro ACEPTADO
create or replace function public.es_miembro_jam(j uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.jam_members
    where jam_id = j and user_id = auth.uid() and status = 'accepted'
  );
$$;

create or replace function public.es_host_jam(j uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.jams where id = j and host = auth.uid());
$$;

-- updated_at = "cuándo cambió el estado" (lo usan los oyentes para calcular la posición).
-- Solo se toca si cambia state: el latido (last_seen) no debe alterarlo.
create or replace function public.jams_tocar_updated_at()
returns trigger language plpgsql as $$
begin
  if new.state is distinct from old.state then
    new.updated_at := now();
  end if;
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- 3) POLÍTICAS (RLS)
-- ---------------------------------------------------------------------------
-- Ven la jam: anfitrión, miembros, jams públicas y amigos del anfitrión (para poder pedir entrar)
drop policy if exists "jams: ver" on public.jams;
create policy "jams: ver" on public.jams
  for select to authenticated
  using (
    host = auth.uid()
    or is_public
    or public.es_miembro_jam(id)
    or public.es_amigo(host, auth.uid())
  );

-- Crear y actualizar jams SOLO mediante funciones (jam_crear / jam_publicar / jam_latido)
drop policy if exists "jams: crear" on public.jams;
drop policy if exists "jams: actualizar (anfitrión)" on public.jams;
revoke insert, update on public.jams from authenticated;

-- Borrar la jam: solo el anfitrión (se mantiene la política de social_schema.sql)

-- Miembros: tú ves tu propia fila; el anfitrión ve todas (incluidas las pendientes);
-- los miembros aceptados ven a los aceptados.
drop policy if exists "miembros: ver" on public.jam_members;
create policy "miembros: ver" on public.jam_members
  for select to authenticated
  using (
    user_id = auth.uid()
    or public.es_host_jam(jam_id)
    or (status = 'accepted' and public.es_miembro_jam(jam_id))
  );

-- Unirse / aceptar SOLO mediante funciones (jam_unirse / jam_responder)
drop policy if exists "miembros: unirse" on public.jam_members;
revoke insert, update on public.jam_members from authenticated;

-- Salir, cancelar tu solicitud o que el anfitrión expulse: se mantiene "miembros: salir/expulsar"

-- ---------------------------------------------------------------------------
-- 4) FUNCIONES DE JAM
-- ---------------------------------------------------------------------------
drop function if exists public.jam_estado(uuid);
drop function if exists public.jams_activas();

-- Crear jam (una por anfitrión). p_estado = estado inicial (cola, canción actual...).
create or replace function public.jam_crear(p_nombre text, p_publica boolean, p_estado jsonb)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_id uuid;
  v_nombre text;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  v_nombre := left(coalesce(nullif(btrim(p_nombre), ''), 'Jam'), 40);
  if coalesce(jsonb_typeof(p_estado), 'null') <> 'object' then
    p_estado := '{}'::jsonb;
  end if;
  if jsonb_array_length(coalesce(p_estado->'queue', '[]'::jsonb)) > 300 then
    raise exception 'cola_demasiado_grande';
  end if;

  delete from public.jams where host = v_uid;   -- limpia jams antiguas del anfitrión
  insert into public.jams (host, name, is_public, state, last_seen)
  values (v_uid, v_nombre, coalesce(p_publica, false),
          p_estado || jsonb_build_object('rev', 1), now())
  returning id into v_id;
  insert into public.jam_members (jam_id, user_id, status) values (v_id, v_uid, 'accepted');

  return jsonb_build_object('id', v_id, 'rev', 1);
end;
$$;

-- Unirse: devuelve 'accepted' (entras ya) o 'pending' (espera al anfitrión).
create or replace function public.jam_unirse(j uuid)
returns text
language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_jam public.jams;
  v_st text;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  select * into v_jam from public.jams where id = j;
  if not found then raise exception 'jam_no_existe'; end if;

  select status into v_st from public.jam_members where jam_id = j and user_id = v_uid;
  if v_st is not null then return v_st; end if;   -- ya estabas (o ya habías pedido entrar)

  if v_jam.host = v_uid or v_jam.is_public then
    insert into public.jam_members (jam_id, user_id, status) values (j, v_uid, 'accepted');
    return 'accepted';
  elsif public.es_amigo(v_jam.host, v_uid) then
    insert into public.jam_members (jam_id, user_id, status) values (j, v_uid, 'pending');
    return 'pending';
  end if;
  raise exception 'no_permitido';
end;
$$;

-- El anfitrión acepta (true) o rechaza/expulsa (false) a alguien.
create or replace function public.jam_responder(j uuid, u uuid, aceptar boolean)
returns void
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'no_autenticado'; end if;
  if not exists (select 1 from public.jams where id = j and host = auth.uid()) then
    raise exception 'no_permitido';
  end if;
  if aceptar then
    update public.jam_members set status = 'accepted'
    where jam_id = j and user_id = u and status = 'pending';
  else
    delete from public.jam_members where jam_id = j and user_id = u and user_id <> auth.uid();
  end if;
end;
$$;

-- Cualquier miembro aceptado publica un cambio. Compara la revisión base con la actual:
--   {"ok": true,  "rev": n}   -> aplicado
--   {"ok": false, "rev": n}   -> alguien se te adelantó; adopta el estado nuevo
--   null                      -> la jam ya no existe o ya no eres miembro aceptado
create or replace function public.jam_publicar(j uuid, p_estado jsonb, p_base_rev int)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_state jsonb;
  v_rev int;
  v_user text;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  if not exists (
    select 1 from public.jam_members where jam_id = j and user_id = v_uid and status = 'accepted'
  ) then
    return null;
  end if;
  if coalesce(jsonb_typeof(p_estado), 'null') <> 'object' then raise exception 'estado_invalido'; end if;
  if jsonb_array_length(coalesce(p_estado->'queue', '[]'::jsonb)) > 300 then
    raise exception 'cola_demasiado_grande';
  end if;

  select state into v_state from public.jams where id = j for update;   -- serializa escrituras
  if not found then return null; end if;

  v_rev := coalesce((v_state->>'rev')::int, 0);
  if v_rev <> p_base_rev then
    return jsonb_build_object('ok', false, 'rev', v_rev);
  end if;

  select username into v_user from public.profiles where id = v_uid;
  v_rev := v_rev + 1;
  update public.jams
     set state = p_estado || jsonb_build_object('rev', v_rev, 'by', v_user)
   where id = j;
  return jsonb_build_object('ok', true, 'rev', v_rev);
end;
$$;

-- Estado de la jam para quien la consulta.
--   null -> la jam no existe o no tienes ninguna relación con ella (te expulsaron / terminó)
--   {"mi_estado": "pending", ...}  -> aún no te han aceptado (no se enseña el estado)
--   {"mi_estado": "accepted", "rev": n, "age_ms": ..., "state": {...}}
--   "state" viene a null si tu revisión (p_rev) ya es la actual: así no se descarga la cola entera
--   cada segundo. age_ms = ms (reloj del servidor) desde que se publicó ese estado.
create or replace function public.jam_estado(j uuid, p_rev int default -1)
returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_jam public.jams;
  v_st text;
  v_rev int;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  select * into v_jam from public.jams where id = j;
  if not found then return null; end if;
  select status into v_st from public.jam_members where jam_id = j and user_id = v_uid;
  if v_st is null then return null; end if;

  if v_st <> 'accepted' then
    return jsonb_build_object('mi_estado', v_st, 'name', v_jam.name, 'publica', v_jam.is_public);
  end if;

  v_rev := coalesce((v_jam.state->>'rev')::int, 0);
  return jsonb_build_object(
    'mi_estado', v_st,
    'host', v_jam.host,
    'name', v_jam.name,
    'publica', v_jam.is_public,
    'rev', v_rev,
    'age_ms', extract(epoch from (clock_timestamp() - v_jam.updated_at)) * 1000,
    'state', case when v_rev = p_rev then null else v_jam.state end
  );
end;
$$;

-- "Sigo aquí": cada miembro lo llama cada pocos segundos; la jam se considera viva mientras alguien lo haga.
create or replace function public.jam_latido(j uuid)
returns void
language sql volatile security definer set search_path = public as $$
  update public.jams set last_seen = now()
  where id = j
    and exists (
      select 1 from public.jam_members
      where jam_id = j and user_id = auth.uid() and status = 'accepted'
    );
$$;

-- Jams que puedes ver (de amigos o públicas) con alguien conectado, y tu estado en cada una.
drop function if exists public.jams_activas();
create or replace function public.jams_activas()
returns table (
  id uuid, name text, host uuid, host_username text,
  age_ms double precision, is_public boolean, mi_estado text
)
language sql volatile security invoker set search_path = public as $$
  select jm.id, jm.name, jm.host, p.username,
         (extract(epoch from (clock_timestamp() - jm.last_seen)) * 1000)::double precision,
         jm.is_public,
         (select m.status from public.jam_members m
           where m.jam_id = jm.id and m.user_id = auth.uid())
  from public.jams jm
  join public.profiles p on p.id = jm.host
  where jm.host <> auth.uid()
    and jm.last_seen > now() - interval '2 minutes'
  order by jm.last_seen desc;
$$;

-- ---------------------------------------------------------------------------
-- 5) PERMISOS DE EJECUCIÓN (solo usuarios con sesión)
-- ---------------------------------------------------------------------------
revoke all on function public.jam_crear(text, boolean, jsonb) from public, anon;
revoke all on function public.jam_unirse(uuid) from public, anon;
revoke all on function public.jam_responder(uuid, uuid, boolean) from public, anon;
revoke all on function public.jam_publicar(uuid, jsonb, int) from public, anon;
revoke all on function public.jam_estado(uuid, int) from public, anon;
revoke all on function public.jam_latido(uuid) from public, anon;
revoke all on function public.jams_activas() from public, anon;

grant execute on function public.jam_crear(text, boolean, jsonb) to authenticated;
grant execute on function public.jam_unirse(uuid) to authenticated;
grant execute on function public.jam_responder(uuid, uuid, boolean) to authenticated;
grant execute on function public.jam_publicar(uuid, jsonb, int) to authenticated;
grant execute on function public.jam_estado(uuid, int) to authenticated;
grant execute on function public.jam_latido(uuid) to authenticated;
grant execute on function public.jams_activas() to authenticated;


-- #############################################################################
-- PARTE 4 · (antes social_schema_4.sql)
-- #############################################################################
-- eXoticPlayer: parte 4 (cola compartida de la jam: añadir / quitar / limpiar por cualquier miembro)
-- Ejecutar DESPUÉS de social_schema.sql, social_schema_2.sql y social_schema_3.sql,
-- en Supabase -> SQL Editor. Se puede ejecutar más de una vez sin romper nada.
--
-- Qué cambia:
--   * Cada canción de la cola lleva un "uid" propio (lo pone el servidor). Sirve para quitar
--     UNA canción concreta aunque otra persona haya movido la cola justo antes.
--   * jam_cola_agregar / jam_cola_quitar / jam_cola_limpiar: operan sobre la cola DENTRO del
--     servidor (con bloqueo de fila), así dos personas que añaden a la vez NO se pisan:
--     las dos canciones entran. Ya no hace falta mandar la cola entera por cada cambio.
--   * jam_publicar: si el estado que llega no trae "queue", se conserva la cola del servidor
--     (play/pausa/siguiente/posición ya no suben 300 canciones cada vez).
--   * jam_crear devuelve también el estado inicial normalizado (con los uid).

-- ---------------------------------------------------------------------------
-- 1) NORMALIZAR UNA COLA: solo campos conocidos, longitudes acotadas, uid garantizado
-- ---------------------------------------------------------------------------
create or replace function public._jam_normalizar_cola(p_cola jsonb)
returns jsonb
language sql volatile set search_path = public as $$
  select coalesce(jsonb_agg(item order by ord), '[]'::jsonb)
  from (
    select ord,
           jsonb_strip_nulls(jsonb_build_object(
             'uid',      coalesce(nullif(e->>'uid', ''), gen_random_uuid()::text),
             'videoId',  left(e->>'videoId', 32),
             'title',    left(coalesce(e->>'title', 'Desconocido'), 200),
             'artist',   left(coalesce(e->>'artist', ''), 200),
             'coverUrl', left(e->>'coverUrl', 400)
           )) as item
    from jsonb_array_elements(
           case when jsonb_typeof(p_cola) = 'array' then p_cola else '[]'::jsonb end
         ) with ordinality as t(e, ord)
    where jsonb_typeof(e) = 'object' and coalesce(e->>'videoId', '') <> ''
  ) s;
$$;
revoke all on function public._jam_normalizar_cola(jsonb) from public, anon, authenticated;

-- Posición (ms) que tiene AHORA la canción actual según el último estado guardado.
-- Cuando el servidor cambia el estado (updated_at pasa a now()), hay que "avanzar" la posición
-- guardada; si no, los oyentes volverían atrás hasta donde estaba en la última publicación.
create or replace function public._jam_posicion_actual(p_state jsonb, p_updated timestamptz)
returns bigint
language sql volatile set search_path = public as $$
  select greatest(0, (
    coalesce((p_state->>'position_ms')::numeric, 0)
    + case when coalesce((p_state->>'playing')::boolean, false)
           then extract(epoch from (clock_timestamp() - p_updated)) * 1000
           else 0 end
  ))::bigint;
$$;
revoke all on function public._jam_posicion_actual(jsonb, timestamptz) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2) jam_crear: normaliza la cola inicial (uid) y devuelve el estado
-- ---------------------------------------------------------------------------
create or replace function public.jam_crear(p_nombre text, p_publica boolean, p_estado jsonb)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_id uuid;
  v_nombre text;
  v_cola jsonb;
  v_estado jsonb;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  v_nombre := left(coalesce(nullif(btrim(p_nombre), ''), 'Jam'), 40);
  if coalesce(jsonb_typeof(p_estado), 'null') <> 'object' then
    p_estado := '{}'::jsonb;
  end if;
  if jsonb_array_length(coalesce(p_estado->'queue', '[]'::jsonb)) > 300 then
    raise exception 'cola_demasiado_grande';
  end if;

  v_cola := public._jam_normalizar_cola(p_estado->'queue');
  v_estado := jsonb_build_object(
    'queue', v_cola,
    'index', case
               when coalesce((p_estado->>'index')::int, -1) between 0 and jsonb_array_length(v_cola) - 1
               then (p_estado->>'index')::int else -1 end,
    'playing', coalesce((p_estado->>'playing')::boolean, false),
    'position_ms', greatest(0, coalesce((p_estado->>'position_ms')::bigint, 0)),
    'rev', 1
  );

  delete from public.jams where host = v_uid;   -- limpia jams antiguas del anfitrión
  insert into public.jams (host, name, is_public, state, last_seen)
  values (v_uid, v_nombre, coalesce(p_publica, false), v_estado, now())
  returning id into v_id;
  insert into public.jam_members (jam_id, user_id, status) values (v_id, v_uid, 'accepted');

  return jsonb_build_object('id', v_id, 'rev', 1, 'state', v_estado);
end;
$$;

-- ---------------------------------------------------------------------------
-- 3) jam_publicar: si no viene "queue", se conserva la del servidor
-- ---------------------------------------------------------------------------
create or replace function public.jam_publicar(j uuid, p_estado jsonb, p_base_rev int)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_state jsonb;
  v_rev int;
  v_user text;
  v_cola jsonb;
  v_idx int;
  v_nuevo jsonb;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  if not exists (
    select 1 from public.jam_members where jam_id = j and user_id = v_uid and status = 'accepted'
  ) then
    return null;
  end if;
  if coalesce(jsonb_typeof(p_estado), 'null') <> 'object' then raise exception 'estado_invalido'; end if;
  if jsonb_array_length(coalesce(p_estado->'queue', '[]'::jsonb)) > 300 then
    raise exception 'cola_demasiado_grande';
  end if;

  select state into v_state from public.jams where id = j for update;   -- serializa escrituras
  if not found then return null; end if;

  v_rev := coalesce((v_state->>'rev')::int, 0);
  if v_rev <> p_base_rev then
    return jsonb_build_object('ok', false, 'rev', v_rev);
  end if;

  -- Sin "queue" en lo publicado -> se queda la cola que ya hay en el servidor
  if p_estado ? 'queue' then
    v_cola := public._jam_normalizar_cola(p_estado->'queue');
  else
    v_cola := coalesce(v_state->'queue', '[]'::jsonb);
  end if;

  v_idx := coalesce((p_estado->>'index')::int, -1);
  if v_idx < 0 or v_idx >= jsonb_array_length(v_cola) then v_idx := -1; end if;

  select username into v_user from public.profiles where id = v_uid;
  v_rev := v_rev + 1;
  v_nuevo := jsonb_build_object(
    'queue', v_cola,
    'index', v_idx,
    'playing', case when v_idx < 0 then false else coalesce((p_estado->>'playing')::boolean, false) end,
    'position_ms', case when v_idx < 0 then 0 else greatest(0, coalesce((p_estado->>'position_ms')::bigint, 0)) end,
    'rev', v_rev,
    'by', v_user
  );
  update public.jams set state = v_nuevo where id = j;
  return jsonb_build_object('ok', true, 'rev', v_rev);
end;
$$;

-- ---------------------------------------------------------------------------
-- 4) OPERACIONES DE COLA (cualquier miembro ACEPTADO)
--    Devuelven {"rev": n}, o null si la jam ya no existe / ya no eres miembro aceptado.
-- ---------------------------------------------------------------------------

-- Añade una o varias canciones al final. Si p_reproducir, la primera pasa a sonar ya
-- (para todos). Si no, la reproducción actual no se toca.
create or replace function public.jam_cola_agregar(j uuid, p_items jsonb, p_reproducir boolean default false)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_state jsonb;
  v_upd timestamptz;
  v_cola jsonb;
  v_nuevas jsonb;
  v_n_antes int;
  v_rev int;
  v_user text;
  v_idx int;
  v_playing boolean;
  v_pos bigint;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  if not exists (
    select 1 from public.jam_members where jam_id = j and user_id = v_uid and status = 'accepted'
  ) then
    return null;
  end if;

  v_nuevas := public._jam_normalizar_cola(p_items);
  -- Los uid de canciones nuevas los pone SIEMPRE el servidor (nadie fuerza uid repetidos)
  select coalesce(jsonb_agg(jsonb_set(e, '{uid}', to_jsonb(gen_random_uuid()::text)) order by ord), '[]'::jsonb)
    into v_nuevas
    from jsonb_array_elements(v_nuevas) with ordinality as t(e, ord);
  if jsonb_array_length(v_nuevas) = 0 then
    raise exception 'estado_invalido';
  end if;

  select state, updated_at into v_state, v_upd from public.jams where id = j for update;
  if not found then return null; end if;

  v_cola := coalesce(v_state->'queue', '[]'::jsonb);
  v_n_antes := jsonb_array_length(v_cola);
  if v_n_antes + jsonb_array_length(v_nuevas) > 300 then
    raise exception 'cola_demasiado_grande';
  end if;

  v_cola := v_cola || v_nuevas;
  v_idx := coalesce((v_state->>'index')::int, -1);
  v_playing := coalesce((v_state->>'playing')::boolean, false);
  v_pos := public._jam_posicion_actual(v_state, v_upd);   -- avanzar la posición al momento actual

  if p_reproducir then
    v_idx := v_n_antes;      -- la primera de las nuevas
    v_playing := true;
    v_pos := 0;
  elsif v_idx < 0 then
    v_pos := 0;
  end if;

  select username into v_user from public.profiles where id = v_uid;
  v_rev := coalesce((v_state->>'rev')::int, 0) + 1;
  update public.jams
     set state = jsonb_build_object(
           'queue', v_cola, 'index', v_idx, 'playing', v_playing,
           'position_ms', v_pos, 'rev', v_rev, 'by', v_user)
   where id = j;
  return jsonb_build_object('rev', v_rev);
end;
$$;

-- Quita UNA canción por su uid. Si era la que sonaba, pasa a sonar la siguiente (o se para
-- si no queda ninguna). Si el uid ya no existe (otra persona la quitó antes) no hace nada.
create or replace function public.jam_cola_quitar(j uuid, p_uid text)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_state jsonb;
  v_upd timestamptz;
  v_cola jsonb;
  v_pos_quitada int;
  v_idx int;
  v_playing boolean;
  v_pos bigint;
  v_rev int;
  v_user text;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  if not exists (
    select 1 from public.jam_members where jam_id = j and user_id = v_uid and status = 'accepted'
  ) then
    return null;
  end if;

  select state, updated_at into v_state, v_upd from public.jams where id = j for update;
  if not found then return null; end if;

  v_cola := coalesce(v_state->'queue', '[]'::jsonb);
  v_rev := coalesce((v_state->>'rev')::int, 0);

  select (ord - 1)::int into v_pos_quitada
    from jsonb_array_elements(v_cola) with ordinality as t(e, ord)
   where e->>'uid' = p_uid
   limit 1;
  if v_pos_quitada is null then
    return jsonb_build_object('rev', v_rev);       -- ya no estaba: nada que hacer
  end if;

  select coalesce(jsonb_agg(e order by ord), '[]'::jsonb) into v_cola
    from jsonb_array_elements(v_cola) with ordinality as t(e, ord)
   where (ord - 1) <> v_pos_quitada;

  v_idx := coalesce((v_state->>'index')::int, -1);
  v_playing := coalesce((v_state->>'playing')::boolean, false);
  v_pos := public._jam_posicion_actual(v_state, v_upd);

  if v_idx = v_pos_quitada then
    -- Era la canción actual: sigue la que ocupa ahora ese hueco (la siguiente)
    v_pos := 0;
    if v_idx >= jsonb_array_length(v_cola) then
      v_idx := -1;
      v_playing := false;
    end if;
  elsif v_idx > v_pos_quitada then
    v_idx := v_idx - 1;
  end if;

  select username into v_user from public.profiles where id = v_uid;
  v_rev := v_rev + 1;
  update public.jams
     set state = jsonb_build_object(
           'queue', v_cola, 'index', v_idx, 'playing', v_playing,
           'position_ms', v_pos, 'rev', v_rev, 'by', v_user)
   where id = j;
  return jsonb_build_object('rev', v_rev);
end;
$$;

-- Vacía la cola y para la reproducción de todos.
create or replace function public.jam_cola_limpiar(j uuid)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_state jsonb;
  v_rev int;
  v_user text;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  if not exists (
    select 1 from public.jam_members where jam_id = j and user_id = v_uid and status = 'accepted'
  ) then
    return null;
  end if;

  select state into v_state from public.jams where id = j for update;
  if not found then return null; end if;

  select username into v_user from public.profiles where id = v_uid;
  v_rev := coalesce((v_state->>'rev')::int, 0) + 1;
  update public.jams
     set state = jsonb_build_object(
           'queue', '[]'::jsonb, 'index', -1, 'playing', false,
           'position_ms', 0, 'rev', v_rev, 'by', v_user)
   where id = j;
  return jsonb_build_object('rev', v_rev);
end;
$$;

-- ---------------------------------------------------------------------------
-- 5) PERMISOS DE EJECUCIÓN (solo usuarios con sesión)
-- ---------------------------------------------------------------------------
revoke all on function public.jam_crear(text, boolean, jsonb) from public, anon;
revoke all on function public.jam_publicar(uuid, jsonb, int) from public, anon;
revoke all on function public.jam_cola_agregar(uuid, jsonb, boolean) from public, anon;
revoke all on function public.jam_cola_quitar(uuid, text) from public, anon;
revoke all on function public.jam_cola_limpiar(uuid) from public, anon;

grant execute on function public.jam_crear(text, boolean, jsonb) to authenticated;
grant execute on function public.jam_publicar(uuid, jsonb, int) to authenticated;
grant execute on function public.jam_cola_agregar(uuid, jsonb, boolean) to authenticated;
grant execute on function public.jam_cola_quitar(uuid, text) to authenticated;
grant execute on function public.jam_cola_limpiar(uuid) to authenticated;


-- #############################################################################
-- PARTE 5 · (antes social_schema_5.sql)
-- #############################################################################
-- eXoticPlayer: parte 5 (nombre de usuario + etiqueta #0000, como Discord)
-- Ejecutar DESPUÉS de social_schema.sql, _2, _3 y _4, en Supabase -> SQL Editor.
-- Se puede ejecutar más de una vez sin romper nada.
--
-- Qué cambia:
--   * profiles.tag: 4 cifras ("0007", "4821"...) que asigna el SERVIDOR al crear el perfil.
--   * Los nombres de usuario YA PUEDEN repetirse; lo que no se repite es la pareja nombre + tag
--     (sin distinguir mayúsculas). Ej.: Juan#4821 y Juan#0093 conviven, Juan#4821 solo existe una vez.
--   * El tag no se puede elegir ni cambiar desde el cliente.
--   * Los perfiles que ya existen reciben su tag automáticamente.

-- 1) Columna
alter table public.profiles add column if not exists tag text;

-- 2) Quitar cualquier restricción/índice ÚNICO que hubiera solo sobre username
do $$
declare r record;
begin
  for r in
    select c.conname
      from pg_constraint c
     where c.conrelid = 'public.profiles'::regclass
       and c.contype = 'u'
       and (select array_agg(a.attname::text)
              from pg_attribute a
             where a.attrelid = c.conrelid and a.attnum = any(c.conkey)) = array['username']
  loop
    execute format('alter table public.profiles drop constraint %I', r.conname);
  end loop;

  for r in
    select i.relname
      from pg_index x
      join pg_class i on i.oid = x.indexrelid
     where x.indrelid = 'public.profiles'::regclass
       and x.indisunique and not x.indisprimary
       and i.relname <> 'profiles_username_tag_uq'
       and pg_get_indexdef(x.indexrelid) ilike '%username%'
       and not exists (select 1 from pg_constraint c where c.conindid = x.indexrelid)
  loop
    execute format('drop index public.%I', r.relname);
  end loop;
end $$;

-- 3) Buscar un tag libre para un nombre (aleatorio; si hay mucha colisión, recorre todos)
create or replace function public._perfil_tag_libre(p_username text)
returns text
language plpgsql security definer set search_path = public as $$
declare
  v_tag text;
  v_try int := 0;
begin
  loop
    v_tag := lpad((floor(random() * 10000))::int::text, 4, '0');
    if not exists (select 1 from public.profiles
                    where lower(username) = lower(p_username) and tag = v_tag) then
      return v_tag;
    end if;
    v_try := v_try + 1;
    exit when v_try >= 60;
  end loop;

  select lpad(n::text, 4, '0') into v_tag
    from generate_series(0, 9999) as n
   where not exists (select 1 from public.profiles
                      where lower(username) = lower(p_username) and tag = lpad(n::text, 4, '0'))
   limit 1;
  if v_tag is null then raise exception 'nombre_agotado'; end if;
  return v_tag;
end;
$$;
revoke all on function public._perfil_tag_libre(text) from public, anon, authenticated;

-- 4) Perfiles existentes (antes de crear el trigger)
drop trigger if exists profiles_tag_trg on public.profiles;
do $$
declare r record;
begin
  for r in select id, username from public.profiles where tag is null loop
    update public.profiles set tag = public._perfil_tag_libre(r.username) where id = r.id;
  end loop;
end $$;

alter table public.profiles alter column tag set not null;
alter table public.profiles drop constraint if exists profiles_tag_formato;
alter table public.profiles add constraint profiles_tag_formato check (tag ~ '^[0-9]{4}$');

create unique index if not exists profiles_username_tag_uq
  on public.profiles (lower(username), tag);

-- 5) Trigger: al insertar, el servidor pone el tag (ignora el que mande el cliente);
--    al actualizar, el tag no cambia nunca.
create or replace function public._perfil_asignar_tag()
returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'UPDATE' then
    new.tag := old.tag;
    return new;
  end if;
  -- evita que dos altas simultáneas con el mismo nombre elijan el mismo tag
  perform pg_advisory_xact_lock(hashtext(lower(new.username)));
  new.tag := public._perfil_tag_libre(new.username);
  return new;
end;
$$;
revoke all on function public._perfil_asignar_tag() from public, anon, authenticated;

create trigger profiles_tag_trg
  before insert or update on public.profiles
  for each row execute function public._perfil_asignar_tag();

-- 6) La lista de jams activas muestra al anfitrión como nombre#tag
--    (misma firma que en social_schema_3.sql, solo cambia el texto de host_username)
drop function if exists public.jams_activas();
create or replace function public.jams_activas()
returns table (
  id uuid, name text, host uuid, host_username text,
  age_ms double precision, is_public boolean, mi_estado text
)
language sql volatile security invoker set search_path = public as $$
  select jm.id, jm.name, jm.host, p.username || '#' || p.tag,
         (extract(epoch from (clock_timestamp() - jm.last_seen)) * 1000)::double precision,
         jm.is_public,
         (select m.status from public.jam_members m
           where m.jam_id = jm.id and m.user_id = auth.uid())
  from public.jams jm
  join public.profiles p on p.id = jm.host
  where jm.host <> auth.uid()
    and jm.last_seen > now() - interval '2 minutes'
  order by jm.last_seen desc;
$$;
grant execute on function public.jams_activas() to authenticated;


-- #############################################################################
-- PARTE 6 · (antes social_schema_6.sql)
-- #############################################################################
-- eXoticPlayer: parte 6 (# único y SECUENCIAL + cambiar nombre de usuario sin cambiar el #)
-- Ejecutar DESPUÉS de social_schema.sql, _2, _3, _4 y _5, en Supabase -> SQL Editor.
-- Se puede ejecutar más de una vez sin romper nada (pero ver el aviso del paso 3).
--
-- Qué cambia:
--   * El # (4 cifras: 0001, 0002, ...) sale de una SECUENCIA del servidor: cada usuario nuevo
--     recibe el siguiente número, en orden, y nunca se repite entre usuarios.
--   * El # es único en TODA la tabla (no solo por nombre). Máximo 9999 usuarios.
--   * El nombre de usuario se puede cambiar (perfil_cambiar_username); el # no cambia nunca.
--   * Los perfiles que ya existen se RENUMERAN por orden de creación (0001 = el más antiguo).

-- 1) Secuencia (sin ciclo: al llegar a 9999 da error en vez de repetir números)
create sequence if not exists public.profiles_tag_seq
  minvalue 1 maxvalue 9999 start 1 no cycle;

-- 2) Quitar el trigger antiguo y el índice único (nombre, tag) de la parte 5
drop trigger if exists profiles_tag_trg on public.profiles;
drop index if exists public.profiles_username_tag_uq;

-- 3) Renumerar los perfiles existentes por orden de creación.
--    AVISO: si vuelves a ejecutar este archivo, los # se recalculan igual (mismo orden),
--    así que no cambian salvo que se hayan borrado perfiles intermedios.
with orden as (
  select id, row_number() over (order by created_at, id) as n
    from public.profiles
)
update public.profiles p
   set tag = lpad(o.n::text, 4, '0')
  from orden o
 where p.id = o.id;

select setval('public.profiles_tag_seq',
              greatest((select count(*) from public.profiles), 1)::bigint,
              (select count(*) from public.profiles) > 0);

-- 4) Unicidad global del # (y formato)
create unique index if not exists profiles_tag_uq on public.profiles (tag);
alter table public.profiles drop constraint if exists profiles_tag_formato;
alter table public.profiles add constraint profiles_tag_formato check (tag ~ '^[0-9]{4}$');

-- 5) Trigger: al insertar, el servidor asigna el siguiente número (ignora lo que mande el cliente);
--    al actualizar, el # se queda como estaba SIEMPRE.
create or replace function public._perfil_asignar_tag()
returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'UPDATE' then
    new.tag := old.tag;
    return new;
  end if;
  begin
    new.tag := lpad(nextval('public.profiles_tag_seq')::text, 4, '0');
  exception when sequence_generator_limit_exceeded then
    raise exception 'tags_agotados';
  end;
  return new;
end;
$$;
revoke all on function public._perfil_asignar_tag() from public, anon, authenticated;

create trigger profiles_tag_trg
  before insert or update on public.profiles
  for each row execute function public._perfil_asignar_tag();

-- La secuencia no la toca nadie desde fuera
revoke all on sequence public.profiles_tag_seq from public, anon, authenticated;

-- 6) Cambiar el nombre de usuario (el # no se toca). Devuelve {id, username, tag}.
create or replace function public.perfil_cambiar_username(p_username text)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_nombre text := btrim(coalesce(p_username, ''));
  v_fila public.profiles;
begin
  if v_uid is null then raise exception 'no_autenticado'; end if;
  if v_nombre !~ '^[A-Za-z0-9_]{3,20}$' then raise exception 'nombre_invalido'; end if;

  update public.profiles set username = v_nombre where id = v_uid
  returning * into v_fila;
  if not found then raise exception 'sin_perfil'; end if;

  return jsonb_build_object('id', v_fila.id, 'username', v_fila.username, 'tag', v_fila.tag);
end;
$$;
revoke all on function public.perfil_cambiar_username(text) from public, anon;
grant execute on function public.perfil_cambiar_username(text) to authenticated;

-- 7) Por seguridad: desde el cliente solo se puede editar el nombre, nunca id/tag/created_at
revoke update on public.profiles from authenticated;
grant update (username) on public.profiles to authenticated;


-- #############################################################################
-- PARTE 7 · v22 (también en supabase_actualizacion_v22.sql)
-- #############################################################################
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
