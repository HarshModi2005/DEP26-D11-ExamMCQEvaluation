"use client"
import { useState, useEffect } from 'react';
import api from '@/lib/api';
import { RefreshCw, FileText, CheckCircle, BarChart, Sheet, Upload, AlertCircle, LogOut } from 'lucide-react';
import { useRouter } from 'next/navigation';


export default function AdminDashboard() {
    const [files, setFiles] = useState<any[]>([]);
    const [results, setResults] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const [folderId, setFolderId] = useState('');
    const [isLogoutModalOpen, setIsLogoutModalOpen] = useState(false);
    const router = useRouter();

    const handleLogout = async () => {
        try {
            await api.post('/auth/logout');
        } catch (error) {
            console.error("Logout failed:", error);
        } finally {
            // Always clear localStorage and redirect
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            router.push('/login');
        }
    };


    // Google Sheets state
    const [sheetsUrl, setSheetsUrl] = useState('');
    const [sheetsLoading, setSheetsLoading] = useState(false);
    const [sheetsResult, setSheetsResult] = useState<any>(null);

    const fetchResults = async () => {
        try {
            const res = await api.get('/results');
            // Handle both new API format { results: [...] } and legacy format [...]
            if (res.data && res.data.results && Array.isArray(res.data.results)) {
                setResults(res.data.results);
            } else if (Array.isArray(res.data)) {
                setResults(res.data);
            } else {
                setResults([]);
            }
        } catch (error) {
            console.error("Failed to fetch results", error);
            setResults([]);
        }
    };

    const handleSync = async () => {
        if (!folderId) {
            alert("Please enter a Folder ID");
            return;
        }
        setLoading(true);
        try {
            const res = await api.post(`/sync-drive?folder_id=${folderId}`);
            setFiles(res.data.files || []);
        } catch (error) {
            console.error(error);
            alert("Sync failed. Check console and backend logs.");
        }
        setLoading(false);
    };

    const [processingAll, setProcessingAll] = useState(false);

    const handleProcess = async (fileId: string, fileName: string, silent = false) => {
        try {
            await api.post(`/process-file?file_id=${fileId}&file_name=${fileName}`);
            if (!silent) alert("Processing started in background");
        } catch (error) {
            console.error(error);
            if (!silent) alert("Processing trigger failed");
        }
    };

    const handleEvaluateAll = async () => {
        if (files.length === 0) {
            alert("No files to evaluate. Sync first.");
            return;
        }

        if (!confirm(`Are you sure you want to evaluate all ${files.length} files? This might take a moment.`)) return;

        setProcessingAll(true);
        let count = 0;

        for (const file of files) {
            await handleProcess(file.id, file.name, true);
            count++;
        }

        alert(`Started evaluation for ${count} files. Check Results section shortly.`);
        setProcessingAll(false);
    };

    const handleExportToSheets = async () => {
        if (!sheetsUrl) {
            alert("Please enter a Google Sheets URL");
            return;
        }
        if (results.length === 0) {
            alert("No results to export. Process some answer sheets first.");
            return;
        }

        setSheetsLoading(true);
        setSheetsResult(null);
        try {
            const res = await api.post('/export-to-sheets', { sheet_url: sheetsUrl });
            setSheetsResult(res.data);
            alert(`✅ Exported marks to Google Sheet! Updated ${res.data.updated || 0} rows.`);
        } catch (error: any) {
            console.error(error);
            const detail = error?.response?.data?.detail || "Export failed. Check console and backend logs.";
            setSheetsResult({ error: detail });
            alert(`❌ Export failed: ${detail}`);
        }
        setSheetsLoading(false);
    };

    const handlePreviewSheet = async () => {
        if (!sheetsUrl) {
            alert("Please enter a Google Sheets URL");
            return;
        }
        setSheetsLoading(true);
        try {
            const res = await api.get(`/sheets/preview?sheet_url=${encodeURIComponent(sheetsUrl)}`);
            setSheetsResult(res.data);
        } catch (error: any) {
            console.error(error);
            const detail = error?.response?.data?.detail || "Preview failed.";
            setSheetsResult({ error: detail });
        }
        setSheetsLoading(false);
    };

    useEffect(() => {
        fetchResults();
        const interval = setInterval(fetchResults, 5000);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="min-h-screen bg-gray-50 p-8 text-gray-800">
            <div className="max-w-6xl mx-auto">
                <header className="flex justify-between items-start mb-10">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">Instructor Dashboard</h1>
                        <p className="text-gray-500">Automated Answer Sheet Evaluation System</p>
                    </div>
                    <button
                        onClick={() => setIsLogoutModalOpen(true)}
                        className="flex items-center gap-2 bg-white border border-gray-200 text-gray-600 px-4 py-2 rounded-xl hover:bg-red-50 hover:text-red-600 hover:border-red-100 transition-all shadow-sm font-medium text-sm group"
                    >
                        <LogOut className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
                        Logout
                    </button>
                </header>

                {/* Logout Confirmation Modal */}
                {isLogoutModalOpen && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-300">
                        <div className="bg-white rounded-3xl shadow-2xl w-full max-w-sm overflow-hidden animate-in zoom-in-95 duration-300">
                            <div className="p-8 text-center">
                                <div className="w-16 h-16 bg-red-50 rounded-2xl flex items-center justify-center mx-auto mb-6">
                                    <LogOut className="w-8 h-8 text-red-500" />
                                </div>
                                <h3 className="text-2xl font-bold text-gray-900 mb-2">Confirm Logout</h3>
                                <p className="text-gray-500 mb-8 text-sm">
                                    Are you sure you want to log out of the Instructor Dashboard?
                                </p>
                                <div className="grid grid-cols-2 gap-4">
                                    <button
                                        onClick={() => setIsLogoutModalOpen(false)}
                                        className="py-3 px-6 rounded-xl border border-gray-200 text-gray-600 font-bold hover:bg-gray-50 transition-all active:scale-95 text-sm"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        onClick={handleLogout}
                                        className="py-3 px-6 rounded-xl bg-red-600 text-white font-bold hover:bg-red-700 shadow-lg shadow-red-200 transition-all active:scale-95 text-sm"
                                    >
                                        Logout
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* Sync Section */}
                <div className="bg-white p-6 rounded-xl shadow-sm mb-8 border border-gray-100">
                    <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                        <RefreshCw className="w-5 h-5 text-blue-500" />
                        Import Submissions
                    </h2>
                    <div className="flex gap-4">
                        <input
                            type="text"
                            placeholder="Enter Google Drive Folder ID or URL"
                            className="flex-1 border border-gray-300 p-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                            value={folderId}
                            onChange={(e) => setFolderId(e.target.value)}
                        />
                        <button
                            onClick={handleSync}
                            className="flex items-center gap-2 bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 transition disabled:opacity-50"
                            disabled={loading}
                        >
                            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                            {loading ? 'Syncing...' : 'Sync Drive'}
                        </button>
                    </div>
                </div>

                {/* Google Sheets Export Section */}
                <div className="bg-white p-6 rounded-xl shadow-sm mb-8 border border-gray-100">
                    <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                        <Sheet className="w-5 h-5 text-green-600" />
                        Export Marks to Google Sheet
                    </h2>
                    <p className="text-sm text-gray-500 mb-3">
                        Enter the Google Sheets URL containing your student list. The sheet should have columns for Entry Number, Name, and Marks.
                    </p>
                    <div className="flex gap-4 mb-3">
                        <input
                            type="text"
                            placeholder="https://docs.google.com/spreadsheets/d/..."
                            className="flex-1 border border-gray-300 p-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-green-500"
                            value={sheetsUrl}
                            onChange={(e) => setSheetsUrl(e.target.value)}
                        />
                        <button
                            onClick={handlePreviewSheet}
                            className="flex items-center gap-2 bg-gray-100 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-200 transition disabled:opacity-50 text-sm"
                            disabled={sheetsLoading}
                        >
                            Preview
                        </button>
                        <button
                            onClick={handleExportToSheets}
                            className="flex items-center gap-2 bg-green-600 text-white px-6 py-2 rounded-lg hover:bg-green-700 transition disabled:opacity-50"
                            disabled={sheetsLoading || results.length === 0}
                        >
                            <Upload className="w-4 h-4" />
                            {sheetsLoading ? 'Exporting...' : 'Export Marks'}
                        </button>
                    </div>

                    {/* Sheets Result Feedback */}
                    {sheetsResult && (
                        <div className={`mt-3 p-4 rounded-lg text-sm ${sheetsResult.error ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-green-50 text-green-700 border border-green-200'}`}>
                            {sheetsResult.error ? (
                                <div className="flex items-start gap-2">
                                    <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                                    <span>{sheetsResult.error}</span>
                                </div>
                            ) : sheetsResult.updated !== undefined ? (
                                <div>
                                    <p className="font-semibold">✅ Export Complete</p>
                                    <p>Updated: {sheetsResult.updated} rows</p>
                                    {sheetsResult.not_found_in_sheet?.length > 0 && (
                                        <p className="text-yellow-700">⚠️ Not found in sheet: {sheetsResult.not_found_in_sheet.join(', ')}</p>
                                    )}
                                    {sheetsResult.not_found_in_results?.length > 0 && (
                                        <p className="text-yellow-700">⚠️ No results for: {sheetsResult.not_found_in_results.join(', ')}</p>
                                    )}
                                    {sheetsResult.name_mismatches?.length > 0 && (
                                        <p className="text-orange-700">⚠️ Name mismatches: {sheetsResult.name_mismatches.length}</p>
                                    )}
                                </div>
                            ) : sheetsResult.students ? (
                                <div>
                                    <p className="font-semibold mb-2">📋 Sheet Preview — {sheetsResult.student_count} students</p>
                                    <p className="text-xs text-gray-500 mb-2">
                                        Detected columns: {Object.entries(sheetsResult.columns_detected || {}).map(([key, val]: [string, any]) => `${key} → "${val.header}" (col ${val.letter})`).join(' | ')}
                                    </p>
                                    <div className="max-h-40 overflow-y-auto">
                                        <table className="w-full text-xs">
                                            <thead>
                                                <tr className="border-b">
                                                    <th className="text-left py-1 px-2">Entry Number</th>
                                                    <th className="text-left py-1 px-2">Name</th>
                                                    <th className="text-left py-1 px-2">Marks</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {sheetsResult.students.map((s: any, i: number) => (
                                                    <tr key={i} className="border-b border-gray-100">
                                                        <td className="py-1 px-2">{s.entry_number}</td>
                                                        <td className="py-1 px-2">{s.name}</td>
                                                        <td className="py-1 px-2">{s.marks ?? '—'}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            ) : (
                                <pre className="overflow-x-auto">{JSON.stringify(sheetsResult, null, 2)}</pre>
                            )}
                        </div>
                    )}
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    {/* Files List */}
                    <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-xl font-semibold flex items-center gap-2 text-gray-800">
                                <FileText className="w-5 h-5 text-gray-500" />
                                Available Files
                            </h2>
                            {files.length > 0 && (
                                <button
                                    onClick={handleEvaluateAll}
                                    disabled={processingAll}
                                    className="text-sm bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 transition disabled:opacity-50 flex items-center gap-2"
                                >
                                    {processingAll ? 'Starting...' : 'Evaluate All'}
                                    <BarChart className="w-4 h-4" />
                                </button>
                            )}
                        </div>
                        <div className="space-y-3 max-h-[500px] overflow-y-auto">
                            {files.length === 0 && (
                                <div className="text-center py-10 text-gray-400">
                                    No files loaded. Sync a folder to get started.
                                </div>
                            )}
                            {files.map(file => (
                                <div key={file.id} className="flex justify-between items-center p-3 hover:bg-gray-50 rounded-lg border border-gray-100">
                                    <div className="flex items-center gap-3 overflow-hidden">
                                        <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center text-blue-600 text-xs">IMG</div>
                                        <span className="truncate font-medium text-sm text-gray-700">{file.name}</span>
                                    </div>
                                    <button
                                        onClick={() => handleProcess(file.id, file.name)}
                                        className="text-xs font-medium bg-green-50 text-green-700 px-3 py-1.5 rounded-full hover:bg-green-100 transition"
                                    >
                                        Process
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Results List */}
                    <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-100">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2 text-gray-800">
                            <CheckCircle className="w-5 h-5 text-green-500" />
                            Evaluation Results
                        </h2>
                        <div className="space-y-4 max-h-[500px] overflow-y-auto">
                            {results.length === 0 && (
                                <div className="text-center py-10 text-gray-400">
                                    No processing results yet.
                                </div>
                            )}
                            {results.map((res, idx) => (
                                <div key={idx} className="p-4 border border-gray-100 rounded-lg hover:shadow-md transition bg-white">
                                    <div className="flex justify-between items-start mb-2">
                                        <span className="font-bold text-gray-900">
                                            {res.submission_id
                                                ? `Submission ${res.submission_id.substring(0, 6)}...`
                                                : res.entry_number
                                                    ? `${res.entry_number} — ${res.name || ''}`
                                                    : `Result ${idx + 1}`
                                            }
                                        </span>
                                        <span className="bg-blue-100 text-blue-800 text-xs font-semibold px-2.5 py-0.5 rounded">
                                            Score: {res.score ?? res.total_score ?? '—'}{res.max_score ? `/${res.max_score}` : ''}
                                        </span>
                                    </div>
                                    {res.feedback && <p className="text-sm text-gray-600 mt-1">{res.feedback}</p>}
                                    <p className="text-xs text-gray-500 mt-1">
                                        {res.correct_count} correct · {res.incorrect_count} incorrect · {res.unattempted_count} unattempted
                                    </p>
                                    {res.details && (
                                        <details className="mt-2 text-xs text-gray-500 cursor-pointer">
                                            <summary>View Details</summary>
                                            <pre className="mt-2 bg-gray-50 p-2 rounded overflow-x-auto">
                                                {typeof res.details === 'string'
                                                    ? JSON.stringify(JSON.parse(res.details || '{}'), null, 2)
                                                    : JSON.stringify(res.details, null, 2)
                                                }
                                            </pre>
                                        </details>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
