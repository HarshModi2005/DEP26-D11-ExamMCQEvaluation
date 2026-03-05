import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Header from '../../components/ui/Header';
import Icon from '../../components/AppIcon';
import { useAuth } from '../../context/AuthContext';
import { evaluationService } from '../../services/evaluationService';
import { resultsService } from '../../services/resultsService';
import { backendService } from '../../services/backendService';

// ── Status Badge ──────────────────────────
const StatusBadge = ({ status }) => {
    const map = {
        draft: 'bg-secondary-100 text-secondary-700',
        active: 'bg-blue-100 text-blue-700',
        grading: 'bg-warning-100 text-warning-700',
        published: 'bg-success-100 text-success-700',
    };
    return <span className={`px-2 py-0.5 rounded-full text-xs font-semibold capitalize ${map[status] || map.draft}`}>{status}</span>;
};

// ── Answer Key Panel ──────────────────────
const AnswerKeyPanel = ({ evaluation, onKeyLoaded }) => {
    const [mode, setMode] = useState('view'); // 'view' | 'manual' | 'upload'
    const [driveUrl, setDriveUrl] = useState(evaluation?.drive_folder_url || '');
    const [loading, setLoading] = useState(false);
    const [err, setErr] = useState('');
    const [manualJson, setManualJson] = useState('{\n  "answers": { "1": "A", "2": "B" },\n  "marks_per_question": 1,\n  "negative_marking": 0\n}');
    const [uploadFile, setUploadFile] = useState(null);
    const hasKey = !!evaluation?.answer_key_data;

    const loadFromDrive = async () => {
        if (!driveUrl) { setErr('Please enter a Drive folder URL.'); return; }
        setLoading(true); setErr('');
        try {
            const res = await backendService.extractAnswerKeyFromDrive(driveUrl);
            await evaluationService.saveAnswerKey(evaluation.id, res.answer_key);
            onKeyLoaded(res.answer_key);
        } catch (e) { setErr(e.message); }
        finally { setLoading(false); }
    };

    const loadManual = async () => {
        setLoading(true); setErr('');
        try {
            const parsed = JSON.parse(manualJson);
            const res = await backendService.setAnswerKeyManual(parsed);
            const key = { ...parsed, total_questions: res.total_questions };
            await evaluationService.saveAnswerKey(evaluation.id, key);
            onKeyLoaded(key);
        } catch (e) { setErr('Invalid JSON or backend error: ' + e.message); }
        finally { setLoading(false); }
    };

    const loadFromUpload = async () => {
        if (!uploadFile) { setErr('Please select a file.'); return; }
        setLoading(true); setErr('');
        try {
            const res = await backendService.uploadAnswerKey(uploadFile);
            await evaluationService.saveAnswerKey(evaluation.id, res.answer_key);
            onKeyLoaded(res.answer_key);
        } catch (e) { setErr(e.message); }
        finally { setLoading(false); }
    };

    return (
        <div className="bg-surface border border-border rounded-xl overflow-hidden">
            <div className="p-4 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Icon name="Key" size={18} className="text-primary" />
                    <h3 className="font-semibold text-text-primary">Answer Key</h3>
                </div>
                {hasKey && (
                    <span className="flex items-center gap-1 text-xs text-success-600 font-medium">
                        <Icon name="CheckCircle" size={14} />Loaded ({evaluation.answer_key_data?.total_questions} Qs)
                    </span>
                )}
            </div>

            {/* Mode selector */}
            <div className="flex border-b border-border">
                {[['view', 'eye', 'From Drive'], ['upload', 'Upload', 'Upload File'], ['manual', 'Code', 'Manual JSON']].map(([m, icon, label]) => (
                    <button key={m} onClick={() => setMode(m)}
                        className={`flex-1 py-2.5 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors ${mode === m ? 'bg-primary-50 text-primary border-b-2 border-primary' : 'text-text-secondary hover:bg-secondary-50'}`}>
                        <Icon name={m === 'view' ? 'FolderOpen' : m === 'upload' ? 'Upload' : 'Code'} size={14} />
                        {label}
                    </button>
                ))}
            </div>

            <div className="p-4 space-y-3">
                {err && <div className="p-3 bg-error-50 border border-error-100 rounded-lg text-sm text-error">{err}</div>}

                {/* From Drive */}
                {mode === 'view' && (
                    <div className="space-y-3">
                        <p className="text-xs text-text-secondary">Extract the answer key file from the evaluation's Google Drive folder. Name the file <code className="bg-secondary-100 px-1 rounded">answer_key</code>.</p>
                        <input type="url" value={driveUrl} onChange={e => setDriveUrl(e.target.value)}
                            className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary-500"
                            placeholder="https://drive.google.com/drive/folders/..." />
                        <button onClick={loadFromDrive} disabled={loading}
                            className="w-full py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary-700 disabled:opacity-50 flex items-center justify-center gap-2">
                            {loading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Icon name="Download" size={14} />}
                            {loading ? 'Extracting...' : 'Extract from Drive'}
                        </button>
                    </div>
                )}

                {/* Upload File */}
                {mode === 'upload' && (
                    <div className="space-y-3">
                        <p className="text-xs text-text-secondary">Upload CSV, XLSX, PDF, or image of the answer key.</p>
                        <label className="block w-full border-2 border-dashed border-border rounded-lg p-4 text-center cursor-pointer hover:border-primary-300 transition-colors">
                            <Icon name="Upload" size={20} className="mx-auto mb-2 text-secondary-400" />
                            <p className="text-sm text-text-secondary">{uploadFile ? uploadFile.name : 'Click to select file'}</p>
                            <input type="file" className="sr-only" accept=".csv,.xlsx,.pdf,.png,.jpg,.jpeg,.txt"
                                onChange={e => setUploadFile(e.target.files[0])} />
                        </label>
                        <button onClick={loadFromUpload} disabled={loading || !uploadFile}
                            className="w-full py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary-700 disabled:opacity-50 flex items-center justify-center gap-2">
                            {loading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Icon name="Upload" size={14} />}
                            {loading ? 'Uploading...' : 'Upload & Parse'}
                        </button>
                    </div>
                )}

                {/* Manual JSON */}
                {mode === 'manual' && (
                    <div className="space-y-3">
                        <p className="text-xs text-text-secondary">Enter the answer key as JSON.</p>
                        <textarea value={manualJson} onChange={e => setManualJson(e.target.value)} rows={8}
                            className="w-full px-3 py-2 border border-border rounded-lg text-xs font-mono focus:ring-2 focus:ring-primary-500 resize-none" />
                        <button onClick={loadManual} disabled={loading}
                            className="w-full py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary-700 disabled:opacity-50 flex items-center justify-center gap-2">
                            {loading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Icon name="Save" size={14} />}
                            {loading ? 'Saving...' : 'Set Answer Key'}
                        </button>
                    </div>
                )}

                {/* Current Key Preview */}
                {hasKey && evaluation.answer_key_data?.answers && (
                    <div className="mt-2 p-3 bg-success-50 border border-success-100 rounded-lg">
                        <p className="text-xs font-semibold text-success-700 mb-2 flex items-center gap-1"><Icon name="CheckCircle" size={12} />Loaded Answer Key</p>
                        <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                            {Object.entries(evaluation.answer_key_data.answers).slice(0, 20).map(([q, a]) => (
                                <span key={q} className="px-1.5 py-0.5 bg-white border border-success-200 rounded text-xs font-mono">
                                    Q{q}:{typeof a === 'object' ? a.correct_option : a}
                                </span>
                            ))}
                            {Object.keys(evaluation.answer_key_data.answers).length > 20 && (
                                <span className="text-xs text-success-600">+{Object.keys(evaluation.answer_key_data.answers).length - 20} more</span>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

// ── Results Table ─────────────────────────
const ResultsTable = ({ results, onCommentUpdate }) => {
    const [editingId, setEditingId] = useState(null);
    const [commentDraft, setCommentDraft] = useState('');

    const handleEditComment = (r) => {
        setEditingId(r.id);
        setCommentDraft(r.comments || '');
    };

    const handleSaveComment = async (id) => {
        await resultsService.updateComment(id, commentDraft);
        onCommentUpdate(id, commentDraft);
        setEditingId(null);
    };

    if (results.length === 0) {
        return (
            <div className="text-center py-12 text-text-secondary">
                <Icon name="FileSearch" size={36} className="mx-auto mb-3 text-secondary-300" />
                <p className="text-sm">No results yet. Run the OCR pipeline to grade answer sheets.</p>
            </div>
        );
    }

    return (
        <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-border text-sm">
                <thead className="bg-secondary-50">
                    <tr>
                        <th className="px-4 py-3 text-left font-medium text-text-secondary uppercase text-xs tracking-wider">Roll No</th>
                        <th className="px-4 py-3 text-left font-medium text-text-secondary uppercase text-xs tracking-wider">Name</th>
                        <th className="px-4 py-3 text-center font-medium text-text-secondary uppercase text-xs tracking-wider">Score</th>
                        <th className="px-4 py-3 text-center font-medium text-text-secondary uppercase text-xs tracking-wider">✓ Correct</th>
                        <th className="px-4 py-3 text-center font-medium text-text-secondary uppercase text-xs tracking-wider">✗ Wrong</th>
                        <th className="px-4 py-3 text-center font-medium text-text-secondary uppercase text-xs tracking-wider">— Skip</th>
                        <th className="px-4 py-3 text-left font-medium text-text-secondary uppercase text-xs tracking-wider">Comments</th>
                    </tr>
                </thead>
                <tbody className="bg-surface divide-y divide-border">
                    {results.map(r => {
                        const student = r.students || {};
                        const pct = r.max_score > 0 ? Math.round((r.total_score / r.max_score) * 100) : 0;
                        const scoreColor = pct >= 75 ? 'text-success-600' : pct >= 50 ? 'text-warning-600' : 'text-error-600';
                        return (
                            <tr key={r.id} className="hover:bg-secondary-50 transition-colors">
                                <td className="px-4 py-3 font-mono text-text-secondary">{student.roll_number || '—'}</td>
                                <td className="px-4 py-3 font-medium text-text-primary">{student.name || '—'}</td>
                                <td className="px-4 py-3 text-center">
                                    <span className={`font-bold ${scoreColor}`}>{r.total_score}</span>
                                    <span className="text-text-secondary">/{r.max_score}</span>
                                    <span className="ml-1 text-xs text-text-secondary">({pct}%)</span>
                                </td>
                                <td className="px-4 py-3 text-center text-success-600 font-medium">{r.correct_count}</td>
                                <td className="px-4 py-3 text-center text-error-600 font-medium">{r.incorrect_count}</td>
                                <td className="px-4 py-3 text-center text-secondary-400">{r.unattempted_count}</td>
                                <td className="px-4 py-3">
                                    {editingId === r.id ? (
                                        <div className="flex items-center gap-2">
                                            <input type="text" value={commentDraft} onChange={e => setCommentDraft(e.target.value)}
                                                className="flex-1 px-2 py-1 border border-primary rounded text-xs focus:ring-1 focus:ring-primary" />
                                            <button onClick={() => handleSaveComment(r.id)} className="text-success-600 hover:text-success-700">
                                                <Icon name="Check" size={14} />
                                            </button>
                                            <button onClick={() => setEditingId(null)} className="text-error hover:text-error-700">
                                                <Icon name="X" size={14} />
                                            </button>
                                        </div>
                                    ) : (
                                        <button onClick={() => handleEditComment(r)}
                                            className="text-left text-xs text-text-secondary hover:text-primary transition-colors flex items-center gap-1 group">
                                            <span className="truncate max-w-[120px]">{r.comments || 'Add comment...'}</span>
                                            <Icon name="Pencil" size={12} className="opacity-0 group-hover:opacity-100 flex-shrink-0" />
                                        </button>
                                    )}
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
};

// ── Main EvaluatePage ─────────────────────
const EvaluatePage = () => {
    const { evaluationId } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();

    const [evaluation, setEvaluation] = useState(null);
    const [results, setResults] = useState([]);
    const [pageLoading, setPageLoading] = useState(true);
    const [pipelineLoading, setPipelineLoading] = useState(false);
    const [exportLoading, setExportLoading] = useState(false);
    const [pipelineLog, setPipelineLog] = useState([]);
    const [pipelineProgress, setPipelineProgress] = useState(0);
    const [error, setError] = useState('');
    const [exportMsg, setExportMsg] = useState('');
    const [driveFolderUrl, setDriveFolderUrl] = useState('');

    const fetchData = useCallback(async () => {
        setPageLoading(true);
        try {
            const ev = await evaluationService.getEvaluationById(evaluationId);
            setEvaluation(ev);
            setDriveFolderUrl(ev.drive_folder_url || '');
            const res = await resultsService.getResultsByEvaluation(evaluationId);
            setResults(res || []);
        } catch (err) {
            setError('Failed to load evaluation: ' + err.message);
        } finally {
            setPageLoading(false);
        }
    }, [evaluationId]);

    useEffect(() => { fetchData(); }, [fetchData]);

    const handleKeyLoaded = (keyData) => {
        setEvaluation(prev => ({ ...prev, answer_key_data: keyData }));
        setPipelineLog(prev => [...prev, `✅ Answer key loaded — ${keyData.total_questions || '?'} questions`]);
    };

    const handleRunPipeline = async () => {
        const url = driveFolderUrl || evaluation?.drive_folder_url;
        if (!url) { setError('Please enter the Google Drive folder URL containing student answer sheets.'); return; }
        if (!evaluation?.answer_key_data) { setError('Please load an answer key first before running the pipeline.'); return; }

        setPipelineLoading(true);
        setError('');
        setPipelineProgress(10);
        setPipelineLog(prev => [...prev, '🚀 Starting OCR pipeline...', `📁 Drive folder: ${url}`]);

        try {
            // Save drive folder URL if changed
            if (url !== evaluation.drive_folder_url) {
                await evaluationService.updateDriveFolderUrl(evaluationId, url);
                setEvaluation(prev => ({ ...prev, drive_folder_url: url }));
            }

            setPipelineProgress(30);
            setPipelineLog(prev => [...prev, '🔍 Scanning Drive folder...']);

            const pipelineResult = await backendService.processDriveFolder(url);
            setPipelineProgress(80);

            const processedResults = pipelineResult.results || [];
            setPipelineLog(prev => [
                ...prev,
                `✅ Processed ${processedResults.length} student sheets`,
                ...(pipelineResult.errors?.length > 0
                    ? [`⚠️ ${pipelineResult.errors.length} errors: ${pipelineResult.errors.map(e => e.file).join(', ')}`]
                    : []),
            ]);

            if (processedResults.length > 0) {
                setPipelineLog(prev => [...prev, '💾 Saving results to database...']);
                await resultsService.saveResults(evaluationId, evaluation.course_id, processedResults, user?.id);
                setPipelineProgress(90);

                // Update eval status to grading
                await evaluationService.updateStatus(evaluationId, 'grading');
                setEvaluation(prev => ({ ...prev, status: 'grading' }));

                // Refresh results
                const fresh = await resultsService.getResultsByEvaluation(evaluationId);
                setResults(fresh || []);
                setPipelineProgress(100);
                setPipelineLog(prev => [...prev, `🎉 Done! ${fresh.length} results saved.`]);
            } else {
                setPipelineLog(prev => [...prev, '⚠️ No results returned. Check the Drive folder.']);
            }
        } catch (err) {
            setError('Pipeline failed: ' + err.message);
            setPipelineLog(prev => [...prev, `❌ Error: ${err.message}`]);
        } finally {
            setPipelineLoading(false);
        }
    };

    const handleExportToSheet = async () => {
        const course = evaluation?.courses;
        if (!course?.master_sheet_url) {
            setExportMsg('❌ No master Google Sheet URL set for this course. Set it in Course Settings.');
            return;
        }
        setExportLoading(true);
        setExportMsg('');
        try {
            const res = await backendService.exportToSheets(course.master_sheet_url, evaluation.subsheet_name);
            await evaluationService.updateStatus(evaluationId, 'published');
            setEvaluation(prev => ({ ...prev, status: 'published' }));
            setExportMsg(`✅ Exported to Google Sheet. Updated: ${res.updated}, Not found: ${res.not_found?.length || 0}`);
        } catch (err) {
            setExportMsg('❌ Export failed: ' + err.message);
        } finally {
            setExportLoading(false);
        }
    };

    const handleCommentUpdate = (id, comment) => {
        setResults(prev => prev.map(r => r.id === id ? { ...r, comments: comment } : r));
    };

    if (pageLoading) {
        return (
            <div className="min-h-screen bg-background">
                <Header />
                <main className="pt-16 flex items-center justify-center min-h-[80vh]">
                    <div className="flex flex-col items-center gap-4">
                        <div className="w-10 h-10 border-4 border-primary border-t-transparent rounded-full animate-spin" />
                        <p className="text-text-secondary">Loading evaluation...</p>
                    </div>
                </main>
            </div>
        );
    }

    const course = evaluation?.courses;

    return (
        <div className="min-h-screen bg-background">
            <Header />

            <main className="pt-16 transition-all duration-300">
                <div className="p-6 max-w-7xl mx-auto space-y-6">

                    {/* Breadcrumb */}
                    <div className="flex items-center text-sm text-text-secondary flex-wrap gap-1">
                        <button onClick={() => navigate('/faculty-dashboard')} className="hover:text-primary transition-colors flex items-center gap-1">
                            <Icon name="Home" size={13} />My Courses
                        </button>
                        <span>/</span>
                        {course && (
                            <>
                                <button onClick={() => navigate(`/course/${course.id}`)} className="hover:text-primary transition-colors">
                                    {course.code}
                                </button>
                                <span>/</span>
                            </>
                        )}
                        <span className="font-medium text-text-primary">{evaluation?.name}</span>
                    </div>

                    {/* Page Header */}
                    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                        <div>
                            <div className="flex items-center gap-3 mb-1">
                                <h1 className="text-2xl font-bold text-text-primary">{evaluation?.name}</h1>
                                {evaluation?.status && <StatusBadge status={evaluation.status} />}
                            </div>
                            <p className="text-text-secondary text-sm">
                                {course?.title} • {evaluation?.total_marks > 0 ? `${evaluation.total_marks} marks` : 'Marks not set'}
                                {evaluation?.negative_marking > 0 ? ` • −${evaluation.negative_marking} negative` : ''}
                                {evaluation?.subsheet_name ? ` • Sheet tab: "${evaluation.subsheet_name}"` : ''}
                            </p>
                        </div>
                        <div className="flex items-center gap-3">
                            {results.length > 0 && (
                                <button onClick={handleExportToSheet} disabled={exportLoading}
                                    className="px-4 py-2 border border-success-300 bg-success-50 text-success-700 rounded-lg hover:bg-success-100 transition-colors text-sm flex items-center gap-2 disabled:opacity-50">
                                    {exportLoading
                                        ? <div className="w-4 h-4 border-2 border-success-500 border-t-transparent rounded-full animate-spin" />
                                        : <Icon name="FileSpreadsheet" size={16} />}
                                    Export to Google Sheet
                                </button>
                            )}
                        </div>
                    </div>

                    {error && (
                        <div className="p-4 bg-error-50 border border-error-200 rounded-xl flex items-start gap-3">
                            <Icon name="AlertCircle" size={18} className="text-error flex-shrink-0 mt-0.5" />
                            <p className="text-sm text-error">{error}</p>
                            <button onClick={() => setError('')} className="ml-auto"><Icon name="X" size={16} className="text-error" /></button>
                        </div>
                    )}

                    {exportMsg && (
                        <div className={`p-4 rounded-xl border text-sm ${exportMsg.startsWith('✅') ? 'bg-success-50 border-success-200 text-success-700' : 'bg-error-50 border-error-200 text-error'}`}>
                            {exportMsg}
                        </div>
                    )}

                    {/* Main two-column layout */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

                        {/* ── LEFT PANEL ── */}
                        <div className="space-y-6">

                            {/* Answer Key */}
                            <AnswerKeyPanel evaluation={evaluation} onKeyLoaded={handleKeyLoaded} />

                            {/* Run Pipeline */}
                            <div className="bg-surface border border-border rounded-xl overflow-hidden">
                                <div className="p-4 border-b border-border flex items-center gap-2">
                                    <Icon name="Cpu" size={18} className="text-primary" />
                                    <h3 className="font-semibold text-text-primary">OCR Pipeline</h3>
                                </div>
                                <div className="p-4 space-y-4">
                                    <div>
                                        <label className="block text-xs font-medium text-text-secondary mb-1">
                                            Google Drive Folder (Student Answer Sheets)
                                        </label>
                                        <input type="url" value={driveFolderUrl} onChange={e => setDriveFolderUrl(e.target.value)}
                                            className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary-500"
                                            placeholder="https://drive.google.com/drive/folders/..." />
                                    </div>

                                    {/* Checklist */}
                                    <div className="space-y-2">
                                        <div className={`flex items-center gap-2 text-sm ${evaluation?.answer_key_data ? 'text-success-600' : 'text-secondary-400'}`}>
                                            <Icon name={evaluation?.answer_key_data ? 'CheckCircle' : 'Circle'} size={16} />
                                            Answer key loaded
                                        </div>
                                        <div className={`flex items-center gap-2 text-sm ${driveFolderUrl ? 'text-success-600' : 'text-secondary-400'}`}>
                                            <Icon name={driveFolderUrl ? 'CheckCircle' : 'Circle'} size={16} />
                                            Drive folder URL set
                                        </div>
                                    </div>

                                    {/* Progress bar */}
                                    {pipelineLoading && (
                                        <div>
                                            <div className="flex justify-between text-xs text-text-secondary mb-1">
                                                <span>Processing...</span>
                                                <span>{pipelineProgress}%</span>
                                            </div>
                                            <div className="w-full bg-secondary-100 rounded-full h-2">
                                                <div className="bg-primary h-2 rounded-full transition-all duration-500"
                                                    style={{ width: `${pipelineProgress}%` }} />
                                            </div>
                                        </div>
                                    )}

                                    <button onClick={handleRunPipeline} disabled={pipelineLoading}
                                        className="w-full py-3 bg-primary text-white rounded-lg font-semibold hover:bg-primary-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
                                        {pipelineLoading
                                            ? <><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />Running OCR...</>
                                            : <><Icon name="Play" size={16} />Run OCR Pipeline</>}
                                    </button>
                                </div>

                                {/* Pipeline Log */}
                                {pipelineLog.length > 0 && (
                                    <div className="border-t border-border p-4">
                                        <p className="text-xs font-medium text-text-secondary mb-2 flex items-center gap-1">
                                            <Icon name="Terminal" size={12} />Pipeline Log
                                        </p>
                                        <div className="bg-secondary-900 rounded-lg p-3 max-h-36 overflow-y-auto space-y-1">
                                            {pipelineLog.map((log, i) => (
                                                <p key={i} className="text-xs font-mono text-secondary-200">{log}</p>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Stats card if results exist */}
                            {results.length > 0 && (
                                <div className="bg-surface border border-border rounded-xl p-4 space-y-3">
                                    <h3 className="font-semibold text-text-primary text-sm flex items-center gap-2">
                                        <Icon name="BarChart2" size={16} className="text-primary" />Quick Summary
                                    </h3>
                                    {(() => {
                                        const scores = results.map(r => r.total_score);
                                        const avg = scores.length ? (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1) : '—';
                                        const max = scores.length ? Math.max(...scores) : '—';
                                        const min = scores.length ? Math.min(...scores) : '—';
                                        return (
                                            <div className="grid grid-cols-3 gap-2 text-center">
                                                {[['Average', avg], ['Highest', max], ['Lowest', min]].map(([label, val]) => (
                                                    <div key={label} className="bg-secondary-50 rounded-lg p-2">
                                                        <p className="text-lg font-bold text-text-primary">{val}</p>
                                                        <p className="text-xs text-text-secondary">{label}</p>
                                                    </div>
                                                ))}
                                            </div>
                                        );
                                    })()}
                                </div>
                            )}
                        </div>

                        {/* ── RIGHT PANEL ── */}
                        <div className="lg:col-span-2">
                            <div className="bg-surface border border-border rounded-xl overflow-hidden">
                                <div className="p-4 border-b border-border flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <Icon name="ClipboardList" size={18} className="text-primary" />
                                        <h3 className="font-semibold text-text-primary">
                                            Grading Results
                                            {results.length > 0 && (
                                                <span className="ml-2 text-sm font-normal text-text-secondary">({results.length} students)</span>
                                            )}
                                        </h3>
                                    </div>
                                    {results.length > 0 && (
                                        <button onClick={fetchData} className="text-xs text-primary hover:underline flex items-center gap-1">
                                            <Icon name="RefreshCw" size={12} />Refresh
                                        </button>
                                    )}
                                </div>
                                <ResultsTable results={results} onCommentUpdate={handleCommentUpdate} />
                            </div>

                            {/* Duties Panel */}
                            {evaluation?.evaluation_duties?.length > 0 && (
                                <div className="mt-4 bg-surface border border-border rounded-xl p-4">
                                    <h3 className="font-semibold text-text-primary text-sm mb-3 flex items-center gap-2">
                                        <Icon name="Users" size={16} className="text-primary" />Assigned Graders
                                    </h3>
                                    <div className="flex flex-wrap gap-2">
                                        {evaluation.evaluation_duties.map(d => (
                                            <div key={d.assignee_id} className="flex items-center gap-2 px-3 py-1.5 bg-primary-50 border border-primary-100 rounded-full">
                                                <div className="w-5 h-5 rounded-full bg-primary-200 flex items-center justify-center text-primary-800 text-xs font-bold">
                                                    {d.profiles?.name?.[0] || '?'}
                                                </div>
                                                <span className="text-sm text-primary-800 font-medium">{d.profiles?.name}</span>
                                                <span className="text-xs text-primary-400 capitalize">({d.profiles?.role})</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </main>
        </div>
    );
};

export default EvaluatePage;
