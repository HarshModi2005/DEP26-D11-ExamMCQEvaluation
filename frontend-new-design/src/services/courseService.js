import { supabase } from './supabaseClient';

export const courseService = {
    /**
     * Fetch all courses for a professor (by instructor_id)
     */
    async getCoursesByProfessor(professorId) {
        const { data, error } = await supabase
            .from('courses')
            .select('*, profiles!courses_instructor_id_fkey(name)')
            .eq('instructor_id', professorId)
            .order('created_at', { ascending: false });
        if (error) throw error;
        return data;
    },

    /**
     * Fetch all courses a TA is assigned to
     */
    async getCoursesByTA(taId) {
        const { data, error } = await supabase
            .from('course_tas')
            .select('course_id, courses(*, profiles!courses_instructor_id_fkey(name))')
            .eq('ta_id', taId);
        if (error) throw error;
        return data.map(row => row.courses);
    },

    /**
     * Get a single course by ID with instructor details
     */
    async getCourseById(courseId) {
        const { data, error } = await supabase
            .from('courses')
            .select('*, profiles!courses_instructor_id_fkey(id, name, department)')
            .eq('id', courseId)
            .single();
        if (error) throw error;
        return data;
    },

    /**
     * Create a new course
     */
    async createCourse({ code, title, description, department, semester, instructorId, masterSheetUrl }) {
        const { data, error } = await supabase
            .from('courses')
            .insert({
                code,
                title,
                description,
                department,
                semester,
                instructor_id: instructorId,
                master_sheet_url: masterSheetUrl || null,
            })
            .select()
            .single();
        if (error) throw error;
        return data;
    },

    /**
     * Update course details (e.g. master_sheet_url)
     */
    async updateCourse(courseId, updates) {
        const { data, error } = await supabase
            .from('courses')
            .update(updates)
            .eq('id', courseId)
            .select()
            .single();
        if (error) throw error;
        return data;
    },

    /**
     * Delete a course
     */
    async deleteCourse(courseId) {
        const { error } = await supabase.from('courses').delete().eq('id', courseId);
        if (error) throw error;
    },
};
