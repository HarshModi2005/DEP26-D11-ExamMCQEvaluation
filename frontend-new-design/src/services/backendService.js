const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';

const api = async (path, options = {}) => {
    const res = await fetch(`${BACKEND_URL}/api${path}`, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Backend error');
    }
    return res.json();
};

// Cache rows are scoped by evaluation_id on the backend. Refuse to submit a
// processing request without a real id — the backend will reject it too, but
// failing fast here gives a better error message and avoids a wasted round-trip.
const requireEvaluationId = (evaluationId, action) => {
    if (!evaluationId || String(evaluationId).trim() === '' || String(evaluationId).trim().toLowerCase() === 'default') {
        throw new Error(`Missing evaluationId for ${action}. Every processing run must be tied to a specific quiz so results cannot leak between evaluations.`);
    }
    return String(evaluationId).trim();
};

export const backendService = {
    /**
     * Load answer key from a Google Drive folder URL
     */
    async extractAnswerKeyFromDrive(driveFolderUrl) {
        return api('/answer-key/extract-from-drive', {
            method: 'POST',
            body: JSON.stringify({ folder_url: driveFolderUrl }),
        });
    },

    /**
     * Upload an answer key file
     */
    async uploadAnswerKey(file) {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${BACKEND_URL}/api/answer-key/upload`, {
            method: 'POST',
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Upload failed');
        }
        return res.json();
    },

    /**
     * Set the answer key manually via JSON
     */
    async setAnswerKeyManual({ answers, marksPerQuestion, negativeMarking }) {
        return api('/answer-key/set-manual', {
            method: 'POST',
            body: JSON.stringify({
                answers,
                marks_per_question: marksPerQuestion,
                negative_marking: negativeMarking,
            }),
        });
    },

    /**
     * Get the currently loaded answer key
     */
    async getAnswerKey() {
        return api('/answer-key');
    },

    async processDriveFolder(driveFolderUrl, evaluationId, forceReprocess = false, groupMultiplePages = false) {
        const evalId = requireEvaluationId(evaluationId, 'processDriveFolder');
        const url = forceReprocess ? '/batch/process-folder-optimized?force_reprocess=true' : '/batch/process-folder-optimized';
        return api(url, {
            method: 'POST',
            body: JSON.stringify({
                folder_url: driveFolderUrl,
                evaluation_id: evalId,
                rename_drive_inline: true,
                group_multiple_pages: groupMultiplePages,
            }),
        });
    },

    async startDriveFolderProcessing(driveFolderUrl, evaluationId, forceReprocess = false, groupMultiplePages = false) {
        const evalId = requireEvaluationId(evaluationId, 'startDriveFolderProcessing');
        const url = forceReprocess ? '/batch/process-folder-optimized/start?force_reprocess=true' : '/batch/process-folder-optimized/start';
        return api(url, {
            method: 'POST',
            body: JSON.stringify({
                folder_url: driveFolderUrl,
                evaluation_id: evalId,
                rename_drive_inline: true,
                group_multiple_pages: groupMultiplePages,
            }),
        });
    },

    /**
     * Upload and process a ZIP file containing answer sheets
     */
    async processZipFile(file, evaluationId, forceReprocess = false, extractAnswerKey = true, groupMultiplePages = false) {
        const formData = new FormData();
        formData.append('file', file);
        if (evaluationId) formData.append('evaluation_id', evaluationId);

        const params = new URLSearchParams();
        if (forceReprocess) params.append('force_reprocess', 'true');
        if (!extractAnswerKey) params.append('extract_answer_key', 'false');
        if (groupMultiplePages) params.append('group_multiple_pages', 'true');

        const url = `/process-zip${params.toString() ? '?' + params.toString() : ''}`;

        const res = await fetch(`${BACKEND_URL}/api${url}`, {
            method: 'POST',
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'ZIP processing failed');
        }
        return res.json();
    },

    async startZipProcessing(file, evaluationId, forceReprocess = false, extractAnswerKey = true, groupMultiplePages = false) {
        const formData = new FormData();
        formData.append('file', file);
        if (evaluationId) formData.append('evaluation_id', evaluationId);

        const params = new URLSearchParams();
        if (forceReprocess) params.append('force_reprocess', 'true');
        if (!extractAnswerKey) params.append('extract_answer_key', 'false');
        if (groupMultiplePages) params.append('group_multiple_pages', 'true');

        const url = `/process-zip/start${params.toString() ? '?' + params.toString() : ''}`;
        const res = await fetch(`${BACKEND_URL}/api${url}`, {
            method: 'POST',
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'ZIP processing failed');
        }
        return res.json();
    },

    /**
     * Upload a single PDF where each page is one student's answer sheet.
     * Returns {processing_id, status_url, mapping_url} — poll processing_id
     * via getProcessingStatus() just like the Drive flow.
     */
    async startPdfProcessing(file, evaluationId, forceReprocess = false) {
        const evalId = requireEvaluationId(evaluationId, 'startPdfProcessing');
        const formData = new FormData();
        formData.append('file', file);
        formData.append('evaluation_id', evalId);

        const params = new URLSearchParams();
        if (forceReprocess) params.append('force_reprocess', 'true');
        const url = `/batch/process-pdf-optimized/start${params.toString() ? '?' + params.toString() : ''}`;

        const res = await fetch(`${BACKEND_URL}/api${url}`, { method: 'POST', body: formData });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'PDF processing failed');
        }
        return res.json();
    },

    async processPdfFile(file, evaluationId, forceReprocess = false) {
        const evalId = requireEvaluationId(evaluationId, 'processPdfFile');
        const formData = new FormData();
        formData.append('file', file);
        formData.append('evaluation_id', evalId);

        const params = new URLSearchParams();
        if (forceReprocess) params.append('force_reprocess', 'true');
        const url = `/batch/process-pdf-optimized${params.toString() ? '?' + params.toString() : ''}`;

        const res = await fetch(`${BACKEND_URL}/api${url}`, { method: 'POST', body: formData });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'PDF processing failed');
        }
        return res.json();
    },

    async getPdfMapping(processingId) {
        return api(`/pdf-runs/${processingId}/mapping`);
    },

    async lookupPdfPage(processingId, pageNumber) {
        return api(`/pdf-runs/${processingId}/page/${pageNumber}`);
    },

    async lookupPdfEntry(processingId, entryNumber) {
        return api(`/pdf-runs/${processingId}/entry/${encodeURIComponent(entryNumber)}`);
    },

    getPdfPageImageUrl(processingId, pageNumber) {
        return `${BACKEND_URL}/api/pdf-runs/${processingId}/page/${pageNumber}/image`;
    },

    // Build a download URL for the page-map CSV. `sheetUrl` is optional; when
    // provided, the backend reconciles OCR names/entries against the master
    // Google Sheet (same logic as /sync-results) and fills in matched columns.
    getPdfMappingCsvUrl(processingId, sheetUrl = '', subsheetName = '') {
        const params = new URLSearchParams();
        if (sheetUrl) params.set('sheet_url', sheetUrl);
        if (subsheetName) params.set('subsheet_name', subsheetName);
        const q = params.toString();
        return `${BACKEND_URL}/api/pdf-runs/${processingId}/mapping.csv${q ? `?${q}` : ''}`;
    },

    // Persist master-sheet matched entry_number/name onto pdf_page_map so the
    // /page/{n} and /entry/{x} endpoints return the cleaned values.
    async reconcilePdfMapping(processingId, sheetUrl, subsheetName) {
        return api(`/pdf-runs/${processingId}/reconcile`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sheet_url: sheetUrl, subsheet_name: subsheetName || null }),
        });
    },

    /**
     * Export results to a Google Sheet (optionally a specific tab).
     * This now creates: marks sheet, studentResponse sheet, and Super Sheet entry.
     */
    async exportToSheets(sheetUrl, subsheetName, evaluationName, results = null, answerKey = null) {
        const params = new URLSearchParams();
        if (subsheetName) params.append('subsheet_name', subsheetName);
        if (evaluationName) params.append('evaluation_name', evaluationName);
        const queryStr = params.toString();
        const url = queryStr ? `/export-to-sheets?${queryStr}` : '/export-to-sheets';
        return api(url, {
            method: 'POST',
            body: JSON.stringify({ sheet_url: sheetUrl, results, answer_key: answerKey }),
        });
    },

    /**
     * Preview a Google Sheet (detect columns, list students)
     */
    async previewSheet(sheetUrl) {
        return api(`/sheets/preview?sheet_url=${encodeURIComponent(sheetUrl)}`);
    },

    /**
     * Scan a Drive folder (see what files are in it)
     */
    async scanDriveFolder(driveFolderUrl) {
        return api('/scan-drive-folder', {
            method: 'POST',
            body: JSON.stringify({ folder_url: driveFolderUrl }),
        });
    },

    /**
     * Check backend health / status
     */
    async getStatus() {
        return api('/status');
    },

    /**
     * Export detailed student responses to a separate sheet
     */
    async exportStudentResponses(sheetUrl, evaluationName, results = null, answerKey = null) {
        const params = new URLSearchParams();
        if (evaluationName) params.append('evaluation_name', evaluationName);
        const queryStr = params.toString();
        const url = queryStr ? `/export-student-responses?${queryStr}` : '/export-student-responses';
        return api(url, {
            method: 'POST',
            body: JSON.stringify({ sheet_url: sheetUrl, results, answer_key: answerKey }),
        });
    },

    /**
     * Download answer sheet template
     */
    async downloadTemplate(format = 'csv', numQuestions = 50) {
        const url = `/download-answer-sheet-template?format=${format}&num_questions=${numQuestions}`;
        const res = await fetch(`${BACKEND_URL}/api${url}`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Template download failed');
        }
        return res;
    },

    /**
     * Get cache status and statistics.
     * Pass ``evaluationId`` so the backend returns per-quiz row counts
     * (``evaluation_cache``) — the global ``total_entries`` counts every quiz.
     */
    async getCacheStatus(evaluationId = null) {
        const q = evaluationId ? `?evaluation_id=${encodeURIComponent(evaluationId)}` : '';
        return api(`/cache/status${q}`);
    },

    /**
     * Clear cache
     */
    async clearCache() {
        return api('/cache/clear?confirm=true', { method: 'POST' });
    },

    /**
     * Delete every cache row for a single evaluation (scoped purge).
     * Use this when you want the next run to be fully fresh without nuking
     * caches for other quizzes.
     */
    async purgeCacheForEvaluation(evaluationId) {
        const evalId = requireEvaluationId(evaluationId, 'purgeCacheForEvaluation');
        return api(`/cache/purge-evaluation/${encodeURIComponent(evalId)}`, { method: 'DELETE' });
    },

    /**
     * Get processing status
     */
    async getProcessingStatus(processingId) {
        return api(`/batch/processing-status/${processingId}`);
    },

    async getPipelineRunStatus(runId) {
        return api(`/pipeline-runs/${runId}/status`);
    },

    /**
     * Sync OCR results with master student list from a Google Sheet
     */
    async syncResultsWithSheet(sheetUrl, results, subsheetName) {
        return api('/sync-results', {
            method: 'POST',
            body: JSON.stringify({ sheet_url: sheetUrl, results, subsheet_name: subsheetName }),
        });
    },

    /**
     * Preview how Drive files would be renamed (dry run; no API writes).
     */
    async previewRenameDriveFiles(folderUrl, results = null, skipAlreadyRenamed = false) {
        return api('/rename-drive-files/preview', {
            method: 'POST',
            body: JSON.stringify({
                folder_url: folderUrl,
                results,
                skip_already_renamed: skipAlreadyRenamed,
            }),
        });
    },

    /**
     * Rename files in a Google Drive folder using pipeline results (entry + name).
     */
    async renameDriveFiles(folderUrl, results = null, dryRun = false, skipAlreadyRenamed = false) {
        return api('/rename-drive-files', {
            method: 'POST',
            body: JSON.stringify({
                folder_url: folderUrl,
                results,
                dry_run: dryRun,
                skip_already_renamed: skipAlreadyRenamed,
            }),
        });
    },

    // ── Code Evaluation Pipeline ──

    async processZipCodeEval(file, answerKey) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('answer_key', JSON.stringify(answerKey));
        const res = await fetch(`${BACKEND_URL}/api/code-eval/process-zip`, {
            method: 'POST',
            body: formData,
        });
        if (!res.ok) {
            const text = await res.text();
            throw new Error(text || `Code eval ZIP failed: ${res.status}`);
        }
        return res.json();
    },

    async processDriveCodeEval(folderUrl, answerKey) {
        // api() already prefixes BACKEND_URL + "/api" — do not repeat "/api" here.
        return api('/code-eval/process-drive-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                folder_url: folderUrl,
                answer_key: answerKey,
            }),
        });
    },
};
