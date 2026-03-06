const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';

// Default timeout: 5 minutes. For OCR pipelines, we use a longer timeout.
const api = async (path, options = {}, timeoutMs = 300000) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
        const res = await fetch(`${BACKEND_URL}/api${path}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            signal: controller.signal,
            ...options,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Backend error');
        }
        return res.json();
    } catch (err) {
        if (err.name === 'AbortError') {
            throw new Error('Request timed out. The backend is still processing — you can refresh the page to check results.');
        }
        throw err;
    } finally {
        clearTimeout(timeoutId);
    }
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
     * Uses SSE streaming to receive live progress updates.
     */
    async processDriveFolder(driveFolderUrl, onProgress) {
        const res = await fetch(`${BACKEND_URL}/api/process-drive-folder`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_url: driveFolderUrl }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Backend error');
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let done = false;

        let finalData = { results: [], errors: [] };

        while (!done) {
            const { value, done: readerDone } = await reader.read();
            done = readerDone;
            if (value) {
                const chunkString = decoder.decode(value, { stream: true });
                const lines = chunkString.split('\n');
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            if (onProgress) {
                                onProgress(data);
                            }
                            if (data.type === 'complete') {
                                finalData.results = data.results || [];
                                finalData.errors = data.errors || [];
                            }
                        } catch (e) {
                            console.error("Failed to parse SSE data block", line, e);
                        }
                    }
                }
            }
        }
        return finalData;
    },

    /**
     * Export results to a Google Sheet (optionally a specific tab)
     */
    async exportToSheets(sheetUrl, subsheetName) {
        return api('/export-to-sheets', {
            method: 'POST',
            body: JSON.stringify({
                sheet_url: sheetUrl,
                subsheet_name: subsheetName
            }),
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
     * Create a new evaluation tab in the master sheet
     */
    async createSheetTab(sheetUrl, subsheetName) {
        return api('/sheets/create-tab', {
            method: 'POST',
            body: JSON.stringify({ sheet_url: sheetUrl, subsheet_name: subsheetName })
        });
    },

    /**
     * Generate or update the Super Sheet
     */
    async updateSuperSheet(sheetUrl) {
        return api('/sheets/update-super-sheet', {
            method: 'POST',
            body: JSON.stringify({ sheet_url: sheetUrl })
        });
    }
};
