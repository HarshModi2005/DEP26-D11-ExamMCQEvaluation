import { supabase } from './supabaseClient';

// Helper: Levenshtein distance
function getLevenshteinDistance(a, b) {
    if (a.length === 0) return b.length;
    if (b.length === 0) return a.length;
    const matrix = [];
    for (let i = 0; i <= b.length; i++) {
        matrix[i] = [i];
    }
    for (let j = 0; j <= a.length; j++) {
        matrix[0][j] = j;
    }
    for (let i = 1; i <= b.length; i++) {
        for (let j = 1; j <= a.length; j++) {
            if (b.charAt(i - 1) === a.charAt(j - 1)) {
                matrix[i][j] = matrix[i - 1][j - 1];
            } else {
                matrix[i][j] = Math.min(
                    matrix[i - 1][j - 1] + 1,
                    Math.min(matrix[i][j - 1] + 1, matrix[i - 1][j] + 1)
                );
            }
        }
    }
    return matrix[b.length][a.length];
}

// Helper: clean roll number (alphanumeric only, uppercase)
function cleanRollString(str) {
    return String(str || '').replace(/[^A-Z0-9]/gi, '').toUpperCase();
}

export const resultsService = {
    /**
     * Save/upsert an array of StudentResult objects for an evaluation.
     * Matches student by roll_number within the course.
     */
    async saveResults(evaluationId, courseId, results, gradedById) {
        if (!results || results.length === 0) return;

        // Pre-fetch all students in the course for fuzzy matching
        const { data: allCourseStudents } = await supabase
            .from('course_students')
            .select('student_id, students(id, roll_number)')
            .eq('course_id', courseId);

        const courseStudentRegistry = (allCourseStudents || []).map(cs => ({
            id: cs.student_id,
            roll_number: cs.students.roll_number,
            clean_roll: cleanRollString(cs.students.roll_number)
        }));

        const inserts = [];
        const skipped = [];

        for (const r of results) {
            let studentId = null;
            const targetRaw = String(r.entry_number || '').trim();
            const targetClean = cleanRollString(targetRaw);

            // 1. Exact match against course registry
            let match = courseStudentRegistry.find(s => s.roll_number.toUpperCase() === targetRaw.toUpperCase());

            // 2. Clean alphanumeric match against course registry
            if (!match) {
                match = courseStudentRegistry.find(s => s.clean_roll === targetClean);
            }

            // 3. Fuzzy match (Levenshtein distance <= 2) against course registry
            if (!match && targetClean.length > 5) {
                let bestMatch = null;
                let bestDist = 3; // Max threshold is 2

                for (const reg of courseStudentRegistry) {
                    const dist = getLevenshteinDistance(targetClean, reg.clean_roll);
                    if (dist < bestDist) {
                        bestDist = dist;
                        bestMatch = reg;
                    }
                }
                if (bestMatch) {
                    match = bestMatch;
                    console.log(`Fuzzy matched OCR typo [${targetRaw}] to student [${match.roll_number}]`);
                }
            }

            if (match) {
                studentId = match.id;
            } else {
                console.warn(`Student not found for roll: ${r.entry_number}. Auto-creating new student record.`);
                const cleanRoll = targetClean || 'UNKNOWN';

                const { data: newStudent, error: createErr } = await supabase
                    .from('students')
                    .upsert([{ roll_number: cleanRoll, name: r.name || 'Unknown' }], { onConflict: 'roll_number' })
                    .select('id')
                    .single();

                if (newStudent) {
                    studentId = newStudent.id;
                    // Link new student to course
                    await supabase.from('course_students').upsert([{
                        course_id: courseId,
                        student_id: studentId
                    }], { onConflict: 'course_id,student_id', ignoreDuplicates: true });
                } else {
                    console.error(`Failed to create missing student ${r.entry_number}`, createErr);
                    skipped.push(r.entry_number);
                }
            }

            if (!studentId) {
                console.warn(`Skipping result for ${r.entry_number} because student_id is null`);
                continue;
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
                comments: r.comments || '',
            });
        }

        if (skipped.length > 0) {
            console.warn(`Results saved without student match for rolls: ${skipped.join(', ')}`);
        }

        if (inserts.length === 0) return;

        // Clear existing results for this evaluation to prevent ghost duplicates from previous runs
        const { error: deleteError } = await supabase
            .from('submission_results')
            .delete()
            .eq('evaluation_id', evaluationId);

        if (deleteError) {
            console.error('Failed to clear old results:', deleteError);
            throw deleteError;
        }

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
