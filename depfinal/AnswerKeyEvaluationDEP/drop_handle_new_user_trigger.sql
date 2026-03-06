-- ============================================================
-- SQL Snippet to Drop the Auto-Profile trigger from Supabase
-- This fixes the server blocking issue caused by synchronous
-- Postgres trigger during user auth registration.
-- Execute this snippet in the Supabase SQL Editor.
-- ============================================================
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
DROP FUNCTION IF EXISTS public.handle_new_user();
-- Since we are now manually inserting from the frontend,
-- we must ensure the authenticated user is allowed to insert into `profiles`.
-- The existing RLS policy `profiles_insert` already allows this:
-- CREATE POLICY "profiles_insert" ON profiles FOR INSERT WITH CHECK (auth.uid() = id);
-- No further changes needed.