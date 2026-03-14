import { supabase } from './supabaseClient';

export const evaluationService = {
    /**
     * Get all evaluations for a course
     */
    async getEvaluationsByCourse(courseId) {
        const { data, error } = await supabase
            .from('evaluations')
            .select(`
                *,
                evaluation_duties(assignee_id, profiles(name, role))
            `)
            .eq('course_id', courseId)
            .order('created_at', { ascending: false });
        if (error) throw error;
        return data;
    },

    /**
     * Get a single evaluation by ID
     */
    async getEvaluationById(evaluationId) {
        const { data, error } = await supabase
            .from('evaluations')
            .select(`
                *,
                courses(id, title, code, master_sheet_url, instructor_id),
                evaluation_duties(assignee_id, profiles(id, name, role))
            `)
            .eq('id', evaluationId)
            .single();
        if (error) throw error;
        return data;
    },

    /**
     * Create a new evaluation
     */
    async createEvaluation({ courseId, name, totalMarks, negativeMarking, subsheetName, driveFolderUrl, assigneeIds, createdBy }) {
        // Insert evaluation
        const { data: evaluation, error } = await supabase
            .from('evaluations')
            .insert({
                course_id: courseId,
                name,
                total_marks: totalMarks || 0,
                negative_marking: negativeMarking || 0,
                subsheet_name: subsheetName || null,
                drive_folder_url: driveFolderUrl || null,
                status: 'draft',
                created_by: createdBy,
            })
            .select()
            .single();
        if (error) throw error;

        // Insert duties if any assignees provided
        if (assigneeIds?.length > 0) {
            const duties = assigneeIds.map(id => ({
                evaluation_id: evaluation.id,
                assignee_id: id,
            }));
            const { error: dutyError } = await supabase.from('evaluation_duties').insert(duties);
            if (dutyError) throw dutyError;
        }

        return evaluation;
    },

    /**
     * Update evaluation status
     */
    async updateStatus(evaluationId, status) {
        const { data, error } = await supabase
            .from('evaluations')
            .update({ status })
            .eq('id', evaluationId)
            .select()
            .single();
        if (error) throw error;
        return data;
    },

    /**
     * Save answer key data to an evaluation
     */
    async saveAnswerKey(evaluationId, answerKeyData) {
        const { data, error } = await supabase
            .from('evaluations')
            .update({ answer_key_data: answerKeyData })
            .eq('id', evaluationId)
            .select()
            .single();
        if (error) throw error;
        return data;
    },

    /**
     * Update drive folder URL
     */
    async updateDriveFolderUrl(evaluationId, driveFolderUrl) {
        const { data, error } = await supabase
            .from('evaluations')
            .update({ drive_folder_url: driveFolderUrl })
            .eq('id', evaluationId)
            .select()
            .single();
        if (error) throw error;
        return data;
    },

    /**
     * Update duties (replace all for this evaluation)
     */
    async updateDuties(evaluationId, assigneeIds) {
        // Delete existing duties
        await supabase.from('evaluation_duties').delete().eq('evaluation_id', evaluationId);
        // Insert new
        if (assigneeIds.length > 0) {
            const duties = assigneeIds.map(id => ({
                evaluation_id: evaluationId,
                assignee_id: id,
            }));
            const { error } = await supabase.from('evaluation_duties').insert(duties);
            if (error) throw error;
        }
    },

    /**
     * Fetch all evaluations assigned to a user (via evaluation_duties).
     * Returns evaluations with joined course info.
     */
    async getMyAssignedEvaluations(userId) {
        const { data, error } = await supabase
            .from('evaluation_duties')
            .select(`
                evaluation_id,
                evaluations(
                    id, name, status, total_marks, negative_marking,
                    created_at, subsheet_name, drive_folder_url,
                    courses(id, code, title)
                )
            `)
            .eq('assignee_id', userId);
        if (error) throw error;
        return (data || []).map(d => d.evaluations).filter(Boolean);
    },

    /**
     * Fetch all evaluations created by a user (professor self-assigned case).
     * Returns evaluations with joined course info.
     */
    async getMyCreatedEvaluations(userId) {
        const { data, error } = await supabase
            .from('evaluations')
            .select(`*, courses(id, code, title)`)
            .eq('created_by', userId);
        if (error) throw error;
        return data || [];
    },

    /**
     * Update the has_mismatches flag for an evaluation
     */
    async updateHasMismatches(evaluationId, hasMismatches) {
        const { data, error } = await supabase
            .from('evaluations')
            .update({ has_mismatches: hasMismatches })
            .eq('id', evaluationId)
            .select()
            .single();
        if (error) throw error;
        return data;
    },

    /**
     * Dismiss mismatch alerts for an evaluation
     */
    async dismissMismatches(evaluationId) {
        return this.updateHasMismatches(evaluationId, false);
    }
};
