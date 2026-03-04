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

    /**
     * Process all student answer sheets in a Drive folder
     */
    async processDriveFolder(driveFolderUrl) {
        return api('/process-drive-folder', {
            method: 'POST',
            body: JSON.stringify({ folder_url: driveFolderUrl }),
        });
    },

    /**
     * Export results to a Google Sheet (optionally a specific tab)
     */
    async exportToSheets(sheetUrl, subsheetName) {
        const url = subsheetName
            ? `/export-to-sheets?subsheet_name=${encodeURIComponent(subsheetName)}`
            : '/export-to-sheets';
        return api(url, {
            method: 'POST',
            body: JSON.stringify({ sheet_url: sheetUrl }),
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
};
