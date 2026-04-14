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

    async processDriveFolder(driveFolderUrl, evaluationId, forceReprocess = false) {
        // Updated to use the ultra-optimized parallel pipelined endpoint
        const url = forceReprocess ? '/batch/process-folder-optimized?force_reprocess=true' : '/batch/process-folder-optimized';
        return api(url, {
            method: 'POST',
            body: JSON.stringify({
                folder_url: driveFolderUrl,
                evaluation_id: evaluationId,
                rename_drive_inline: true,
            }),
        });
    },

    async startDriveFolderProcessing(driveFolderUrl, evaluationId, forceReprocess = false) {
        const url = forceReprocess ? '/batch/process-folder-optimized/start?force_reprocess=true' : '/batch/process-folder-optimized/start';
        return api(url, {
            method: 'POST',
            body: JSON.stringify({
                folder_url: driveFolderUrl,
                evaluation_id: evaluationId,
                rename_drive_inline: true,
            }),
        });
    },

    /**
     * Upload and process a ZIP file containing answer sheets
     */
    async processZipFile(file, evaluationId, forceReprocess = false, extractAnswerKey = true) {
        const formData = new FormData();
        formData.append('file', file);
        if (evaluationId) formData.append('evaluation_id', evaluationId);

        const params = new URLSearchParams();
        if (forceReprocess) params.append('force_reprocess', 'true');
        if (!extractAnswerKey) params.append('extract_answer_key', 'false');

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

    async startZipProcessing(file, evaluationId, forceReprocess = false, extractAnswerKey = true) {
        const formData = new FormData();
        formData.append('file', file);
        if (evaluationId) formData.append('evaluation_id', evaluationId);

        const params = new URLSearchParams();
        if (forceReprocess) params.append('force_reprocess', 'true');
        if (!extractAnswerKey) params.append('extract_answer_key', 'false');

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
     * Upload and process a ZIP file through Code Evaluation
     */
    async processZipCodeEval(file, answerKeyData) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('answer_key_json', JSON.stringify(answerKeyData));

        const res = await fetch(`${BACKEND_URL}/api/code-eval/process-zip`, {
            method: 'POST',
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Code evaluation ZIP processing failed');
        }
        return res.json();
    },

    /**
     * Process a Drive Folder through Code Evaluation
     */
    async processDriveCodeEval(driveFolderUrl, answerKeyData) {
        return api('/code-eval/process-drive-folder', {
            method: 'POST',
            body: JSON.stringify({ folder_url: driveFolderUrl, answer_key: answerKeyData }),
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
     * Get cache status and statistics
     */
    async getCacheStatus() {
        return api('/cache/status');
    },

    /**
     * Clear cache
     */
    async clearCache() {
        return api('/cache/clear?confirm=true', { method: 'POST' });
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
};
