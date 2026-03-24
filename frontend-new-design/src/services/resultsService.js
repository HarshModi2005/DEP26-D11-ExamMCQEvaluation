import { supabase } from './supabaseClient';

export const resultsService = {
    /**
     * Save/upsert an array of StudentResult objects for an evaluation.
     * Matches student by roll_number within the course.
     */
    async saveResults(evaluationId, courseId, results, gradedById) {
        if (!results || results.length === 0) return;

        // ── Helper: batch a Supabase .in() query into chunks ──
        const BATCH = 50;  // safe chunk size for Supabase URL limits

        async function batchIn(table, selectCols, column, values) {
            const all = [];
            for (let i = 0; i < values.length; i += BATCH) {
                const chunk = values.slice(i, i + BATCH);
                const { data, error } = await supabase
                    .from(table)
                    .select(selectCols)
                    .in(column, chunk);
                if (error) throw error;
                if (data) all.push(...data);
            }
            return all;
        }

        // 1. Get unique roll numbers from results
        const uniqueRollNos = [...new Set(results.map(r => r.entry_number).filter(Boolean))];
        console.log(`[saveResults] incoming results: ${results.length}, unique roll numbers: ${uniqueRollNos.length}`);

        // 2. Fetch existing students (batched)
        const existingStudents = await batchIn('students', 'id, roll_number', 'roll_number', uniqueRollNos);
        const existingRollNos = new Set(existingStudents.map(s => s.roll_number));
        console.log(`[saveResults] existing students found: ${existingStudents.length}, missing to insert: ${uniqueRollNos.length - existingRollNos.size}`);

        // 3. Prepare missing students for insertion
        const missingStudents = [];
        const seenRollNos = new Set();

        for (const r of results) {
            if (r.entry_number && !existingRollNos.has(r.entry_number) && !seenRollNos.has(r.entry_number)) {
                missingStudents.push({
                    roll_number: r.entry_number,
                    name: r.name || ''
                });
                seenRollNos.add(r.entry_number);
            }
        }

        // 4. Insert missing students if any (batched)
        if (missingStudents.length > 0) {
            for (let i = 0; i < missingStudents.length; i += BATCH) {
                const chunk = missingStudents.slice(i, i + BATCH);
                const { error: insertErr } = await supabase
                    .from('students')
                    .insert(chunk);
                if (insertErr) {
                    console.error(`Failed to insert student batch ${i}-${i + chunk.length}:`, insertErr);
                }
            }
        }

        // 5. Fetch all needed students again to get their assigned IDs (batched)
        const allStudents = await batchIn('students', 'id, roll_number', 'roll_number', uniqueRollNos);
        const studentMap = new Map(allStudents.map(s => [s.roll_number, s.id]));
        console.log(`[saveResults] studentMap size after re-fetch: ${studentMap.size}`);

        const insertsMap = new Map();

        for (const r of results) {
            if (!r.entry_number) continue;

            const studentId = studentMap.get(r.entry_number);

            if (!studentId) {
                console.warn(`Student not found and could not be created for roll: ${r.entry_number}`);
                continue;
            }

            insertsMap.set(studentId, {
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

        const inserts = Array.from(insertsMap.values());

        console.log(`[saveResults] insertsMap size: ${insertsMap.size}, inserts array: ${inserts.length}`);
        if (inserts.length === 0) return [];

        // 6. True Synchronization: Delete any existing results for this evaluation that are NOT in the new batch
        const { data: existingRecords } = await supabase
            .from('submission_results')
            .select('student_id')
            .eq('evaluation_id', evaluationId);

        if (existingRecords && existingRecords.length > 0) {
            const keepSet = new Set(inserts.map(i => i.student_id));
            const toDelete = existingRecords.map(r => r.student_id).filter(id => !keepSet.has(id));

            if (toDelete.length > 0) {
                for (let i = 0; i < toDelete.length; i += BATCH) {
                    const chunk = toDelete.slice(i, i + BATCH);
                    const { error: deleteErr } = await supabase
                        .from('submission_results')
                        .delete()
                        .eq('evaluation_id', evaluationId)
                        .in('student_id', chunk);
                    if (deleteErr) {
                        console.error('Failed to delete obsolete results during sync:', deleteErr);
                    }
                }
            }
        }

        // 7. Upsert results in batches
        let allData = [];
        for (let i = 0; i < inserts.length; i += BATCH) {
            const chunk = inserts.slice(i, i + BATCH);
            const { data, error } = await supabase
                .from('submission_results')
                .upsert(chunk, { onConflict: 'evaluation_id,student_id' })
                .select();
            if (error) throw error;
            if (data) allData.push(...data);
        }
        return allData;
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
     * Delete all results for an evaluation to start fresh
     */
    async clearResultsByEvaluation(evaluationId) {
        const { error } = await supabase
            .from('submission_results')
            .delete()
            .eq('evaluation_id', evaluationId);
        if (error) throw error;
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
