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

    async processDriveFolder(driveFolderUrl, evaluationId, forceReprocess = false, masterSheetUrl = null) {
        // Updated to use the ultra-optimized parallel pipelined endpoint
        const url = forceReprocess ? '/batch/process-folder-optimized?force_reprocess=true' : '/batch/process-folder-optimized';
        return api(url, {
            method: 'POST',
            body: JSON.stringify({ 
                folder_url: driveFolderUrl, 
                evaluation_id: evaluationId,
                master_sheet_url: masterSheetUrl 
            }),
        });
    },

    /**
     * Upload and process a ZIP file containing answer sheets
     */
    async processZipFile(file, evaluationId, forceReprocess = false, extractAnswerKey = true, masterSheetUrl = null) {
        const formData = new FormData();
        formData.append('file', file);
        if (evaluationId) formData.append('evaluation_id', evaluationId);
        if (masterSheetUrl) formData.append('master_sheet_url', masterSheetUrl);

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
    async getProcessingStatus() {
        return api('/processing/status');
    },

    async syncFromSheets(sheetUrl, sheetTabName) {
        const res = await api('/sync-from-sheets', {
            method: 'POST',
            body: JSON.stringify({
                sheet_url: sheetUrl,
                sheet_tab_name: sheetTabName
            }),
        });
        return res.data;
    },
};
