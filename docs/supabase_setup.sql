-- P14 账务核对工作台 · Supabase 建表脚本
-- 在 Supabase 控制台 → SQL Editor → New query → 粘贴执行

-- 账户表：原本存在 Render 容器里的 runtime/users.json，
-- 容器重启即清空（表现为「注册的账号第二天失效」），改存到这里。
create table if not exists public.app_users (
    username      text primary key,
    password_hash text not null,
    salt          text not null,
    role          text not null default '用户',
    status        text not null default 'active',
    created_at    text not null default ''
);

-- 只允许服务端（service_role）访问：
-- 开启 RLS 后，anon key 读不到任何行；service_role key 天然绕过 RLS。
alter table public.app_users enable row level security;

-- 显式不给 anon / authenticated 任何策略，等于完全禁止浏览器端读写。
-- 应用通过 SUPABASE_KEY（service_role）在服务端调用，不受影响。

-- 索引：登录按用户名精确匹配，主键已足够；这里给列表排序补一个。
create index if not exists app_users_created_at_idx on public.app_users (created_at);

-- 验证
select username, role, status, created_at from public.app_users;
