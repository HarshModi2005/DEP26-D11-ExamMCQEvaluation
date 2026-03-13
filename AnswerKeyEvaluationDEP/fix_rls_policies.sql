-- ============================================================
-- FIX: Infinite Recursion in RLS Policies
-- Run this in Supabase SQL Editor
-- ============================================================
-- Drop the problematic policies that cause circular references
DROP POLICY IF EXISTS "courses_select" ON courses;
DROP POLICY IF EXISTS "course_tas_select" ON course_tas;
DROP POLICY IF EXISTS "course_tas_insert" ON course_tas;
DROP POLICY IF EXISTS "course_tas_delete" ON course_tas;
DROP POLICY IF EXISTS "course_students_select" ON course_students;
DROP POLICY IF EXISTS "course_students_insert" ON course_students;
DROP POLICY IF EXISTS "course_students_delete" ON course_students;
DROP POLICY IF EXISTS "evaluations_select" ON evaluations;
DROP POLICY IF EXISTS "evaluations_insert" ON evaluations;
DROP POLICY IF EXISTS "evaluations_update" ON evaluations;
-- ── COURSES: allow professors and TAs to see their courses ──
-- Use a direct lookup on course_tas without referencing courses back
CREATE POLICY "courses_select" ON courses FOR
SELECT USING (
        instructor_id = auth.uid()
        OR id IN (
            SELECT course_id
            FROM course_tas
            WHERE ta_id = auth.uid()
        )
    );
-- ── COURSE_TAS: professors manage, TAs see their own ──
-- Avoid referencing courses table to break the loop
CREATE POLICY "course_tas_select" ON course_tas FOR
SELECT USING (
        ta_id = auth.uid()
        OR course_id IN (
            SELECT id
            FROM courses
            WHERE instructor_id = auth.uid()
        )
    );
CREATE POLICY "course_tas_insert" ON course_tas FOR
INSERT WITH CHECK (
        course_id IN (
            SELECT id
            FROM courses
            WHERE instructor_id = auth.uid()
        )
    );
CREATE POLICY "course_tas_delete" ON course_tas FOR DELETE USING (
    course_id IN (
        SELECT id
        FROM courses
        WHERE instructor_id = auth.uid()
    )
);
-- ── COURSE_STUDENTS: course members can read ──
CREATE POLICY "course_students_select" ON course_students FOR
SELECT USING (
        course_id IN (
            SELECT id
            FROM courses
            WHERE instructor_id = auth.uid()
        )
        OR course_id IN (
            SELECT course_id
            FROM course_tas
            WHERE ta_id = auth.uid()
        )
    );
CREATE POLICY "course_students_insert" ON course_students FOR
INSERT WITH CHECK (
        course_id IN (
            SELECT id
            FROM courses
            WHERE instructor_id = auth.uid()
        )
        OR course_id IN (
            SELECT course_id
            FROM course_tas
            WHERE ta_id = auth.uid()
        )
    );
CREATE POLICY "course_students_delete" ON course_students FOR DELETE USING (
    course_id IN (
        SELECT id
        FROM courses
        WHERE instructor_id = auth.uid()
    )
);
-- ── EVALUATIONS: course members can read ──
CREATE POLICY "evaluations_select" ON evaluations FOR
SELECT USING (
        course_id IN (
            SELECT id
            FROM courses
            WHERE instructor_id = auth.uid()
        )
        OR course_id IN (
            SELECT course_id
            FROM course_tas
            WHERE ta_id = auth.uid()
        )
    );
CREATE POLICY "evaluations_insert" ON evaluations FOR
INSERT WITH CHECK (
        course_id IN (
            SELECT id
            FROM courses
            WHERE instructor_id = auth.uid()
        )
    );
CREATE POLICY "evaluations_update" ON evaluations FOR
UPDATE USING (
        course_id IN (
            SELECT id
            FROM courses
            WHERE instructor_id = auth.uid()
        )
        OR id IN (
            SELECT evaluation_id
            FROM evaluation_duties
            WHERE assignee_id = auth.uid()
        )
    );