-- Supabase migration: page ↔ student mapping for PDF-uploaded runs.
-- Run this once in the Supabase SQL Editor (or via psql). Not required
-- for purely local SQLite installs — the backend creates the same table
-- automatically on startup.

CREATE TABLE IF NOT EXISTS public.pdf_page_map (
    run_id          text NOT NULL,
    pdf_hash        text NOT NULL,
    page_number     integer NOT NULL,
    page_index      integer NOT NULL,
    file_id         text,
    file_name       text,
    entry_number    text,
    name            text,
    status          text NOT NULL,          -- 'processed' | 'error' | 'unresolved'
    total_score     numeric,
    max_score       numeric,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_pdf_page_map_pdf_hash
    ON public.pdf_page_map(pdf_hash);

CREATE INDEX IF NOT EXISTS idx_pdf_page_map_entry_number
    ON public.pdf_page_map(entry_number);

-- RLS: keep enabled; backend connects with the Postgres role (bypasses RLS).
ALTER TABLE public.pdf_page_map ENABLE ROW LEVEL SECURITY;
