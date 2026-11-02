-- Unit Turn KPI Board (Operations/Maintenance): extra work order columns.
-- Run once in Supabase -> SQL Editor.
alter table work_orders add column if not exists unit_turn_id text;
alter table work_orders add column if not exists estimate_req_on date;
alter table work_orders add column if not exists estimated_on date;
alter table work_orders add column if not exists estimate_amount numeric;
alter table work_orders add column if not exists estimate_approval_status text;
alter table work_orders add column if not exists estimate_approved_on date;
alter table work_orders add column if not exists estimate_approval_last_requested_on date;
alter table work_orders add column if not exists work_done_on date;
