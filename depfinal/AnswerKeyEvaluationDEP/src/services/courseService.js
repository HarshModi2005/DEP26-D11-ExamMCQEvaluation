import { supabase } from './supabaseClient';

export const courseService = {
    /**
     * Fetch all courses for a professor (by instructor_id)
     */
    async getCoursesByProfessor(professorId) {
        console.log('[CourseService] getCoursesByProfessor called, professorId:', professorId);
        const startTime = Date.now();
        const { data, error } = await supabase
            .from('courses')
            .select('*, profiles!courses_instructor_id_fkey(name)')
            .eq('instructor_id', professorId)
            .order('created_at', { ascending: false });
        const elapsed = Date.now() - startTime;
        if (error) {
            console.error('[CourseService] getCoursesByProfessor error after', elapsed, 'ms:', error.message, 'code:', error.code, 'details:', error.details);
            throw error;
        }
        console.log('[CourseService] getCoursesByProfessor success after', elapsed, 'ms, count:', data?.length);
        return data;
    },

    /**
     * Fetch all courses a TA is assigned to
     */
    async getCoursesByTA(taId) {
        console.log('[CourseService] getCoursesByTA called, taId:', taId);
        const startTime = Date.now();
        const { data, error } = await supabase
            .from('course_tas')
            .select('course_id, courses(*, profiles!courses_instructor_id_fkey(name))')
            .eq('ta_id', taId);
        const elapsed = Date.now() - startTime;
        if (error) {
            console.error('[CourseService] getCoursesByTA error after', elapsed, 'ms:', error.message);
            throw error;
        }
        console.log('[CourseService] getCoursesByTA success after', elapsed, 'ms, count:', data?.length);
        return data.map(row => row.courses);
    },

    /**
     * Get a single course by ID with instructor details
     */
    async getCourseById(courseId) {
        console.log('[CourseService] getCourseById called, courseId:', courseId);
        const startTime = Date.now();
        const { data, error } = await supabase
            .from('courses')
            .select('*, profiles!courses_instructor_id_fkey(id, name, department)')
            .eq('id', courseId)
            .single();
        const elapsed = Date.now() - startTime;
        if (error) {
            console.error('[CourseService] getCourseById error after', elapsed, 'ms:', error.message);
            throw error;
        }
        console.log('[CourseService] getCourseById success after', elapsed, 'ms:', data?.code, data?.title);
        return data;
    },

    /**
     * Helper to validate that a master sheet URL is unique across the system.
     * Throws an error if the URL is already taken by another course.
     */
    async validateMasterSheetUrl(url, excludeCourseId = null) {
        if (!url) return;
        let query = supabase.from('courses').select('id, code, title').eq('master_sheet_url', url);
        if (excludeCourseId) {
            query = query.neq('id', excludeCourseId);
        }
        const { data, error } = await query;
        if (error) throw error;
        if (data && data.length > 0) {
            const conflict = data[0];
            throw new Error(`This Google Sheet is already in use by another course (${conflict.code} - ${conflict.title}). Please provide a unique sheet URL.`);
        }
    },

    /**
     * Create a new course
     */
    async createCourse({ code, title, description, department, semester, instructorId, masterSheetUrl }) {
        console.log('[CourseService] createCourse called, code:', code, 'title:', title);
        await this.validateMasterSheetUrl(masterSheetUrl);
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
        if (error) {
            console.error('[CourseService] createCourse error:', error.message);
            throw error;
        }
        console.log('[CourseService] createCourse success, id:', data?.id);
        return data;
    },

    /**
     * Update course details (e.g. master_sheet_url)
     */
    async updateCourse(courseId, updates) {
        console.log('[CourseService] updateCourse called, courseId:', courseId);
        if (updates.master_sheet_url !== undefined) {
            await this.validateMasterSheetUrl(updates.master_sheet_url, courseId);
        }
        const { data, error } = await supabase
            .from('courses')
            .update(updates)
            .eq('id', courseId)
            .select()
            .single();
        if (error) {
            console.error('[CourseService] updateCourse error:', error.message);
            throw error;
        }
        console.log('[CourseService] updateCourse success');
        return data;
    },

    /**
     * Delete a course
     */
    async deleteCourse(courseId) {
        console.log('[CourseService] deleteCourse called, courseId:', courseId);
        const { error } = await supabase.from('courses').delete().eq('id', courseId);
        if (error) {
            console.error('[CourseService] deleteCourse error:', error.message);
            throw error;
        }
        console.log('[CourseService] deleteCourse success');
    },
};
