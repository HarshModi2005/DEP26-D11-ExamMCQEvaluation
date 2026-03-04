import { supabase } from './supabaseClient';

export const studentService = {
    /**
     * Get all students in a course
     */
    async getStudentsByCourse(courseId) {
        const { data, error } = await supabase
            .from('course_students')
            .select('*, students(*)')
            .eq('course_id', courseId)
            .order('imported_at', { ascending: true });
        if (error) throw error;
        return data.map(row => row.students);
    },

    /**
     * Import students into a course from a parsed list.
     * Each student: { name, roll_number, email }
     * Upserts to students table, then links in course_students.
     */
    async importStudents(courseId, studentList) {
        if (!studentList || studentList.length === 0) return;

        // Upsert into students table
        const { data: upserted, error: upsertError } = await supabase
            .from('students')
            .upsert(
                studentList.map(s => ({
                    name: s.name,
                    roll_number: s.roll_number,
                    email: s.email || null,
                })),
                { onConflict: 'roll_number' }
            )
            .select('id, roll_number');
        if (upsertError) throw upsertError;

        // Link each student to the course (ignore duplicates)
        const links = upserted.map(s => ({
            course_id: courseId,
            student_id: s.id,
        }));

        const { error: linkError } = await supabase
            .from('course_students')
            .upsert(links, { onConflict: 'course_id,student_id', ignoreDuplicates: true });
        if (linkError) throw linkError;

        return upserted;
    },

    /**
     * Remove a student from a course (not from the students table globally)
     */
    async removeStudentFromCourse(courseId, studentId) {
        const { error } = await supabase
            .from('course_students')
            .delete()
            .eq('course_id', courseId)
            .eq('student_id', studentId);
        if (error) throw error;
    },

    /**
     * Find a student by roll number
     */
    async findByRollNumber(rollNumber) {
        const { data, error } = await supabase
            .from('students')
            .select('*')
            .eq('roll_number', rollNumber)
            .single();
        if (error && error.code !== 'PGRST116') throw error;
        return data;
    },
};
