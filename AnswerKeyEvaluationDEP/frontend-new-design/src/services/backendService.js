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

/**
 * Helper: Upload a file using XMLHttpRequest so we get upload progress events.
 * onUploadProgress(percent) is called with 0–100 as bytes are sent.
 * Returns a Promise that resolves with the parsed JSON response.
 */
const xhrUpload = (url, formData, onUploadProgress) => {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url, true);

        if (onUploadProgress) {
            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    onUploadProgress(Math.round((e.loaded / e.total) * 100));
                }
            };
        }

        xhr.onload = () => {
            let parsed;
            try { parsed = JSON.parse(xhr.responseText); } catch (_) { parsed = {}; }
            if (xhr.status >= 200 && xhr.status < 300) {
                resolve(parsed);
            } else {
                reject(new Error(parsed.detail || `Upload failed (${xhr.status})`));
            }
        };

        xhr.onerror = () => reject(new Error('Network error during upload.'));
        xhr.send(formData);
    });
};

/**
 * Helper: Read an SSE stream from a fetch Response, calling onEvent for each event.
 */
const readSseStream = async (res, onEvent) => {
    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let finalData = { results: [], errors: [] };
    let done = false;

    while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
            const chunk = decoder.decode(value, { stream: true });
            for (const line of chunk.split('\n')) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.substring(6));
                        if (onEvent) onEvent(data);
                        if (data.type === 'complete') {
                            finalData.results = data.results || [];
                            finalData.errors = data.errors || [];
                        }
                    } catch (e) {
                        console.error('Failed to parse SSE data block', line, e);
                    }
                }
            }
        }
    }
    return finalData;
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
     * Upload an answer key file.
     * onUploadProgress(percent) — called with 0–100 during upload.
     */
    async uploadAnswerKey(file, onUploadProgress) {
        const formData = new FormData();
        formData.append('file', file);
        return xhrUpload(`${BACKEND_URL}/api/answer-key/upload`, formData, onUploadProgress);
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
     * Process all student answer sheets in a Drive folder via SSE.
     * onProgress(event) — called for each SSE event.
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

        return readSseStream(res, onProgress);
    },

    /**
     * Process all student answer sheets from a ZIP file upload.
     * Phase 1: upload the ZIP with progress via XHR.
     * Phase 2: stream the SSE response via fetch.
     * onUploadProgress(percent) — called 0–100 while uploading.
     * onProgress(event) — called for each SSE pipeline event.
     */
    async processZipFolder(file, onProgress, onUploadProgress) {
        // Phase 1 – upload the file, track progress
        if (onUploadProgress) onUploadProgress(0);

        const formData = new FormData();
        formData.append('file', file);

        // We need streaming for the response but XHR progress for the upload.
        // Strategy: upload with XHR first to get progress, then use fetch for response stream.
        // Because the backend streams the response, we use fetch directly but
        // intercept the upload via a dummy pre-flight approach by wrapping two phases:
        // Actually, we'll use XMLHttpRequest but also capture responseText progressively.

        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', `${BACKEND_URL}/api/process-zip`, true);

            let lastProcessed = 0;

            if (onUploadProgress) {
                xhr.upload.onprogress = (e) => {
                    if (e.lengthComputable) {
                        onUploadProgress(Math.round((e.loaded / e.total) * 100));
                    }
                };
                xhr.upload.onload = () => onUploadProgress(100);
            }

            // Poll progress incrementally from XHR response text (works for SSE)
            xhr.onreadystatechange = () => {
                if (xhr.readyState >= 3 && xhr.responseText) {
                    const newText = xhr.responseText.substring(lastProcessed);
                    lastProcessed = xhr.responseText.length;
                    for (const line of newText.split('\n')) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.substring(6));
                                if (onProgress) onProgress(data);
                                if (data.type === 'complete') {
                                    resolve({ results: data.results || [], errors: data.errors || [] });
                                }
                                if (data.type === 'error') {
                                    reject(new Error(data.message || 'Pipeline error'));
                                }
                            } catch (_) { /* partial chunk */ }
                        }
                    }
                }
            };

            xhr.onload = () => {
                if (xhr.status >= 400) {
                    try {
                        const err = JSON.parse(xhr.responseText);
                        reject(new Error(err.detail || `Server error ${xhr.status}`));
                    } catch (_) {
                        reject(new Error(`Server error ${xhr.status}`));
                    }
                } else {
                    // ensure resolved even if 'complete' event was missed
                    resolve({ results: [], errors: [] });
                }
            };

            xhr.onerror = () => reject(new Error('Network error during ZIP upload.'));
            xhr.send(formData);
        });
    },

    /**
     * Export results to a Google Sheet (optionally a specific tab)
     */
    async exportToSheets(sheetUrl, subsheetName, results = [], answerKeyData = null) {
        return api('/export-to-sheets', {
            method: 'POST',
            body: JSON.stringify({
                sheet_url: sheetUrl,
                subsheet_name: subsheetName,
                results: results,
                answer_key_data: answerKeyData
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
    },

    /**
     * Clear pipeline results session state
     */
    async clearResults() {
        return api('/results/clear', {
            method: 'DELETE'
        });
    }
};
