import { supabase } from './supabaseClient';

export const teamService = {
    /**
     * Get all TAs for a course with their profiles
     */
    async getTAsByCourse(courseId) {
        const { data, error } = await supabase
            .from('course_tas')
            .select('*, profiles!course_tas_ta_id_fkey(id, name, entry_number, department, role)')
            .eq('course_id', courseId);
        if (error) throw error;
        return data.map(row => row.profiles);
    },

    /**
     * Add a TA to a course by their profile ID
     */
    async addTA(courseId, taId) {
        const { data, error } = await supabase
            .from('course_tas')
            .insert({ course_id: courseId, ta_id: taId })
            .select()
            .single();
        if (error) throw error;
        return data;
    },

    /**
     * Remove a TA from a course
     */
    async removeTA(courseId, taId) {
        const { error } = await supabase
            .from('course_tas')
            .delete()
            .eq('course_id', courseId)
            .eq('ta_id', taId);
        if (error) throw error;
    },

    /**
     * Search for TAs by entry number or name (for invite flow)
     */
    async searchTAs(query) {
        const { data, error } = await supabase
            .from('profiles')
            .select('id, name, entry_number, department')
            .eq('role', 'ta')
            .or(`name.ilike.%${query}%,entry_number.ilike.%${query}%`)
            .limit(10);
        if (error) throw error;
        return data;
    },

    /**
     * Get all professors (for listing instructors)
     */
    async getProfessors() {
        const { data, error } = await supabase
            .from('profiles')
            .select('id, name, department')
            .eq('role', 'professor');
        if (error) throw error;
        return data;
    },
};
