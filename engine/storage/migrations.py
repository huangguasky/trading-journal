SCHEMA_SQL = """
create table if not exists watchlist (
  symbol text primary key,
  name text not null default '',
  enabled integer not null default 1,
  notes text not null default '',
  created_at text not null default (strftime('%Y-%m-%d %H:%M:%S', 'now', '+8 hours'))
);

create table if not exists reports (
  id integer primary key autoincrement,
  kind text not null,
  symbol text,
  market text,
  title text not null,
  score real not null,
  regime text,
  payload_json text not null,
  markdown text not null,
  created_at text not null default (strftime('%Y-%m-%d %H:%M:%S', 'now', '+8 hours'))
);

create table if not exists tracking_tasks (
  id integer primary key autoincrement,
  report_id integer not null,
  symbol text not null,
  base_price real not null,
  target_price real,
  stop_price real,
  status text not null default 'open',
  last_checked_at text,
  result_json text,
  created_at text not null default (strftime('%Y-%m-%d %H:%M:%S', 'now', '+8 hours'))
);

create table if not exists system_settings (
  key text primary key,
  value text not null default '',
  updated_at text not null default (strftime('%Y-%m-%d %H:%M:%S', 'now', '+8 hours'))
);
"""
