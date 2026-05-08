-- Supabase migration: result cache table used by ResultCacheService
-- Run this once in the Supabase SQL Editor (or via psql) before setting
-- CACHE_BACKEND=supabase in the backend.

CREATE TABLE IF NOT EXISTS public.result_cache (
    file_hash         text PRIMARY KEY,
    file_name         text NOT NULL,
    ocr_result        jsonb NOT NULL,
    evaluation_result jsonb,
    answer_key_hash   text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    last_accessed     timestamptz NOT NULL DEFAULT now(),
    access_count      integer NOT NULL DEFAULT 0,
    result_size       integer NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_result_cache_answer_key_hash
    ON public.result_cache(answer_key_hash);

CREATE INDEX IF NOT EXISTS idx_result_cache_last_accessed
    ON public.result_cache(last_accessed);

CREATE INDEX IF NOT EXISTS idx_result_cache_created_at
    ON public.result_cache(created_at);

CREATE INDEX IF NOT EXISTS idx_result_cache_eval_only
    ON public.result_cache(file_name) WHERE file_name = '__eval__';

-- RLS: keep enabled; backend connects with the Postgres role (bypasses RLS).
-- Do NOT expose this table to anon/authenticated Supabase roles.
ALTER TABLE public.result_cache ENABLE ROW LEVEL SECURITY;
