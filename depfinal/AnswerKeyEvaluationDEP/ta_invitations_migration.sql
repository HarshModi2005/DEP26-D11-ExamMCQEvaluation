-- ============================================================
-- FIX: Remove the broken trigger that crashes signup
-- Run this in Supabase SQL Editor IMMEDIATELY
-- ============================================================
-- Drop the trigger that's causing "Database error saving new user"
DROP TRIGGER IF EXISTS on_profile_created_accept_invites ON profiles;
-- Drop the function too (cleanup)
DROP FUNCTION IF EXISTS public.accept_pending_invitations();
-- Make sure the ta_invitations table exists (safe to re-run)
CREATE TABLE IF NOT EXISTS ta_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    invited_by UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'declined')),
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(course_id, email)
);