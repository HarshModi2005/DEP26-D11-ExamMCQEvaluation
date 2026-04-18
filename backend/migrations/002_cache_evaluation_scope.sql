-- Supabase migration: add evaluation scoping to the result cache so
-- runs from different quizzes can never leak into each other, and so
-- cache rows can be purged wholesale when an evaluation is deleted.
--
-- Run this once in the Supabase SQL Editor after 001_result_cache.sql.

ALTER TABLE public.result_cache
    ADD COLUMN IF NOT EXISTS evaluation_id text,
    ADD COLUMN IF NOT EXISTS file_id       text;

-- Backfill (best-effort) from the legacy `ocr:<eval_id>:<file_id>` key scheme
-- used before this migration. `__eval__` rows use a sha256 of
-- `eval:<eval_id>:<file_id>:<ak_hash>` so they are NOT reversible and
-- will simply not be matched by the new single-row API — they age out
-- naturally via LRU, or can be nuked with the purge endpoints below.
UPDATE public.result_cache
   SET evaluation_id = split_part(file_hash, ':', 2),
       file_id       = split_part(file_hash, ':', 3)
 WHERE evaluation_id IS NULL
   AND file_hash LIKE 'ocr:%';

CREATE INDEX IF NOT EXISTS idx_result_cache_evaluation_id
    ON public.result_cache(evaluation_id);

CREATE INDEX IF NOT EXISTS idx_result_cache_eval_file
    ON public.result_cache(evaluation_id, file_id);
