import { supabase } from './supabaseClient';

export const resultsService = {
    /**
     * Save/upsert an array of StudentResult objects for an evaluation.
     * Matches student by roll_number within the course.
     */
    async saveResults(evaluationId, courseId, results, gradedById) {
        if (!results || results.length === 0) return;

        const inserts = [];
        const skipped = [];

        for (const r of results) {
            let studentId = null;

            // Look up the student via the course_students junction table
            const { data: courseStudent } = await supabase
                .from('course_students')
                .select('student_id, students(id, roll_number)')
                .eq('course_id', courseId)
                .eq('students.roll_number', r.entry_number)
                .maybeSingle();

            if (courseStudent?.student_id) {
                studentId = courseStudent.student_id;
            } else {
                // Fallback: search all students globally by roll number (case-insensitive)
                const { data: globalStudents } = await supabase
                    .from('students')
                    .select('id, roll_number')
                    .ilike('roll_number', r.entry_number);

                if (globalStudents && globalStudents.length === 1) {
                    studentId = globalStudents[0].id;
                    console.warn(`Matched student globally: ${r.entry_number} -> ${globalStudents[0].roll_number}`);
                } else if (globalStudents && globalStudents.length > 1) {
                    // Multiple global matches — try exact match
                    const exact = globalStudents.find(s => s.roll_number.toUpperCase() === r.entry_number.toUpperCase());
                    if (exact) studentId = exact.id;
                    else console.warn(`Multiple students found for roll: ${r.entry_number}, unable to match.`);
                } else {
                    console.warn(`Student not found for roll: ${r.entry_number}. Saving result without student link.`);
                    skipped.push(r.entry_number);
                }
            }

            inserts.push({
                evaluation_id: evaluationId,
                student_id: studentId,
                graded_by: gradedById,
                total_score: r.total_score,
                max_score: r.max_score,
                correct_count: r.correct_count,
                incorrect_count: r.incorrect_count,
                unattempted_count: r.unattempted_count,
                negative_deduction: r.negative_deduction || 0,
                details: r.details || [],
                // Store roll number in comments when student couldn't be linked
                comments: studentId ? (r.comments || '') : `[Roll: ${r.entry_number}] ${r.comments || ''}`,
            });
        }

        if (skipped.length > 0) {
            console.warn(`Results saved without student match for rolls: ${skipped.join(', ')}`);
        }

        if (inserts.length === 0) return;

        const { data, error } = await supabase
            .from('submission_results')
            .upsert(inserts, { onConflict: 'evaluation_id,student_id' })
            .select();
        if (error) {
            console.error('Supabase upsert error:', error);
            throw error;
        }
        return data;
    },

    /**
     * Get all results for an evaluation, joined with student info
     */
    async getResultsByEvaluation(evaluationId) {
        const { data, error } = await supabase
            .from('submission_results')
            .select('*, students(name, roll_number), profiles!submission_results_graded_by_fkey(name)')
            .eq('evaluation_id', evaluationId)
            .order('total_score', { ascending: false });
        if (error) throw error;
        return data;
    },

    /**
     * Update a single result's comment
     */
    async updateComment(resultId, comment) {
        const { error } = await supabase
            .from('submission_results')
            .update({ comments: comment })
            .eq('id', resultId);
        if (error) throw error;
    },

    /**
     * Compute aggregate analytics for an evaluation
     */
    async getAnalytics(evaluationId) {
        const { data, error } = await supabase
            .from('submission_results')
            .select('total_score, max_score, correct_count, incorrect_count, unattempted_count, details')
            .eq('evaluation_id', evaluationId);
        if (error) throw error;
        if (!data || data.length === 0) return null;

        const scores = data.map(r => r.total_score);
        const maxScore = data[0].max_score;
        const total = scores.length;
        const avg = scores.reduce((a, b) => a + b, 0) / total;
        const sorted = [...scores].sort((a, b) => a - b);
        const median = sorted[Math.floor(total / 2)];
        const highest = Math.max(...scores);
        const lowest = Math.min(...scores);

        // Score distribution buckets (0-25%, 25-50%, 50-75%, 75-100%)
        const distribution = [
            { range: '0-25%', count: scores.filter(s => s / maxScore < 0.25).length },
            { range: '25-50%', count: scores.filter(s => s / maxScore >= 0.25 && s / maxScore < 0.5).length },
            { range: '50-75%', count: scores.filter(s => s / maxScore >= 0.5 && s / maxScore < 0.75).length },
            { range: '75-100%', count: scores.filter(s => s / maxScore >= 0.75).length },
        ];

        // Question-wise correctness from JSONB details
        const questionStats = {};
        for (const row of data) {
            if (Array.isArray(row.details)) {
                for (const qr of row.details) {
                    const qn = qr.question_number;
                    if (!questionStats[qn]) questionStats[qn] = { correct: 0, total: 0 };
                    questionStats[qn].total += 1;
                    if (qr.result === 'correct') questionStats[qn].correct += 1;
                }
            }
        }

        const questionArray = Object.entries(questionStats).map(([qn, stat]) => ({
            question: `Q${qn}`,
            correctRate: stat.total > 0 ? Math.round((stat.correct / stat.total) * 100) : 0,
        }));

        const hardest = questionArray.sort((a, b) => a.correctRate - b.correctRate)[0];
        const easiest = questionArray.sort((a, b) => b.correctRate - a.correctRate)[0];

        return {
            totalStudents: total,
            gradedCount: total,
            averageScore: avg.toFixed(1),
            medianScore: median.toFixed(1),
            highestScore: highest,
            lowestScore: lowest,
            maxScore,
            distribution,
            hardestQuestion: hardest,
            easiestQuestion: easiest,
        };
    },
};
