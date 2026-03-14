import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Header from '../../components/ui/Header';
import Icon from '../../components/AppIcon';
import { useAuth } from '../../context/AuthContext';
import { evaluationService } from '../../services/evaluationService';
import { resultsService } from '../../services/resultsService';
import { backendService } from '../../services/backendService';
import { supabase } from '../../services/supabaseClient';

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
    const [uploadProgress, setUploadProgress] = useState(0);
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
        setLoading(true); setErr(''); setUploadProgress(0);
        try {
            const res = await backendService.uploadAnswerKey(uploadFile, (pct) => setUploadProgress(pct));
            await evaluationService.saveAnswerKey(evaluation.id, res.answer_key);
            onKeyLoaded(res.answer_key);
        } catch (e) { setErr(e.message); }
        finally { setLoading(false); setUploadProgress(0); }
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
                {err && <div className="p-3 bg-error-50 border border-error-100 rounded-lg text-sm text-error whitespace-pre-wrap font-mono relative"><Icon name="AlertCircle" size={16} className="absolute top-3 left-3" /> <div className="ml-6">{err}</div></div>}

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
                        <div className="bg-primary-50 p-3 rounded-lg border border-primary-100 text-xs text-primary-800 space-y-1.5">
                            <p className="font-semibold flex items-center gap-1.5"><Icon name="Info" size={14} /> Expected Format Columns:</p>
                            <ul className="list-disc pl-5 space-y-0.5">
                                <li><strong>Question</strong>: e.g. 1, 2, 3</li>
                                <li><strong>Type</strong>: <code className="bg-white px-1 rounded">SMCQ</code> (Single), <code className="bg-white px-1 rounded">MMCQ</code> (Multi), or <code className="bg-white px-1 rounded">NCQ</code> (Numerical)</li>
                                <li><strong>Positive Marks</strong>: e.g. 3.0</li>
                                <li><strong>Negative Marks</strong>: e.g. 1.0</li>
                                <li><strong>Correct Answer</strong>: Letter(s) or number based on Type</li>
                            </ul>
                        </div>
                        <label className={`block w-full border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-all duration-200 ${uploadFile ? 'border-success-500 bg-success-50' : 'border-border hover:border-primary-300 bg-white'}`}>
                            {uploadFile ? (
                                <>
                                    <Icon name="CheckCircle" size={20} className="mx-auto mb-2 text-success-500" />
                                    <p className="text-sm font-semibold text-success-700">{uploadFile.name}</p>
                                    <p className="text-xs text-success-600 mt-0.5">{(uploadFile.size / 1024).toFixed(0)} KB · Ready to parse</p>
                                </>
                            ) : (
                                <>
                                    <Icon name="Upload" size={20} className="mx-auto mb-2 text-secondary-400" />
                                    <p className="text-sm text-text-secondary">Click to select file</p>
                                </>
                            )}
                            <input type="file" className="sr-only" accept=".csv,.xlsx,.pdf,.png,.jpg,.jpeg,.txt"
                                onChange={e => setUploadFile(e.target.files[0])} />
                        </label>
                        <button onClick={loadFromUpload} disabled={loading || !uploadFile}
                            className="w-full py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary-700 disabled:opacity-50 flex items-center justify-center gap-2">
                            {loading
                                ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                : <Icon name="Upload" size={14} />}
                            {loading
                                ? (uploadProgress > 0 && uploadProgress < 100 ? `Uploading... (${uploadProgress}%)` : 'Processing...')
                                : 'Upload & Parse'}
                        </button>
                        {loading && (
                            <div>
                                <div className="w-full bg-secondary-100 rounded-full h-1.5 mt-1">
                                    <div
                                        className="bg-primary h-1.5 rounded-full transition-all duration-300"
                                        style={{ width: uploadProgress > 0 ? `${uploadProgress}%` : '30%' }}
                                    />
                                </div>
                                <p className="text-xs text-text-secondary mt-1 text-center">
                                    {uploadProgress > 0 && uploadProgress < 100
                                        ? `Uploading file to server... ${uploadProgress}%`
                                        : uploadProgress >= 100
                                            ? 'Analysing answer key...'
                                            : 'Preparing upload...'}
                                </p>
                            </div>
                        )}
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
                                    Q{q}: {typeof a === 'object' ? `${a.type || 'SMCQ'} [${a.correct_option}] (+${a.positive_marks || 1}/-${a.negative_marks || 0})` : a}
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
    const [pipelineMode, setPipelineMode] = useState('drive'); // 'drive' | 'zip'
    const [zipFile, setZipFile] = useState(null);
    const [zipUploadProgress, setZipUploadProgress] = useState(0);
    const [showLogs, setShowLogs] = useState(false);
    const [clearLoading, setClearLoading] = useState(false);

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
        if (!evaluation?.answer_key_data) { setError('Please load an answer key first before running the pipeline.'); return; }

        let targetName = "";
        let url = "";

        if (pipelineMode === 'drive') {
            url = driveFolderUrl || evaluation?.drive_folder_url;
            if (!url) { setError('Please enter the Google Drive folder URL containing student answer sheets.'); return; }
            targetName = url;
        } else {
            if (!zipFile) { setError('Please upload a ZIP file containing the student sheets.'); return; }
            targetName = zipFile.name;
        }

        setPipelineLoading(true);
        setError('');
        setShowLogs(true);
        setPipelineProgress(10);
        setPipelineLog([
            `[System] Initializing OCR text extraction pipeline...`,
            `[System] Target Source: ${targetName}`,
            `[Info] Processing duration estimated at 20-30 seconds per document. Please standby.`,
        ]);

        try {
            let pipelineResult;

            if (pipelineMode === 'drive') {
                // Save drive folder URL if changed
                if (url !== evaluation.drive_folder_url) {
                    await evaluationService.updateDriveFolderUrl(evaluationId, url);
                    setEvaluation(prev => ({ ...prev, drive_folder_url: url }));
                }

                pipelineResult = await backendService.processDriveFolder(url, (event) => {
                    if (event.message) setPipelineLog(prev => [...prev, event.message]);
                    if (event.type === 'process') setPipelineProgress(prev => Math.min(prev + 5, 80));
                });
            } else {
                setZipUploadProgress(0);
                const collectedZipResults = [];
                pipelineResult = await backendService.processZipFolder(
                    zipFile,
                    (event) => {
                        if (event.message) setPipelineLog(prev => [...prev, event.message]);
                        if (event.type === 'process') setPipelineProgress(prev => Math.min(prev + 5, 80));
                        // Collect individual student result events
                        if (event.type === 'result' && event.data) {
                            collectedZipResults.push(event.data);
                        }
                    },
                    (pct) => setZipUploadProgress(pct)
                );
                setZipUploadProgress(0);
                // Override pipelineResult.results with what we collected from SSE events
                pipelineResult = { ...pipelineResult, results: collectedZipResults };
            }

            setPipelineProgress(80);

            const processedResults = pipelineResult.results || [];
            if (processedResults.length > 0) {
                setPipelineLog(prev => [...prev, '[Database] Committing grades and schema extraction to permanent storage...']);
                const saveResult = await resultsService.saveResults(evaluationId, evaluation.course_id, processedResults, user?.id);
                setPipelineProgress(90);

                // Warn about skipped (unmatched) students
                const skippedRolls = saveResult?.skipped || [];
                const notFoundRolls = saveResult?.notFoundRolls || [];
                const nameMismatches = saveResult?.nameMismatches || [];

                if (skippedRolls.length > 0) {
                    setPipelineLog(prev => [...prev, `[Warning] ${skippedRolls.length} student(s) not found in course roster and were skipped: ${skippedRolls.join(', ')}`]);
                }
                if (nameMismatches.length > 0) {
                    setPipelineLog(prev => [...prev, `[Warning] ${nameMismatches.length} name mismatch(es) detected between OCR and roster.`]);
                }

                // Flag mismatches on the evaluation (triggers alert badge in course detail)
                if (notFoundRolls.length > 0 || nameMismatches.length > 0) {
                    try {
                        await evaluationService.updateHasMismatches(evaluationId, true);
                        const updatedAnswerKeyData = {
                            ...(evaluation.answer_key_data || {}),
                            mismatches: nameMismatches,
                            not_found: notFoundRolls
                        };
                        await evaluationService.saveAnswerKey(evaluationId, updatedAnswerKeyData);
                        setEvaluation(prev => ({ ...prev, has_mismatches: true, answer_key_data: updatedAnswerKeyData }));
                    } catch (mismatchErr) {
                        console.error('Failed to save mismatch data:', mismatchErr);
                    }
                }

                // Update eval status to grading
                await evaluationService.updateStatus(evaluationId, 'grading');
                setEvaluation(prev => ({ ...prev, status: 'grading' }));

                // Refresh results
                const fresh = await resultsService.getResultsByEvaluation(evaluationId);
                setResults(fresh || []);
                setPipelineProgress(100);
                setPipelineLog(prev => [...prev, `[System] Operation concluded successfully. ${fresh.length} assessment records stored.${skippedRolls.length > 0 ? ` ${skippedRolls.length} unmatched roll(s) skipped.` : ''}`]);
            } else {
                setPipelineLog(prev => [...prev, '[Critical] Zero assessments matched. Please verify Drive directory contents and permissions.']);
            }
        } catch (err) {
            setShowLogs(true);
            if (err.message?.includes('timed out')) {
                setError('Pipeline execution exceeded standard timeout threshold. Background processing is active.');
                setPipelineLog(prev => [...prev, '[Timeout] Connection threshold exceeded. The server cluster continues background execution. Please manually reload the data.']);
            } else {
                setError('Pipeline execution failure: ' + err.message);
                setPipelineLog(prev => [...prev, `[Error] Unhandled exception during execution: ${err.message}`]);
            }
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
            const res = await backendService.exportToSheets(course.master_sheet_url, evaluation.subsheet_name, results, evaluation.answer_key_data);
            await evaluationService.updateStatus(evaluationId, 'published');

            if (res.has_mismatches) {
                await evaluationService.updateHasMismatches(evaluationId, true);

                // Save detailed mismatch info inside answer_key_data JSONB
                const updatedAnswerKeyData = {
                    ...(evaluation.answer_key_data || {}),
                    mismatches: res.name_mismatches || [],
                    not_found: res.not_found_in_results || []
                };
                await evaluationService.saveAnswerKey(evaluationId, updatedAnswerKeyData);
            }

            setEvaluation(prev => ({ ...prev, status: 'published', has_mismatches: Boolean(res.has_mismatches) }));

            setExportMsg(`✅ Exported to Google Sheet. Updated: ${res.updated}, Not found: ${res.not_found?.length || 0}. Updating Super Sheet...`);

            // Try updating Super Sheet silently/afterwards
            try {
                await backendService.updateSuperSheet(course.master_sheet_url);
                setExportMsg(prev => prev.replace('Updating Super Sheet...', 'Super Sheet updated!'));
            } catch (superErr) {
                console.error("Failed to update super sheet:", superErr);
                setExportMsg(prev => prev.replace('Updating Super Sheet...', '⚠️ Failed to update Super Sheet.'));
            }

        } catch (err) {
            setExportMsg('❌ Export failed: ' + err.message);
        } finally {
            setExportLoading(false);
        }
    };

    const handleCommentUpdate = (id, comment) => {
        setResults(prev => prev.map(r => r.id === id ? { ...r, comments: comment } : r));
    };

    const handleClearResults = async () => {
        if (!window.confirm("Are you sure you want to clear all results and reset the session? This action cannot be undone and you will need to run the OCR pipeline again.")) {
            return;
        }
        setClearLoading(true);
        setError('');
        try {
            // 1. Clear backend local session cache + answer key
            await backendService.clearResults();

            // 2. Delete from Supabase DB so results don't reappear on page refresh
            const { error: dbErr } = await supabase
                .from('submission_results')
                .delete()
                .eq('evaluation_id', evaluationId);
            if (dbErr) throw dbErr;

            // 3. Reset evaluation status back to draft in DB
            await evaluationService.updateStatus(evaluationId, 'draft');

            // 4. Update local state
            setResults([]);
            setEvaluation(prev => ({ ...prev, status: 'draft', has_mismatches: false }));
            setPipelineProgress(0);
            setPipelineLog([]);
            setShowLogs(false);
        } catch (err) {
            setError('Failed to clear results: ' + err.message);
        } finally {
            setClearLoading(false);
        }
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
                            <button onClick={handleClearResults} disabled={clearLoading || pipelineLoading}
                                className="px-4 py-2 border border-error-300 bg-error-50 text-error-700 rounded-lg hover:bg-error-100 transition-colors text-sm flex items-center gap-2 disabled:opacity-50">
                                {clearLoading
                                    ? <div className="w-4 h-4 border-2 border-error-500 border-t-transparent rounded-full animate-spin" />
                                    : <Icon name="Trash2" size={16} />}
                                Clear Session
                            </button>
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
                                    <div className="flex bg-secondary-50 border border-border rounded-lg overflow-hidden mb-4">
                                        <button onClick={() => setPipelineMode('drive')} className={`flex-1 py-2 text-sm font-medium transition-colors ${pipelineMode === 'drive' ? 'bg-primary-50 text-primary border-b-2 border-primary' : 'text-text-secondary hover:bg-secondary-100'}`}>Google Drive Link</button>
                                        <button onClick={() => setPipelineMode('zip')} className={`flex-1 py-2 text-sm font-medium transition-colors ${pipelineMode === 'zip' ? 'bg-primary-50 text-primary border-b-2 border-primary' : 'text-text-secondary hover:bg-secondary-100'}`}>Upload ZIP File</button>
                                    </div>

                                    {pipelineMode === 'drive' ? (
                                        <div>
                                            <label className="block text-xs font-medium text-text-secondary mb-1">
                                                Google Drive Folder (Student Answer Sheets)
                                            </label>
                                            <input type="url" value={driveFolderUrl} onChange={e => setDriveFolderUrl(e.target.value)}
                                                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary-500"
                                                placeholder="https://drive.google.com/drive/folders/..." />
                                        </div>
                                    ) : (
                                        <div>
                                            <label className="block text-xs font-medium text-text-secondary mb-1">
                                                ZIP Archive (Containing student image files)
                                            </label>
                                            <label className={`block w-full border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-all duration-200 ${zipFile ? 'border-success-500 bg-success-50' : 'border-border hover:border-primary-300 bg-white'}`}>
                                                {zipFile ? (
                                                    <>
                                                        <Icon name="CheckCircle" size={20} className="mx-auto mb-2 text-success-500" />
                                                        <p className="text-sm font-semibold text-success-700">{zipFile.name}</p>
                                                        <p className="text-xs text-success-600 mt-0.5">{(zipFile.size / 1024 / 1024).toFixed(2)} MB · Ready to process</p>
                                                    </>
                                                ) : (
                                                    <>
                                                        <Icon name="FileArchive" size={20} className="mx-auto mb-2 text-secondary-400" />
                                                        <p className="text-sm font-medium text-text-primary">Select ZIP File</p>
                                                        <p className="text-xs text-text-secondary mt-0.5">Drop a .zip archive here</p>
                                                    </>
                                                )}
                                                <input type="file" className="sr-only" accept=".zip,application/zip" onChange={e => setZipFile(e.target.files[0])} />
                                            </label>
                                            {pipelineLoading && pipelineMode === 'zip' && (
                                                <div className="mt-2">
                                                    <div className="flex justify-between text-xs text-text-secondary mb-1">
                                                        <span>
                                                            {zipUploadProgress > 0 && zipUploadProgress < 100
                                                                ? `Uploading ZIP to server...`
                                                                : zipUploadProgress >= 100
                                                                    ? 'Processing sheets...'
                                                                    : 'Preparing upload...'}
                                                        </span>
                                                        {zipUploadProgress > 0 && <span>{zipUploadProgress}%</span>}
                                                    </div>
                                                    <div className="w-full bg-secondary-100 rounded-full h-1.5">
                                                        <div
                                                            className="bg-primary h-1.5 rounded-full transition-all duration-300"
                                                            style={{ width: zipUploadProgress > 0 ? `${zipUploadProgress}%` : '20%' }}
                                                        />
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {/* Checklist */}
                                    <div className="space-y-2">
                                        <div className={`flex items-center gap-2 text-sm ${evaluation?.answer_key_data ? 'text-success-600' : 'text-secondary-400'}`}>
                                            <Icon name={evaluation?.answer_key_data ? 'CheckCircle' : 'Circle'} size={16} />
                                            Answer key loaded
                                        </div>
                                        <div className={`flex items-center gap-2 text-sm ${(pipelineMode === 'drive' && driveFolderUrl) || (pipelineMode === 'zip' && zipFile) ? 'text-success-600' : 'text-secondary-400'}`}>
                                            <Icon name={(pipelineMode === 'drive' && driveFolderUrl) || (pipelineMode === 'zip' && zipFile) ? 'CheckCircle' : 'Circle'} size={16} />
                                            {pipelineMode === 'drive' ? 'Drive folder URL set' : 'ZIP file uploaded'}
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
                                            ? <><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />Executing Pipeline...</>
                                            : <><Icon name="Play" size={16} />Execute OCR Pipeline</>}
                                    </button>
                                </div>

                                {/* Pipeline Log */}
                                {pipelineLog.length > 0 && (
                                    <div className="border-t border-border">
                                        <button
                                            onClick={() => setShowLogs(!showLogs)}
                                            className="w-full p-4 flex items-center justify-between text-sm font-medium text-text-secondary hover:bg-secondary-50 transition-colors"
                                        >
                                            <div className="flex items-center gap-2">
                                                <Icon name="Terminal" size={16} />
                                                Execution Logs
                                            </div>
                                            <Icon name={showLogs ? "ChevronUp" : "ChevronDown"} size={16} />
                                        </button>

                                        {showLogs && (
                                            <div className="px-4 pb-4">
                                                <div className="bg-[#1e1e1e] rounded-lg p-3 max-h-48 overflow-y-auto space-y-1.5 border border-[#333]">
                                                    {pipelineLog.map((log, i) => {
                                                        const isError = log.includes('[Error]') || log.includes('[Critical]') || log.includes('[Timeout]');
                                                        const isWarning = log.includes('[Warning]');
                                                        const isSuccess = log.includes('[Success]');
                                                        let colorClass = 'text-gray-300';
                                                        if (isError) colorClass = 'text-red-400 font-semibold';
                                                        if (isWarning) colorClass = 'text-yellow-400';
                                                        if (isSuccess) colorClass = 'text-green-400';

                                                        return (
                                                            <p key={i} className={`text-[11px] font-mono ${colorClass} leading-relaxed tracking-wide`}>
                                                                <span className="text-gray-500 mr-2">{new Date().toLocaleTimeString('en-US', { hour12: false, hour: "numeric", minute: "numeric", second: "numeric" })}</span>
                                                                {log}
                                                            </p>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                        )}
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
