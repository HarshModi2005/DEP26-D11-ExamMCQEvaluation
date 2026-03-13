import { supabase } from './supabaseClient';

// Helper: Compute similarity ratio between two strings (like Python's difflib.SequenceMatcher)
function similarityRatio(a, b) {
    if (!a || !b) return 0;
    if (a === b) return 1;
    const longer = a.length >= b.length ? a : b;
    const shorter = a.length >= b.length ? b : a;
    if (longer.length === 0) return 1;

    // Longest common subsequence approach for ratio
    const m = shorter.length;
    const n = longer.length;
    const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            if (shorter[i - 1] === longer[j - 1]) {
                dp[i][j] = dp[i - 1][j - 1] + 1;
            } else {
                dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
            }
        }
    }
    const lcs = dp[m][n];
    return (2.0 * lcs) / (m + n);
}

// Helper: clean roll number (alphanumeric only, uppercase)
function cleanRollString(str) {
    return String(str || '').replace(/[^A-Z0-9]/gi, '').toUpperCase();
}

// Helper: normalize entry number (match backend pattern yyyyBBBnnnn)
function normalizeEntryNumber(raw) {
    if (!raw) return null;
    const clean = raw.trim();
    const pattern = /(\d{4})\s*([A-Za-z]{2,4})\s*(\d{2,5})/;
    const m = clean.match(pattern);
    if (m) {
        return `${m[1]}${m[2].toUpperCase()}${m[3]}`;
    }
    const fallback = clean.replace(/[\s\-_./]/g, '').toUpperCase();
    return fallback.length >= 6 ? fallback : null;
}

// Helper: check name mismatch (mirrors backend logic)
function checkNameMismatch(registryName, ocrName) {
    if (!registryName || !ocrName) return false;
    const s = registryName.trim().toLowerCase();
    const o = ocrName.trim().toLowerCase();
    if (!s || !o || s === 'unknown' || o === 'unknown') return false;
    if (s === o) return false;
    const sParts = new Set(s.split(/\s+/));
    const oParts = new Set(o.split(/\s+/));
    const intersection = [...sParts].filter(w => oParts.has(w));
    if (intersection.length > 0) return false;
    if (s.includes(o) || o.includes(s)) return false;
    for (const word of sParts) { if (word.length >= 3 && o.includes(word)) return false; }
    for (const word of oParts) { if (word.length >= 3 && s.includes(word)) return false; }
    return true; // names are mismatched
}

export const resultsService = {
    /**
     * Save/upsert an array of StudentResult objects for an evaluation.
     * Uses combined entry-number + name scoring (mirrors backend sheets_service).
     * Returns { data, skipped, notFoundRolls, nameMismatches }.
     */
    async saveResults(evaluationId, courseId, results, gradedById) {
        if (!results || results.length === 0) return { data: [], skipped: [], notFoundRolls: [], nameMismatches: [] };

        // Pre-fetch all students in the course for matching
        const { data: allCourseStudents } = await supabase
            .from('course_students')
            .select('student_id, students(id, roll_number, name)')
            .eq('course_id', courseId);

        const courseStudentRegistry = (allCourseStudents || []).map(cs => ({
            id: cs.student_id,
            roll_number: cs.students.roll_number,
            name: cs.students.name || '',
            clean_roll: cleanRollString(cs.students.roll_number),
            normalized: normalizeEntryNumber(cs.students.roll_number)
        }));

        const inserts = [];
        const skipped = [];
        const notFoundRolls = [];
        const nameMismatches = [];
        const claimedStudentIds = new Set();

        // Combined scoring function (mirrors backend _find_best_match)
        function findBestMatch(targetRaw, ocrName) {
            const targetClean = cleanRollString(targetRaw);
            const targetNorm = normalizeEntryNumber(targetRaw);
            const ocrNameClean = (ocrName || '').trim().toLowerCase();

            let bestMatch = null;
            let bestScore = 0;

            for (const reg of courseStudentRegistry) {
                if (claimedStudentIds.has(reg.id)) continue;

                let score = 0;
                const regNameClean = reg.name.trim().toLowerCase();

                // 1. Score Entry Number
                if (targetNorm && reg.normalized) {
                    if (targetNorm === reg.normalized) {
                        score += 100;
                    } else {
                        const ratio = similarityRatio(targetNorm, reg.normalized);
                        if (ratio >= 0.75) {
                            score += Math.floor(50 * ratio);
                        }
                    }
                }
                // Also try cleaned match
                if (score < 100 && targetClean && reg.clean_roll) {
                    if (targetClean === reg.clean_roll) {
                        score = Math.max(score, 100);
                    } else {
                        const ratio = similarityRatio(targetClean, reg.clean_roll);
                        if (ratio >= 0.75) {
                            score = Math.max(score, Math.floor(50 * ratio));
                        }
                    }
                }

                // 2. Score Name
                if (ocrNameClean && regNameClean) {
                    if (ocrNameClean === regNameClean) {
                        score += 100;
                    } else {
                        const ratio = similarityRatio(ocrNameClean, regNameClean);
                        if (ratio >= 0.75) {
                            score += Math.floor(50 * ratio);
                        } else {
                            // Word intersection fallback
                            const sParts = new Set(regNameClean.split(/\s+/));
                            const oParts = new Set(ocrNameClean.split(/\s+/));
                            const intersection = [...sParts].filter(w => oParts.has(w));
                            if (intersection.length >= 2 || (intersection.length >= 1 && sParts.size === 1 && oParts.size === 1)) {
                                score += 30;
                            }
                        }
                    }
                }

                if (score > bestScore && score >= 40) {
                    bestScore = score;
                    bestMatch = reg;
                }
            }

            return bestMatch;
        }

        for (const r of results) {
            const targetRaw = String(r.entry_number || '').trim();
            const ocrName = r.name || '';

            const match = findBestMatch(targetRaw, ocrName);

            if (match) {
                claimedStudentIds.add(match.id);

                // Check for name mismatch
                if (checkNameMismatch(match.name, ocrName)) {
                    nameMismatches.push({
                        entry_number: match.roll_number,
                        sheet_name: match.name,
                        ocr_name: ocrName
                    });
                }

                inserts.push({
                    evaluation_id: evaluationId,
                    student_id: match.id,
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
            } else {
                console.warn(`Student not found in course roster for roll: ${r.entry_number}. Skipping.`);
                skipped.push(r.entry_number || cleanRollString(targetRaw) || 'UNKNOWN');
                notFoundRolls.push(r.entry_number || cleanRollString(targetRaw) || 'UNKNOWN');
            }
        }

        if (skipped.length > 0) {
            console.warn(`Skipped results for unmatched rolls (not in course roster): ${skipped.join(', ')}`);
        }

        if (inserts.length === 0) return { data: [], skipped, notFoundRolls, nameMismatches };

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
        return { data, skipped, notFoundRolls, nameMismatches };
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
