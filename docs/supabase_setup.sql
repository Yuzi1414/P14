-- P14 账务核对工作台 · Supabase 建表脚本
-- 在 Supabase 控制台 → SQL Editor → New query → 粘贴执行
-- 可重复执行，已存在的表不会被破坏。

-- ============ 1. 账户表 ============
-- 原本存在 Render 容器里的 runtime/users.json，容器重启即清空
-- （表现为「注册的账号第二天失效」），改存到这里。
create table if not exists public.app_users (
    username      text primary key,
    password_hash text not null,
    salt          text not null,
    role          text not null default '用户',
    status        text not null default 'active',
    created_at    text not null default ''
);

-- ============ 2. 任务表 ============
-- 原本存在 runtime/tasks/*.db，同样是临时磁盘，重启丢失。
-- task_key 形如「用户名slug_hash_设备标识」，一个账号的每台设备各占一行。
create table if not exists public.app_tasks (
    task_key       text primary key,
    schema_version integer not null default 1,
    payload        text not null,
    updated_at     text not null default ''
);

-- 只允许服务端（service_role）访问：
-- 开启 RLS 后，anon key 读不到任何行；service_role key 天然绕过 RLS。
alter table public.app_users enable row level security;
alter table public.app_tasks enable row level security;

-- 显式不给 anon / authenticated 任何策略，等于完全禁止浏览器端读写。
-- 应用通过 SUPABASE_KEY（service_role）在服务端调用，不受影响。

-- ============ 3. 索引 ============
create index if not exists app_users_created_at_idx on public.app_users (created_at);

-- ============ 4. 验证 ============
select 'app_users' as table_name, count(*) as rows from public.app_users
union all
select 'app_tasks', count(*) from public.app_tasks;
