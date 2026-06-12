create table if not exists rent_roll (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  unit text,
  unit_id text,
  status text,
  tenant text,
  rent numeric,
  market_rent numeric,
  deposit numeric,
  past_due numeric,
  lease_from date,
  lease_to date,
  bd_ba text,
  portfolio text,
  created_at timestamptz default now()
);

create table if not exists aged_receivable (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  payer_name text,
  amount_receivable numeric,
  d0_30 numeric,
  d31_60 numeric,
  d61_90 numeric,
  d91_plus numeric,
  created_at timestamptz default now()
);

create table if not exists work_orders (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  unit text,
  status text,
  priority text,
  amount numeric,
  created_at_raw text,
  completed_on text,
  days_to_resolve numeric,
  work_order_issue text,
  vendor text,
  work_order_type text,
  created_at timestamptz default now()
);

create table if not exists showings (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  unit text,
  status text,
  showing_time timestamp,
  prospect_name text,
  agent text,
  created_at timestamptz default now()
);

create table if not exists showings_agg (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  calc_completed int,
  calc_canceled int,
  calc_scheduled int,
  created_at timestamptz default now()
);

create table if not exists leasing_funnel (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  inquiries int,
  completed_showings int,
  rental_apps int,
  decision_pending int,
  approved int,
  signed_leases int,
  created_at timestamptz default now()
);

create table if not exists leasing_summary (
  id bigserial primary key,
  snapshot_date date not null,
  leased int,
  move_ins int,
  move_outs int,
  inquiries int,
  showings int,
  applications int,
  created_at timestamptz default now()
);

create table if not exists vacancy_detail (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  unit text,
  unit_id text,
  unit_status text,
  days_vacant numeric,
  last_rent numeric,
  scheduled_rent numeric,
  bed_bath text,
  rent_ready text,
  available_on date,
  rr_status text,
  rr_tenant text,
  source text,
  created_at timestamptz default now()
);

create table if not exists renewal_summary (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  unit_id text,
  tenant_name text,
  status text,
  previous_rent numeric,
  rent numeric,
  percent_difference numeric,
  created_at timestamptz default now()
);

create table if not exists rental_applications (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  applicant text,
  status text,
  received date,
  unit text,
  move_in_date date,
  created_at timestamptz default now()
);

create table if not exists tenant_tickler (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  event_date date,
  event text,
  tenant text,
  unit text,
  rent numeric,
  created_at timestamptz default now()
);

create table if not exists historical_metrics (
  id bigserial primary key,
  date date not null unique,
  physical_occupancy numeric,
  economic_occupancy numeric,
  total_units int,
  occupied_units int,
  vacant_units int,
  sum_of_rent numeric,
  inquiries int,
  showings int,
  leased int,
  collection_rate numeric,
  created_at timestamptz default now()
);

create table if not exists monthly_leasing (
  id bigserial primary key,
  snapshot_date date not null,
  year int not null,
  month int not null,
  showings_completed int,
  applications_received int,
  leases_signed int,
  inquiries int,
  created_at timestamptz default now()
);

create table if not exists calls (
  id bigserial primary key,
  snapshot_date date not null,
  name text,
  ext text,
  total_calls int,
  avg_daily int,
  inbound int,
  outbound int,
  missed_with_vm int,
  missed_vm_pct numeric,
  period_start date,
  period_end date,
  created_at timestamptz default now()
);

create table if not exists leads (
  id bigserial primary key,
  snapshot_date date not null,
  property text,
  name text,
  status text,
  monthly_income numeric,
  max_rent numeric,
  credit_score numeric,
  credit_score_mid numeric,
  lead_score numeric,
  created_at timestamptz default now()
);