create extension if not exists pgcrypto;

create table if not exists public.reviews (
  id uuid primary key default gen_random_uuid(),
  product_id text not null,
  product_name text not null,
  product_url text not null,
  customer_name text not null,
  customer_email text not null,
  rating smallint not null check (rating between 1 and 5),
  title text not null default '',
  comment text not null check (char_length(comment) between 10 and 1200),
  image_urls text[] not null default '{}',
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  verified_purchase boolean not null default false,
  created_at timestamptz not null default now()
);

create index if not exists reviews_product_status_idx
  on public.reviews (product_id, status, created_at desc);

alter table public.reviews enable row level security;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'review-images',
  'review-images',
  true,
  5242880,
  array['image/jpeg','image/png','image/webp']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

