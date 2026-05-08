import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Header from '../../components/ui/Header';
import Icon from '../../components/AppIcon';
import { useAuth } from '../../context/AuthContext';
import { evaluationService } from '../../services/evaluationService';
import { resultsService } from '../../services/resultsService';
import { backendService } from '../../services/backendService';

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

const formatLiveProgressLine = ({ processed = 0, total = 0, errors = 0 }) => {
    const pct = total > 0 ? Math.round((processed / total) * 100) : 0;
    const success = Math.max(processed - errors, 0);
    return `[Live] ${processed}/${total} (${pct}%) | ✅${success} ❌${errors}`;
};

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
    const [mode, setMode] = useState('view'); // 'view' | 'manual' | 'upload' | 'template'
    const [driveUrl, setDriveUrl] = useState(evaluation?.drive_folder_url || '');
    const [loading, setLoading] = useState(false);
    const [err, setErr] = useState('');
    const [manualJson, setManualJson] = useState(`{
  "answers": {
    "1": {
      "question_type": "SMCQ",
      "correct_answer": "A",
      "positive_marks": 3,
      "negative_marks": 1
    },
    "2": {
      "question_type": "MMCQ",
      "correct_answer": "AC",
      "positive_marks": 4,
      "negative_marks": 0
    },
    "3": {
      "question_type": "NCQ",
      "correct_answer": "2.5",
      "positive_marks": 4,
      "negative_marks": 1
    }
  },
  "negative_marking": 0
}`);
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

    const downloadTemplate = async (format, numQuestions) => {
        setLoading(true); setErr('');
        try {
            const response = await backendService.downloadTemplate(format, numQuestions);
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `answer_key_template_${numQuestions}q.${format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
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
                {[['view', 'FolderOpen', 'From Drive'], ['upload', 'Upload', 'Upload File'], ['manual', 'Code', 'Manual JSON'], ['template', 'Download', 'Download Template']].map(([m, icon, label]) => (
                    <button key={m} onClick={() => setMode(m)}
                        className={`flex-1 py-2.5 text-xs font-medium flex items-center justify-center gap-1.5 transition-colors ${mode === m ? 'bg-primary-50 text-primary border-b-2 border-primary' : 'text-text-secondary hover:bg-secondary-50'}`}>
                        <Icon name={icon} size={14} />
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

                {/* Download Template */}
                {mode === 'template' && (
                    <div className="space-y-3">
                        <p className="text-xs text-text-secondary">Download a blank answer key template to fill out.</p>
                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className="block text-xs font-medium text-text-secondary mb-1">Format</label>
                                <select className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary-500" id="template-format">
                                    <option value="csv">CSV</option>
                                    <option value="xlsx">Excel (XLSX)</option>
                                    <option value="json">JSON</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-xs font-medium text-text-secondary mb-1">Questions</label>
                                <input type="number" min="1" max="200" defaultValue="50"
                                    className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary-500"
                                    id="template-questions" />
                            </div>
                        </div>
                        <button onClick={() => {
                            const format = document.getElementById('template-format').value;
                            const numQuestions = parseInt(document.getElementById('template-questions').value);
                            downloadTemplate(format, numQuestions);
                        }} disabled={loading}
                            className="w-full py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary-700 disabled:opacity-50 flex items-center justify-center gap-2">
                            {loading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Icon name="Download" size={14} />}
                            {loading ? 'Downloading...' : 'Download Template'}
                        </button>
                    </div>
                )}

                {/* Current Key Preview */}
                {hasKey && evaluation.answer_key_data?.answers && (
                    <div className="mt-2 p-3 bg-success-50 border border-success-100 rounded-lg">
                        <p className="text-xs font-semibold text-success-700 mb-2 flex items-center gap-1"><Icon name="CheckCircle" size={12} />Loaded Answer Key</p>

                        {/* Question Type Summary */}
                        {(() => {
                            const typeCounts = {};
                            Object.values(evaluation.answer_key_data.answers).forEach(a => {
                                const type = (typeof a === 'object' ? a.question_type : 'SMCQ') || 'SMCQ';
                                typeCounts[type] = (typeCounts[type] || 0) + 1;
                            });
                            return Object.keys(typeCounts).length > 1 && (
                                <div className="mb-2 flex flex-wrap gap-2">
                                    {Object.entries(typeCounts).map(([type, count]) => (
                                        <span key={type} className="px-2 py-1 bg-white border border-success-200 rounded text-xs font-medium">
                                            {type}: {count}
                                        </span>
                                    ))}
                                </div>
                            );
                        })()}

                        <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                            {Object.entries(evaluation.answer_key_data.answers).slice(0, 20).map(([q, a]) => {
                                const answer = typeof a === 'object' ? (a.correct_answer || a.correct_option) : a;
                                const type = typeof a === 'object' ? a.question_type : 'SMCQ';
                                const typeColor = type === 'MMCQ' ? 'border-blue-200 bg-blue-50' :
                                    type === 'NCQ' ? 'border-orange-200 bg-orange-50' :
                                        'border-success-200 bg-white';
                                return (
                                    <span key={q} className={`px-1.5 py-0.5 border rounded text-xs font-mono ${typeColor}`}>
                                        Q{q}:{answer}
                                        {type !== 'SMCQ' && <span className="ml-1 text-xs opacity-70">({type})</span>}
                                    </span>
                                );
                            })}
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

// ── Code Answer Key Panel (LeetCode) ──────
const CodeAnswerKeyPanel = ({ evaluation, onKeyLoaded }) => {
    const [mode, setMode] = useState('upload'); // upload | manual
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [manualJson, setManualJson] = useState('{\n  "problems": {\n    "1": { "slug": "two-sum", "marks": 3 }\n  }\n}');
    const [keyPreview, setKeyPreview] = useState(null);
    const hasKey = !!evaluation?.answer_key_data?.problems;

    const handleFileUpload = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setLoading(true);
        setError('');
        try {
            // Upload to the standard answer key endpoint (which parses Excel/CSV)
            const res = await backendService.uploadAnswerKey(file);
            const answerKey = res.answer_key;  // { total_questions, answers: { "1": { correct_answer, positive_marks, ... } } }
            const answers = answerKey?.answers || {};

            // Transform into code-eval format: { problems: { "1": { slug: "two-sum", marks: 3 } } }
            const problems = {};
            for (const [qNum, entry] of Object.entries(answers)) {
                problems[String(qNum)] = {
                    slug: String(entry.correct_answer || '').trim(),
                    marks: entry.positive_marks || 1,
                    partial_marking_allowed: entry.partial_marking_allowed || false,
                };
            }
            const codeKey = { problems, total_questions: Object.keys(problems).length };
            setKeyPreview(codeKey);

            // Save to Supabase
            await evaluationService.saveAnswerKey(evaluation.id, codeKey);
            onKeyLoaded(codeKey);
        } catch (err) {
            setError(err.message || 'Failed to parse answer key file.');
        } finally {
            setLoading(false);
        }
    };

    const handleManualSubmit = async () => {
        setError('');
        setLoading(true);
        try {
            const parsed = JSON.parse(manualJson);
            if (!parsed.problems) throw new Error('JSON must have a "problems" key.');
            parsed.total_questions = Object.keys(parsed.problems).length;
            setKeyPreview(parsed);

            // Save to Supabase
            await evaluationService.saveAnswerKey(evaluation.id, parsed);
            onKeyLoaded(parsed);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="bg-surface border border-border rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
                <Icon name="Code" size={20} className="text-green-600" />
                <h3 className="text-lg font-semibold text-text-primary">Code Answer Key</h3>
                <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">LeetCode</span>
                {hasKey && <span className="ml-auto px-2 py-0.5 rounded-full text-xs font-medium bg-success-100 text-success-700">✓ Loaded</span>}
            </div>

            {/* Mode tabs */}
            <div className="flex gap-2 mb-4">
                {[{ id: 'upload', label: 'Upload File', icon: 'Upload' }, { id: 'manual', label: 'Manual JSON', icon: 'Edit3' }].map(tab => (
                    <button key={tab.id} onClick={() => setMode(tab.id)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${mode === tab.id ? 'bg-primary text-white' : 'bg-secondary-100 text-text-secondary hover:bg-secondary-200'
                            }`}>
                        <Icon name={tab.icon} size={14} /> {tab.label}
                    </button>
                ))}
            </div>

            {error && <div className="mb-3 p-3 bg-error-50 border border-error-100 rounded-lg text-sm text-error">{error}</div>}

            {mode === 'upload' && (
                <div>
                    {/* Expected format display */}
                    <div className="mb-3 p-3 bg-blue-50 border border-blue-100 rounded-lg">
                        <p className="text-xs font-semibold text-blue-700 mb-2">📋 Expected Excel/CSV Format:</p>
                        <table className="w-full text-xs border-collapse">
                            <thead>
                                <tr className="bg-blue-100">
                                    <th className="border border-blue-200 px-2 py-1 text-left text-blue-800">Question Number</th>
                                    <th className="border border-blue-200 px-2 py-1 text-left text-blue-800">Name</th>
                                    <th className="border border-blue-200 px-2 py-1 text-left text-blue-800">Positive Marks</th>
                                    <th className="border border-blue-200 px-2 py-1 text-left text-blue-800">Negative Marks</th>
                                    <th className="border border-blue-200 px-2 py-1 text-left text-blue-800">Partial Marking</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600">1</td>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600 font-mono">two-sum</td>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600">3</td>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600">1</td>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600 font-semibold">A</td>
                                </tr>
                                <tr>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600">2</td>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600 font-mono">add-two-numbers</td>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600">5</td>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600">1</td>
                                    <td className="border border-blue-200 px-2 py-1 text-blue-600">NA</td>
                                </tr>
                            </tbody>
                        </table>
                        <p className="text-xs text-blue-500 mt-1">The "Name" column should contain the LeetCode problem slug from the URL. "Partial Marking": <strong>A</strong> = allowed (proportional marks), <strong>NA</strong> = not allowed.</p>
                    </div>
                    <input type="file" accept=".csv,.xlsx,.xls" onChange={handleFileUpload}
                        className="w-full text-sm file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:bg-primary-50 file:text-primary-700 hover:file:bg-primary-100 transition-colors" />
                </div>
            )}

            {mode === 'manual' && (
                <div>
                    <textarea value={manualJson} onChange={e => setManualJson(e.target.value)}
                        rows={8}
                        className="w-full px-3 py-2 border border-border rounded-lg font-mono text-sm focus:ring-2 focus:ring-primary-500 transition-colors" />
                    <button onClick={handleManualSubmit} disabled={loading}
                        className="mt-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors text-sm font-medium flex items-center gap-2 disabled:opacity-50">
                        <Icon name="Check" size={14} /> {loading ? 'Saving...' : 'Apply Key'}
                    </button>
                </div>
            )}

            {loading && <p className="text-sm text-text-secondary mt-2 animate-pulse">Parsing & saving...</p>}

            {(keyPreview || hasKey) && (
                <div className="mt-4 p-3 bg-green-50 border border-green-100 rounded-lg">
                    <p className="text-sm font-semibold text-green-700 mb-1">
                        ✅ Answer key loaded — {Object.keys((keyPreview || evaluation?.answer_key_data)?.problems || {}).length} problems
                    </p>
                    <div className="text-xs text-green-600 space-y-0.5">
                        {Object.entries((keyPreview || evaluation?.answer_key_data)?.problems || {}).map(([q, def]) => (
                            <div key={q} className="flex items-center gap-1.5">
                                <span>Q{q}: <code className="bg-green-100 px-1 rounded">{def.slug}</code> ({def.marks} marks)</span>
                                {def.partial_marking_allowed
                                    ? <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-medium">Partial</span>
                                    : <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-xs">No Partial</span>
                                }
                            </div>
                        ))}
                    </div>
                </div>
            )}
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
    const [rawOcrResults, setRawOcrResults] = useState([]); // ALL OCR results, including unmatched
    const [pageLoading, setPageLoading] = useState(true);
    const [pipelineLoading, setPipelineLoading] = useState(false);
    const [exportLoading, setExportLoading] = useState(false);
    const [pipelineLog, setPipelineLog] = useState([]);
    const [pipelineProgress, setPipelineProgress] = useState(0);
    const [pipelineSheetCount, setPipelineSheetCount] = useState(null); // {total, processed, cached, new}
    const [error, setError] = useState('');
    const [exportMsg, setExportMsg] = useState('');
    const [driveFolderUrl, setDriveFolderUrl] = useState('');
    const [zipFile, setZipFile] = useState(null);
    const [processingMode, setProcessingMode] = useState('drive'); // 'drive' | 'zip'
    const [forceReprocess, setForceReprocess] = useState(false);
    const [cacheStatus, setCacheStatus] = useState(null);
    const logEndRef = React.useRef(null);
    const lastProgressLogRef = React.useRef('');

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

    useEffect(() => {
        fetchData();
        loadCacheStatus();
    }, [fetchData]);

    const loadCacheStatus = async () => {
        try {
            const status = await backendService.getCacheStatus();
            setCacheStatus(status);
        } catch (err) {
            console.warn('Failed to load cache status:', err);
        }
    };

    const appendPipelineLog = useCallback((line) => {
        if (!line) return;
        setPipelineLog(prev => [...prev, line]);
    }, []);

    const appendProgressLog = useCallback((line) => {
        if (!line || lastProgressLogRef.current === line) return;
        lastProgressLogRef.current = line;
        setPipelineLog(prev => [...prev, line]);
    }, []);

    const handleKeyLoaded = (keyData) => {
        setEvaluation(prev => ({ ...prev, answer_key_data: keyData }));
        const count = keyData.total_questions || Object.keys(keyData.problems || {}).length || '?';
        setPipelineLog(prev => [...prev, `Answer key loaded — ${count} questions`]);
    };

    const handleRunPipeline = async () => {
        if (processingMode === 'drive') {
            const url = driveFolderUrl || evaluation?.drive_folder_url;
            if (!url) { setError('Please enter the Google Drive folder URL containing student answer sheets.'); return; }
        } else if (processingMode === 'zip') {
            if (!zipFile) { setError('Please select a ZIP file containing student answer sheets.'); return; }
        }

        if (!evaluation?.answer_key_data) { setError('Please load an answer key first before running the pipeline.'); return; }

        setPipelineLoading(true);
        setError('');
        setPipelineProgress(0);
        setPipelineSheetCount(null);
        lastProgressLogRef.current = '';

        const modeText = processingMode === 'zip' ? 'ZIP file' : 'Drive folder';
        const sourceText = processingMode === 'zip' ? zipFile.name : (driveFolderUrl || evaluation?.drive_folder_url);

        setPipelineLog(prev => [...prev,
        `Starting OCR pipeline (${modeText})...`,
        `Source: ${sourceText}`,
        forceReprocess ? 'Force reprocess enabled.' : 'Evaluation ready.',
        ]);

        try {
            let pipelineResult;
            const startTime = Date.now();
            const speed = "0.00";

            const isCodeEval = evaluation?.evaluation_type === 'code';

            if (isCodeEval) {
                // ── Code Evaluation Pipeline ──
                const codeAnswerKey = evaluation?.answer_key_data || {};
                setPipelineLog(prev => [...prev, `Starting synchronous Code Evaluation...`]);

                if (processingMode === 'drive') {
                    const url = driveFolderUrl || evaluation?.drive_folder_url;
                    if (url !== evaluation.drive_folder_url) {
                        await evaluationService.updateDriveFolderUrl(evaluationId, url);
                        setEvaluation(prev => ({ ...prev, drive_folder_url: url }));
                    }
                    setPipelineProgress(0);
                    setPipelineLog(prev => [...prev, 'Scanning Drive folder for sheets...']);
                    pipelineResult = await backendService.processDriveCodeEval(url, codeAnswerKey);
                } else {
                    setPipelineProgress(0);
                    setPipelineLog(prev => [...prev, 'Processing ZIP file...']);
                    pipelineResult = await backendService.processZipCodeEval(zipFile, codeAnswerKey);
                }
            } else {
                // ── Standard Objective Pipeline ──
                if (processingMode === 'drive') {
                    const url = driveFolderUrl || evaluation?.drive_folder_url;
                    if (url !== evaluation.drive_folder_url) {
                        await evaluationService.updateDriveFolderUrl(evaluationId, url);
                        setEvaluation(prev => ({ ...prev, drive_folder_url: url }));
                    }

                    setPipelineProgress(0);
                    setPipelineLog(prev => [...prev, 'Scanning Drive folder for sheets...']);
                    pipelineResult = await backendService.processDriveFolder(url, evaluationId, forceReprocess);
                } else {
                    setPipelineProgress(0);
                    setPipelineLog(prev => [...prev, 'Processing ZIP file...']);
                    pipelineResult = await backendService.processZipFile(zipFile, evaluationId, forceReprocess, true);
                }
            }

            const processedResults = pipelineResult.results || [];
            const stats = pipelineResult.processing_stats || {};
            const totalSheets = stats.total_files || processedResults.length;
            const cacheHits = (stats.cache_hits || 0) + (stats.ocr_cache_hits || 0);
            const newlyProcessed = totalSheets - cacheHits;

            setPipelineSheetCount({
                total: totalSheets,
                processed: processedResults.length,
                cached: cacheHits,
                newOcr: newlyProcessed,
                errors: pipelineResult.errors?.length || 0,
            });

            const processedPct = totalSheets > 0 ? Math.round((processedResults.length / totalSheets) * 100) : 0;
            const errorCount = pipelineResult.errors?.length || 0;

            const logLine = `[OCR] ${processedResults.length}/${totalSheets} (${processedPct}%) | ✓${processedResults.length} ✗${errorCount} ${cacheHits} cached | ${speed}/s`;

            setPipelineProgress(processedResults.length > 0 ? 99 : processedPct);
            setPipelineLog(prev => [...prev, `[OCR] ${processedResults.length}/${totalSheets} (${processedPct}%) | ✅${processedResults.length} ❌${errorCount}`]);

            if (processedResults.length > 0) {
                setPipelineLog(prev => [...prev, 'Saving results to database...']);
                await resultsService.saveResults(evaluationId, evaluation.course_id, processedResults, user?.id);
                setPipelineProgress(99);

                await evaluationService.updateStatus(evaluationId, 'grading');
                setEvaluation(prev => ({ ...prev, status: 'grading' }));

                // Store ALL raw OCR results for export (before DB filtering)
                setRawOcrResults(processedResults);

                const fresh = await resultsService.getResultsByEvaluation(evaluationId);
                setResults(fresh || []);
                setPipelineProgress(100);
                setPipelineLog(prev => [...prev, `Done! ${fresh.length} student results saved.`]);
            } else {
                setPipelineLog(prev => [...prev, 'No results returned. Check the source folder or file.']);
            }
        } catch (err) {
            setError('Pipeline failed: ' + err.message);
            setPipelineLog(prev => [...prev, `Error: ${err.message}`]);
        } finally {
            setPipelineLoading(false);
            loadCacheStatus();
        }
    };

    const handleRunPipelineLive = async () => {
        const isZipMode = processingMode === 'zip';
        const url = driveFolderUrl || evaluation?.drive_folder_url;
        if (isZipMode) {
            if (!zipFile) { setError('Please select a ZIP file containing student answer sheets.'); return; }
        } else if (!url) {
            setError('Please enter the Google Drive folder URL containing student answer sheets.'); return;
        }
        if (!evaluation?.answer_key_data) { setError('Please load an answer key first before running the pipeline.'); return; }

        setPipelineLoading(true);
        setError('');
        setPipelineProgress(0);
        setPipelineSheetCount(null);
        lastProgressLogRef.current = '';

        appendPipelineLog(`Starting OCR pipeline (${isZipMode ? 'ZIP file' : 'Drive folder'})...`);
        appendPipelineLog(`Source: ${isZipMode ? zipFile.name : url}`);
        appendPipelineLog(forceReprocess ? 'Force reprocess enabled.' : 'Evaluation ready.');

        try {
            if (!isZipMode && url !== evaluation.drive_folder_url) {
                await evaluationService.updateDriveFolderUrl(evaluationId, url);
                setEvaluation(prev => ({ ...prev, drive_folder_url: url }));
            }

            setPipelineProgress(0);
            appendPipelineLog(isZipMode ? 'Processing ZIP file...' : 'Scanning Drive folder for sheets...');

            const startTime = Date.now();
            const started = isZipMode
                ? await backendService.startZipProcessing(zipFile, evaluationId, forceReprocess, true)
                : await backendService.startDriveFolderProcessing(url, evaluationId, forceReprocess);
            appendPipelineLog(`Live tracking started for ${started.run_id || started.processing_id}`);

            let pipelineResult = null;
            while (true) {
                const status = isZipMode
                    ? await backendService.getPipelineRunStatus(started.run_id)
                    : await backendService.getProcessingStatus(started.processing_id);
                const totalSheets = status.total_files || 0;
                const processedSheets = status.processed_files || 0;
                const cacheHits = (status.cache_hits || 0) + (status.ocr_cache_hits || 0);
                const errorCount = Array.isArray(status.errors) ? status.errors.length : 0;
                const liveProgress = totalSheets > 0 ? Math.round((processedSheets / totalSheets) * 100) : Math.round(status.progress_percentage || 0);

                setPipelineProgress(Math.min(liveProgress, 99));
                setPipelineSheetCount({
                    total: totalSheets,
                    processed: processedSheets,
                    cached: cacheHits,
                    newOcr: Math.max(totalSheets - cacheHits, 0),
                    errors: errorCount,
                });

                appendProgressLog(formatLiveProgressLine({
                    processed: processedSheets,
                    total: totalSheets,
                    errors: errorCount,
                }));

                if (status.status === 'completed') {
                    pipelineResult = {
                        results: status.results || [],
                        errors: status.errors || [],
                        processing_stats: status,
                    };
                    break;
                }

                if (status.status === 'failed') {
                    throw new Error(status.error || 'Drive processing failed.');
                }

                await sleep(1200);
            }

            const processedResults = pipelineResult.results || [];
            const stats = pipelineResult.processing_stats || {};
            const totalSheets = stats.total_files || processedResults.length;
            const cacheHits = (stats.cache_hits || 0) + (stats.ocr_cache_hits || 0);

            setPipelineSheetCount({
                total: totalSheets,
                processed: processedResults.length,
                cached: cacheHits,
                newOcr: Math.max(totalSheets - cacheHits, 0),
                errors: pipelineResult.errors?.length || 0,
            });

            const processedPct = totalSheets > 0 ? Math.round((processedResults.length / totalSheets) * 100) : 0;
            const errorCount = pipelineResult.errors?.length || 0;

            setPipelineProgress(processedResults.length > 0 ? 99 : processedPct);
            appendPipelineLog(`[OCR] ${processedResults.length}/${totalSheets} (${processedPct}%) | ✅${processedResults.length} ❌${errorCount}`);

            if (processedResults.length > 0) {
                appendPipelineLog('Saving results to database...');
                await resultsService.saveResults(evaluationId, evaluation.course_id, processedResults, user?.id);
                setPipelineProgress(99);

                await evaluationService.updateStatus(evaluationId, 'grading');
                setEvaluation(prev => ({ ...prev, status: 'grading' }));
                setRawOcrResults(processedResults);

                const fresh = await resultsService.getResultsByEvaluation(evaluationId);
                setResults(fresh || []);
                setPipelineProgress(100);
                appendPipelineLog(`Done! ${fresh.length} student results saved.`);
            } else {
                appendPipelineLog('No results returned. Check the source folder or file.');
            }
        } catch (err) {
            setError('Pipeline failed: ' + err.message);
            appendPipelineLog(`Error: ${err.message}`);
        } finally {
            setPipelineLoading(false);
            loadCacheStatus();
        }
    };

    const handleClearResults = async () => {
        if (!window.confirm("Are you sure you want to completely clear the Grading Results and OCR cache for this evaluation? You will start fresh with zero processed students.")) return;

        setError('');
        setPipelineProgress(0);
        setPipelineLog(['Clearing OCR cache and Grading Results...']);
        try {
            await backendService.clearCache();
            await resultsService.clearResultsByEvaluation(evaluationId);
            setResults([]);
            setRawOcrResults([]);
            setPipelineLog(prev => [...prev, 'Cache and results cleared successfully! Start a new pipeline run.']);
            await loadCacheStatus();
        } catch (err) {
            setError('Failed to clear results: ' + err.message);
            setPipelineLog(prev => [...prev, `Error: ${err.message}`]);
        }
    };

    const handleExportToSheet = async () => {
        const course = evaluation?.courses;
        if (!course?.master_sheet_url) {
            setExportMsg('Error: No master Google Sheet URL set for this course. Set it in Course Settings.');
            return;
        }
        setExportLoading(true);
        setExportMsg('');
        try {
            const evalName = evaluation.subsheet_name || evaluation.name;
            // Use raw OCR results if available (includes unmatched/garbled entry numbers)
            // Fall back to DB results if pipeline hasn't been run this session
            const exportResults = rawOcrResults.length > 0 ? rawOcrResults : results;
            const mappedResults = exportResults.map(r => ({
                ...r,
                entry_number: r.entry_number || r.students?.roll_number || '',
                name: r.name || r.students?.name || ''
            }));
            const res = await backendService.exportToSheets(
                course.master_sheet_url,
                evaluation.subsheet_name,
                evalName,
                mappedResults,
                evaluation.answer_key_data
            );
            await evaluationService.updateStatus(evaluationId, 'published');
            setEvaluation(prev => ({ ...prev, status: 'published' }));

            let msg = `Exported to Google Sheet "${evalName}". Updated: ${res.updated} students.`;
            if (res.response_sheet) {
                msg += ` Response sheet: "${res.response_sheet.sheet_name}" (${res.response_sheet.students_exported} students).`;
            }
            if (res.super_sheet) {
                msg += ` Super Sheet updated.`;
            }
            if (res.statistics) {
                msg += ` Stats: Mean=${res.statistics.mean}, Highest=${res.statistics.highest}, Lowest=${res.statistics.lowest}.`;
            }
            setExportMsg(msg);
        } catch (err) {
            setExportMsg('Export failed: ' + err.message);
        } finally {
            setExportLoading(false);
        }
    };

    const [syncLoading, setSyncLoading] = useState(false);
    const [renameLoading, setRenameLoading] = useState(false);

    const buildResultsForDriveRename = () => {
        const list = rawOcrResults.length > 0 ? rawOcrResults : results;
        return list.map((r) => ({
            entry_number: r.entry_number || r.students?.roll_number || '',
            name: r.name || r.students?.name || '',
            comments: r.comments || '',
            file_name: r.file_name || undefined,
            file_id: r.file_id || undefined,
        }));
    };

    const handleRenameDriveFiles = async () => {
        const folderUrl = driveFolderUrl || evaluation?.drive_folder_url;
        if (!folderUrl) {
            setExportMsg('Error: Set a Google Drive folder URL on this evaluation to rename files there.');
            return;
        }
        if (!window.confirm(
            "Rename files in that Google Drive folder using each sheet's detected roll number and name? "
            + "Already-renamed files may be skipped. This cannot be undone from the app."
        )) {
            return;
        }
        setRenameLoading(true);
        setExportMsg('');
        try {
            const payload = buildResultsForDriveRename();
            if (payload.length === 0) {
                setExportMsg('No results to use for renaming.');
                return;
            }
            const res = await backendService.renameDriveFiles(folderUrl, payload, false, false);
            if (res.error) {
                setExportMsg(`Rename: ${res.error}`);
                return;
            }
            const msg = res.message
                || (res.execution_result
                    ? `Renamed ${res.execution_result.success}/${res.execution_result.total} files.`
                    : 'Rename finished.');
            setExportMsg(msg);
        } catch (err) {
            setExportMsg('Rename failed: ' + err.message);
        } finally {
            setRenameLoading(false);
        }
    };

    const handleSyncFromSheet = async () => {
        const course = evaluation?.courses;
        if (!course?.master_sheet_url) {
            setExportMsg('Error: No master Google Sheet URL set for this course.');
            return;
        }
        setSyncLoading(true);
        setExportMsg('');
        try {
            // Send the raw OR DB results to backend for synchronization
            const currentResults = rawOcrResults.length > 0 ? rawOcrResults : results;
            const mappedResults = currentResults.map(r => ({
                ...r,
                entry_number: r.entry_number || (r.students?.roll_number) || '',
                name: r.name || (r.students?.name) || ''
            }));

            // Pass the subsheet name to extract exported marks manually modified by user
            const res = await backendService.syncResultsWithSheet(course.master_sheet_url, mappedResults, evaluation?.subsheet_name);

            // Save synchronized results directly back to DB
            if (res.results && res.results.length > 0) {
                await resultsService.saveResults(evaluationId, course.id, res.results, user?.id);

                // Fetch fresh records to display
                const fresh = await resultsService.getResultsByEvaluation(evaluationId);
                setResults(fresh || []);
                setExportMsg('Successfully synchronized App Data with Google Sheet.');
            } else {
                setExportMsg('No results returned from Sync.');
            }
        } catch (err) {
            setExportMsg('Sync failed: ' + err.message);
        } finally {
            setSyncLoading(false);
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
                                <>
                                    <button
                                        type="button"
                                        onClick={handleRenameDriveFiles}
                                        disabled={renameLoading || syncLoading || exportLoading || !(driveFolderUrl || evaluation?.drive_folder_url)}
                                        title={!(driveFolderUrl || evaluation?.drive_folder_url) ? 'Save a Drive folder URL for this evaluation first' : undefined}
                                        className="px-4 py-2 border border-secondary-300 bg-secondary-50 text-secondary-800 rounded-lg hover:bg-secondary-100 transition-colors text-sm flex items-center gap-2 disabled:opacity-50">
                                        {renameLoading
                                            ? <div className="w-4 h-4 border-2 border-secondary-500 border-t-transparent rounded-full animate-spin" />
                                            : <Icon name="FilePenLine" size={16} />}
                                        Rename Drive files
                                    </button>
                                    <button onClick={handleSyncFromSheet} disabled={syncLoading || exportLoading || renameLoading}
                                        className="px-4 py-2 border border-blue-300 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 transition-colors text-sm flex items-center gap-2 disabled:opacity-50">
                                        {syncLoading
                                            ? <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                                            : <Icon name="RefreshCw" size={16} />}
                                        Sync from Sheet
                                    </button>
                                    <button onClick={handleExportToSheet} disabled={exportLoading || syncLoading || renameLoading}
                                        className="px-4 py-2 border border-success-300 bg-success-50 text-success-700 rounded-lg hover:bg-success-100 transition-colors text-sm flex items-center gap-2 disabled:opacity-50">
                                        {exportLoading
                                            ? <div className="w-4 h-4 border-2 border-success-500 border-t-transparent rounded-full animate-spin" />
                                            : <Icon name="FileSpreadsheet" size={16} />}
                                        Export to Sheet
                                    </button>
                                </>
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
                        <div className={`p-4 rounded-xl border text-sm ${!exportMsg.startsWith('Error') && !exportMsg.startsWith('Export failed') ? 'bg-success-50 border-success-200 text-success-700' : 'bg-error-50 border-error-200 text-error'}`}>
                            {exportMsg}
                        </div>
                    )}

                    {/* Main two-column layout */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

                        {/* ── LEFT PANEL ── */}
                        <div className="space-y-6">

                            {/* Answer Key */}
                            {evaluation?.evaluation_type === 'code'
                                ? <CodeAnswerKeyPanel evaluation={evaluation} onKeyLoaded={handleKeyLoaded} />
                                : <AnswerKeyPanel evaluation={evaluation} onKeyLoaded={handleKeyLoaded} />
                            }

                            {/* Run Pipeline */}
                            <div className="bg-surface border border-border rounded-xl overflow-hidden">
                                <div className="p-4 border-b border-border flex items-center gap-2">
                                    <Icon name="Cpu" size={18} className="text-primary" />
                                    <h3 className="font-semibold text-text-primary">OCR Pipeline</h3>
                                </div>
                                <div className="p-4 space-y-4">
                                    {/* Processing Mode Selector */}
                                    <div>
                                        <label className="block text-xs font-medium text-text-secondary mb-2">Processing Mode</label>
                                        <div className="flex border border-border rounded-lg overflow-hidden">
                                            <button
                                                onClick={() => setProcessingMode('drive')}
                                                className={`flex-1 py-2 px-3 text-sm font-medium flex items-center justify-center gap-2 transition-colors ${processingMode === 'drive' ? 'bg-primary text-white' : 'bg-surface text-text-secondary hover:bg-secondary-50'
                                                    }`}>
                                                <Icon name="FolderOpen" size={14} />
                                                Google Drive
                                            </button>
                                            <button
                                                onClick={() => setProcessingMode('zip')}
                                                className={`flex-1 py-2 px-3 text-sm font-medium flex items-center justify-center gap-2 transition-colors ${processingMode === 'zip' ? 'bg-primary text-white' : 'bg-surface text-text-secondary hover:bg-secondary-50'
                                                    }`}>
                                                <Icon name="Archive" size={14} />
                                                ZIP Upload
                                            </button>
                                        </div>
                                    </div>

                                    {/* Drive Mode */}
                                    {processingMode === 'drive' && (
                                        <div>
                                            <label className="block text-xs font-medium text-text-secondary mb-1">
                                                Google Drive Folder (Student Answer Sheets)
                                            </label>
                                            <input type="url" value={driveFolderUrl} onChange={e => setDriveFolderUrl(e.target.value)}
                                                className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary-500"
                                                placeholder="https://drive.google.com/drive/folders/..." />
                                        </div>
                                    )}

                                    {/* ZIP Mode */}
                                    {processingMode === 'zip' && (
                                        <div>
                                            <label className="block text-xs font-medium text-text-secondary mb-1">
                                                ZIP File (Answer Key + Student Sheets)
                                            </label>
                                            <label className="block w-full border-2 border-dashed border-border rounded-lg p-4 text-center cursor-pointer hover:border-primary-300 transition-colors">
                                                <Icon name="Archive" size={20} className="mx-auto mb-2 text-secondary-400" />
                                                <p className="text-sm text-text-secondary">{zipFile ? zipFile.name : 'Click to select ZIP file'}</p>
                                                <input type="file" className="sr-only" accept=".zip"
                                                    onChange={e => setZipFile(e.target.files[0])} />
                                            </label>
                                        </div>
                                    )}

                                    {/* Processing Options */}
                                    <div className="space-y-3">
                                        <div className="flex items-center justify-between">
                                            <label className="flex items-center gap-2 text-sm">
                                                <input
                                                    type="checkbox"
                                                    checked={forceReprocess}
                                                    onChange={e => setForceReprocess(e.target.checked)}
                                                    className="rounded border-border text-primary focus:ring-primary-500"
                                                />
                                                Force reprocess (bypass cache)
                                            </label>
                                            {cacheStatus && (
                                                <span className="text-xs text-text-secondary">
                                                    Cache: {cacheStatus.cache_stats?.total_entries || 0} files
                                                </span>
                                            )}
                                        </div>

                                        {forceReprocess && (
                                            <div className="p-2 bg-warning-50 border border-warning-200 rounded text-xs text-warning-700">
                                                Note: This will reprocess all files, ignoring cached results. Use only if you suspect cache issues.
                                            </div>
                                        )}
                                    </div>

                                    {/* Checklist */}
                                    <div className="space-y-2">
                                        <div className={`flex items-center gap-2 text-sm ${evaluation?.answer_key_data ? 'text-success-600' : 'text-secondary-400'}`}>
                                            <Icon name={evaluation?.answer_key_data ? 'CheckCircle' : 'Circle'} size={16} />
                                            Answer key loaded
                                        </div>
                                        {processingMode === 'drive' && (
                                            <div className={`flex items-center gap-2 text-sm ${driveFolderUrl ? 'text-success-600' : 'text-secondary-400'}`}>
                                                <Icon name={driveFolderUrl ? 'CheckCircle' : 'Circle'} size={16} />
                                                Drive folder URL set
                                            </div>
                                        )}
                                        {processingMode === 'zip' && (
                                            <div className={`flex items-center gap-2 text-sm ${zipFile ? 'text-success-600' : 'text-secondary-400'}`}>
                                                <Icon name={zipFile ? 'CheckCircle' : 'Circle'} size={16} />
                                                ZIP file selected
                                            </div>
                                        )}
                                    </div>

                                    {/* Sheet count summary badge */}
                                    {pipelineSheetCount && (
                                        <div className="grid grid-cols-2 gap-2 text-center">
                                            <div className="bg-primary-50 border border-primary-100 rounded-lg p-2">
                                                <p className="text-lg font-bold text-primary">{pipelineSheetCount.total}</p>
                                                <p className="text-xs text-primary-600">Total Sheets</p>
                                            </div>
                                            <div className="bg-success-50 border border-success-100 rounded-lg p-2">
                                                <p className="text-lg font-bold text-success-600">{pipelineSheetCount.processed}</p>
                                                <p className="text-xs text-success-600">Processed</p>
                                            </div>
                                            <div className="bg-blue-50 border border-blue-100 rounded-lg p-2">
                                                <p className="text-lg font-bold text-blue-600">{pipelineSheetCount.cached}</p>
                                                <p className="text-xs text-blue-600">From Cache</p>
                                            </div>
                                            <div className="bg-secondary-50 border border-border rounded-lg p-2">
                                                <p className="text-lg font-bold text-text-primary">{pipelineSheetCount.newOcr}</p>
                                                <p className="text-xs text-text-secondary">New OCR</p>
                                            </div>
                                        </div>
                                    )}

                                    {/* Progress bar */}
                                    {pipelineLoading && (
                                        <div>
                                            <div className="flex justify-between text-xs text-text-secondary mb-1">
                                                <span>Processing sheets...</span>
                                                <span>{pipelineProgress}%</span>
                                            </div>
                                            <div className="w-full bg-secondary-100 rounded-full h-2">
                                                <div className="bg-primary h-2 rounded-full transition-all duration-500"
                                                    style={{ width: `${pipelineProgress}%` }} />
                                            </div>
                                        </div>
                                    )}

                                    <button onClick={handleRunPipelineLive} disabled={pipelineLoading}
                                        className="w-full py-3 bg-primary text-white rounded-lg font-semibold hover:bg-primary-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-2">
                                        {pipelineLoading
                                            ? <><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />Running OCR Pipeline...</>
                                            : <><Icon name="Play" size={16} />Run OCR Pipeline</>}
                                    </button>
                                </div>

                                {/* Pipeline Log */}
                                {pipelineLog.length > 0 && (
                                    <div className="border-t border-border p-4">
                                        <div className="flex items-center justify-between mb-2">
                                            <p className="text-xs font-medium text-text-secondary flex items-center gap-1">
                                                <Icon name="Terminal" size={12} />Pipeline Log
                                                <span className="ml-1 text-text-tertiary">({pipelineLog.length} lines)</span>
                                            </p>
                                            <button onClick={() => setPipelineLog([])} className="text-xs text-text-tertiary hover:text-error transition-colors">Clear</button>
                                        </div>
                                        <div
                                            className="bg-secondary-900 rounded-lg p-3 max-h-52 overflow-y-auto space-y-1"
                                            ref={el => { if (el) el.scrollTop = el.scrollHeight; }}
                                        >
                                            {pipelineLog.map((log, i) => {
                                                const isCache = log.includes('⚡') || log.includes('cache');
                                                const isError = log.includes('❌') || log.includes('⚠️');
                                                const isSuccess = log.includes('✅') || log.includes('🎉');
                                                const color = isError ? 'text-red-400' : isSuccess ? 'text-green-400' : isCache ? 'text-blue-300' : 'text-secondary-200';
                                                return <p key={i} className={`text-xs font-mono ${color}`}>{log}</p>;
                                            })}
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

                                    {/* Answer Key Type Summary */}
                                    {evaluation?.answer_key_data?.answers && (() => {
                                        const typeCounts = {};
                                        Object.values(evaluation.answer_key_data.answers).forEach(a => {
                                            const type = (typeof a === 'object' ? a.question_type : 'SMCQ') || 'SMCQ';
                                            typeCounts[type] = (typeCounts[type] || 0) + 1;
                                        });
                                        return Object.keys(typeCounts).length > 1 && (
                                            <div className="pt-2 border-t border-border">
                                                <p className="text-xs text-text-secondary mb-2">Question Types:</p>
                                                <div className="flex flex-wrap gap-2">
                                                    {Object.entries(typeCounts).map(([type, count]) => (
                                                        <span key={type} className="px-2 py-1 bg-primary-50 text-primary-700 rounded text-xs font-medium">
                                                            {type}: {count}
                                                        </span>
                                                    ))}
                                                </div>
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
                                        <div className="flex items-center gap-4">
                                            <button onClick={handleClearResults} className="text-xs text-secondary-500 hover:text-error-600 hover:underline flex items-center gap-1 transition-colors">
                                                <Icon name="Trash2" size={12} />Clear Cache & Results
                                            </button>
                                            <button onClick={fetchData} className="text-xs text-primary hover:underline flex items-center gap-1">
                                                <Icon name="RefreshCw" size={12} />Refresh
                                            </button>
                                        </div>
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
