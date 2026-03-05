-- ============================================================
-- EvalDEP Supabase Schema (NO RLS VERSION)
-- Run this entire script in Supabase SQL Editor
-- (Project: jdvtidheprbkhtbzlfyq)
-- ============================================================
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- ── 1. PROFILES ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    entry_number TEXT,
    role TEXT NOT NULL CHECK (role IN ('professor', 'ta')),
    department TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
-- ── 2. COURSES ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS courses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    department TEXT,
    semester TEXT,
    instructor_id UUID REFERENCES profiles(id) ON DELETE
    SET NULL,
        master_sheet_url TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
);
-- ── 3. COURSE_TAS (many-to-many: courses ↔ TAs) ─────────────
CREATE TABLE IF NOT EXISTS course_tas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    ta_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    UNIQUE(course_id, ta_id)
);
-- ── 4. STUDENTS ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    roll_number TEXT NOT NULL UNIQUE,
    email TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
-- ── 5. COURSE_STUDENTS (many-to-many: courses ↔ students) ────
CREATE TABLE IF NOT EXISTS course_students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    imported_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(course_id, student_id)
);
-- ── 6. EVALUATIONS ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    total_marks NUMERIC DEFAULT 0,
    negative_marking NUMERIC DEFAULT 0,
    status TEXT DEFAULT 'draft' CHECK (
        status IN ('draft', 'active', 'grading', 'published')
    ),
    subsheet_name TEXT,
    drive_folder_url TEXT,
    answer_key_data JSONB,
    created_by UUID REFERENCES profiles(id) ON DELETE
    SET NULL,
        created_at TIMESTAMPTZ DEFAULT now()
);
-- ── 7. EVALUATION_DUTIES ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS evaluation_duties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_id UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    assignee_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    role_note TEXT,
    assigned_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(evaluation_id, assignee_id)
);
-- ── 8. SUBMISSION_RESULTS ────────────────────────────────────
CREATE TABLE IF NOT EXISTS submission_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_id UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    graded_by UUID REFERENCES profiles(id) ON DELETE
    SET NULL,
        total_score NUMERIC,
        max_score NUMERIC,
        correct_count INT,
        incorrect_count INT,
        unattempted_count INT,
        negative_deduction NUMERIC DEFAULT 0,
        details JSONB,
        comments TEXT DEFAULT '',
        created_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE(evaluation_id, student_id)
);
-- ── AUTO-CREATE PROFILE ON SIGNUP ────────────────────────────
CREATE OR REPLACE FUNCTION public.handle_new_user() RETURNS trigger AS $$ BEGIN
INSERT INTO public.profiles (id, name, role, entry_number, department)
VALUES (
        new.id,
        COALESCE(new.raw_user_meta_data->>'name', 'User'),
        COALESCE(new.raw_user_meta_data->>'role', 'professor'),
        new.raw_user_meta_data->>'entry_number',
        new.raw_user_meta_data->>'department'
    );
RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
AFTER
INSERT ON auth.users FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();
-- ============================================================
-- NOTE: ROW LEVEL SECURITY (RLS) IS INTENTIONALLY DISABLED
-- FOR ALL TABLES IN THIS SCRIPT. 
-- ALL AUTHENTICATED OR UNAUTHENTICATED USERS WITH THE ANON KEY
-- CAN READ/WRITE TO THESE TABLES UNRESTRICTED.
-- ============================================================