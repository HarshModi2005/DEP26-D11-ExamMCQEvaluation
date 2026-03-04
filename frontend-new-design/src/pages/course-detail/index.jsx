import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Header from '../../components/ui/Header';
import Sidebar from '../../components/ui/Sidebar';
import PageHeader from '../../components/ui/PageHeader';
import Icon from '../../components/AppIcon';
import MetricsCard from '../dashboard-overview/components/MetricsCard';
import { useAuth } from '../../context/AuthContext';
import { courseService } from '../../services/courseService';
import { evaluationService } from '../../services/evaluationService';
import { studentService } from '../../services/studentService';
import { teamService } from '../../services/teamService';
import { resultsService } from '../../services/resultsService';
import { backendService } from '../../services/backendService';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

// ─── Sub-components ────────────────────────────────────────────────────────────

const StatusBadge = ({ status }) => {
    const map = {
        draft: 'bg-secondary-100 text-secondary-700',
        active: 'bg-blue-100 text-blue-700',
        grading: 'bg-warning-100 text-warning-700',
        published: 'bg-success-100 text-success-700',
    };
    return (
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${map[status] || map.draft}`}>{status}</span>
    );
};

// ─── Create Evaluation Modal ────────────────────────────────────────────────────
const CreateEvalModal = ({ courseId, courseTAs, instructor, currentUserId, onClose, onCreated }) => {
    const [form, setForm] = useState({
        name: '', totalMarks: '', negativeMarking: '0',
        subsheetName: '', driveFolderUrl: '', assigneeIds: [],
    });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleChange = e => setForm(prev => ({ ...prev, [e.target.name]: e.target.value }));

    const toggleAssignee = (id) => {
        setForm(prev => ({
            ...prev,
            assigneeIds: prev.assigneeIds.includes(id)
                ? prev.assigneeIds.filter(a => a !== id)
                : [...prev.assigneeIds, id],
        }));
    };

    const handleSubmit = async e => {
        e.preventDefault();
        if (!form.name) { setError('Evaluation name is required.'); return; }
        setLoading(true);
        try {
            const ev = await evaluationService.createEvaluation({
                courseId,
                name: form.name,
                totalMarks: parseFloat(form.totalMarks) || 0,
                negativeMarking: parseFloat(form.negativeMarking) || 0,
                subsheetName: form.subsheetName,
                driveFolderUrl: form.driveFolderUrl,
                assigneeIds: form.assigneeIds,
                createdBy: currentUserId,
            });
            onCreated(ev);
            onClose();
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const allPeople = [
        ...(instructor ? [{ id: instructor.id, name: instructor.name + ' (Instructor)', role: 'professor' }] : []),
        ...(courseTAs || []).map(ta => ({ id: ta.id, name: ta.name, role: 'ta' })),
    ];

    return (
        <div className="fixed inset-0 z-200 bg-black bg-opacity-50 flex items-center justify-center p-4 overflow-y-auto">
            <div className="bg-surface rounded-2xl shadow-2xl w-full max-w-lg border border-border my-4">
                <div className="flex items-center justify-between p-6 border-b border-border">
                    <h2 className="text-xl font-semibold text-text-primary">Create New Evaluation</h2>
                    <button onClick={onClose} className="p-2 hover:bg-secondary-100 rounded-lg transition-colors">
                        <Icon name="X" size={20} className="text-secondary-500" />
                    </button>
                </div>
                <form onSubmit={handleSubmit} className="p-6 space-y-4">
                    {error && <div className="p-3 bg-error-50 border border-error-100 rounded-lg text-sm text-error">{error}</div>}

                    <div>
                        <label className="block text-sm font-medium text-text-primary mb-1">Evaluation Name *</label>
                        <input name="name" value={form.name} onChange={handleChange}
                            className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                            placeholder="e.g. Quiz 1, Mid Semester Exam" />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-text-primary mb-1">Total Marks</label>
                            <input name="totalMarks" type="number" min="0" value={form.totalMarks} onChange={handleChange}
                                className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                                placeholder="e.g. 50" />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-text-primary mb-1">Negative Marking</label>
                            <input name="negativeMarking" type="number" min="0" step="0.25" value={form.negativeMarking} onChange={handleChange}
                                className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                                placeholder="e.g. 0.25" />
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-text-primary mb-1">
                            Subsheet Name <span className="text-text-secondary font-normal">(tab in master Google Sheet)</span>
                        </label>
                        <input name="subsheetName" value={form.subsheetName} onChange={handleChange}
                            className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                            placeholder="e.g. Quiz1_Marks" />
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-text-primary mb-1">
                            Google Drive Folder URL <span className="text-text-secondary font-normal">(answer sheets)</span>
                        </label>
                        <input name="driveFolderUrl" value={form.driveFolderUrl} onChange={handleChange}
                            className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                            placeholder="https://drive.google.com/drive/folders/..." />
                    </div>

                    {allPeople.length > 0 && (
                        <div>
                            <label className="block text-sm font-medium text-text-primary mb-2">Assign Grading Duties</label>
                            <div className="space-y-2">
                                {allPeople.map(person => (
                                    <label key={person.id} className={`flex items-center gap-3 p-3 border rounded-lg cursor-pointer transition-all ${form.assigneeIds.includes(person.id) ? 'border-primary bg-primary-50' : 'border-border hover:border-primary-200'}`}>
                                        <input type="checkbox" checked={form.assigneeIds.includes(person.id)}
                                            onChange={() => toggleAssignee(person.id)} className="w-4 h-4 text-primary rounded" />
                                        <div className="w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center text-primary-700 text-xs font-bold flex-shrink-0">
                                            {person.name.split(' ').map(n => n[0]).join('').slice(0, 2)}
                                        </div>
                                        <div>
                                            <p className="text-sm font-medium text-text-primary">{person.name}</p>
                                            <p className="text-xs text-text-secondary capitalize">{person.role}</p>
                                        </div>
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}

                    <div className="flex justify-end gap-3 pt-2">
                        <button type="button" onClick={onClose} className="px-4 py-2 border border-border text-text-secondary rounded-lg hover:bg-secondary-50 transition-colors">Cancel</button>
                        <button type="submit" disabled={loading}
                            className="px-5 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50 flex items-center gap-2">
                            {loading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Icon name="Plus" size={16} />}
                            {loading ? 'Creating...' : 'Create Evaluation'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

// ─── Main Component ─────────────────────────────────────────────────────────────
const CourseDetail = () => {
    const { courseId } = useParams();
    const navigate = useNavigate();
    const { user, profile } = useAuth();

    const [course, setCourse] = useState(null);
    const [evaluations, setEvaluations] = useState([]);
    const [students, setStudents] = useState([]);
    const [tas, setTAs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('overview');
    const [showCreateEval, setShowCreateEval] = useState(false);

    // Analytics state
    const [selectedEvalForAnalytics, setSelectedEvalForAnalytics] = useState(null);
    const [analytics, setAnalytics] = useState(null);
    const [analyticsLoading, setAnalyticsLoading] = useState(false);

    // Import students state
    const [importUrl, setImportUrl] = useState('');
    const [importLoading, setImportLoading] = useState(false);
    const [importMessage, setImportMessage] = useState('');

    // Team tab
    const [taSearch, setTaSearch] = useState('');
    const [taSearchResults, setTaSearchResults] = useState([]);
    const [taSearchLoading, setTaSearchLoading] = useState(false);

    // Fetch all data
    const fetchAll = useCallback(async () => {
        setLoading(true);
        try {
            const [courseData, evalsData, studentsData, tasData] = await Promise.all([
                courseService.getCourseById(courseId),
                evaluationService.getEvaluationsByCourse(courseId),
                studentService.getStudentsByCourse(courseId),
                teamService.getTAsByCourse(courseId),
            ]);
            setCourse(courseData);
            setEvaluations(evalsData || []);
            setStudents(studentsData || []);
            setTAs(tasData || []);
            if (courseData?.master_sheet_url) setImportUrl(courseData.master_sheet_url);
        } catch (err) {
            console.error('Failed to load course:', err);
        } finally {
            setLoading(false);
        }
    }, [courseId]);

    useEffect(() => { fetchAll(); }, [fetchAll]);

    const handleImportStudents = async () => {
        if (!importUrl) return;
        setImportLoading(true);
        setImportMessage('');
        try {
            const preview = await backendService.previewSheet(importUrl);
            const parsed = (preview.students || []).map(s => ({
                name: s.name || s.Name || '',
                roll_number: s.entry_number || s['Entry Number'] || s.roll_number || '',
                email: s.email || s.Email || '',
            })).filter(s => s.roll_number);
            if (parsed.length === 0) { setImportMessage('No valid students found in the sheet.'); return; }
            await studentService.importStudents(courseId, parsed);
            setImportMessage(`✅ Imported ${parsed.length} students successfully.`);
            const updated = await studentService.getStudentsByCourse(courseId);
            setStudents(updated || []);
        } catch (err) {
            setImportMessage(`❌ Import failed: ${err.message}`);
        } finally {
            setImportLoading(false);
        }
    };

    const handleRemoveStudent = async (studentId) => {
        await studentService.removeStudentFromCourse(courseId, studentId);
        setStudents(prev => prev.filter(s => s.id !== studentId));
    };

    const handleTaSearch = async (q) => {
        setTaSearch(q);
        if (q.length < 2) { setTaSearchResults([]); return; }
        setTaSearchLoading(true);
        try {
            const results = await teamService.searchTAs(q);
            setTaSearchResults(results.filter(r => !tas.find(t => t.id === r.id)));
        } catch { setTaSearchResults([]); }
        finally { setTaSearchLoading(false); }
    };

    const handleAddTA = async (ta) => {
        await teamService.addTA(courseId, ta.id);
        setTAs(prev => [...prev, ta]);
        setTaSearch('');
        setTaSearchResults([]);
    };

    const handleRemoveTA = async (taId) => {
        await teamService.removeTA(courseId, taId);
        setTAs(prev => prev.filter(t => t.id !== taId));
    };

    const handleEvalStatusChange = async (evalId, status) => {
        await evaluationService.updateStatus(evalId, status);
        setEvaluations(prev => prev.map(e => e.id === evalId ? { ...e, status } : e));
    };

    const loadAnalytics = async (ev) => {
        setSelectedEvalForAnalytics(ev);
        setAnalyticsLoading(true);
        try {
            const data = await resultsService.getAnalytics(ev.id);
            setAnalytics(data);
        } catch { setAnalytics(null); }
        finally { setAnalyticsLoading(false); }
    };

    const tabs = [
        { id: 'overview', label: 'Overview', icon: 'LayoutDashboard' },
        { id: 'evaluations', label: 'Evaluations', icon: 'FileText' },
        { id: 'students', label: 'Students', icon: 'Users' },
        { id: 'team', label: 'Teaching Team', icon: 'Shield' },
        { id: 'analytics', label: 'Analytics', icon: 'BarChart3' },
        { id: 'settings', label: 'Settings', icon: 'Settings' },
    ];

    if (loading) {
        return (
            <div className="min-h-screen bg-background">
                <Header /><Sidebar />
                <main className="lg:ml-64 pt-16 flex items-center justify-center min-h-[80vh]">
                    <div className="flex flex-col items-center gap-4">
                        <div className="w-10 h-10 border-4 border-primary border-t-transparent rounded-full animate-spin" />
                        <p className="text-text-secondary">Loading course...</p>
                    </div>
                </main>
            </div>
        );
    }

    if (!course) {
        return (
            <div className="min-h-screen bg-background">
                <Header /><Sidebar />
                <main className="lg:ml-64 pt-16 flex items-center justify-center">
                    <div className="text-center">
                        <p className="text-text-primary font-medium">Course not found.</p>
                        <button onClick={() => navigate('/faculty-dashboard')} className="mt-4 text-primary hover:underline">Back to My Courses</button>
                    </div>
                </main>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-background">
            <Header />
            <Sidebar />

            {showCreateEval && (
                <CreateEvalModal
                    courseId={courseId}
                    courseTAs={tas}
                    instructor={course.profiles}
                    currentUserId={user?.id}
                    onClose={() => setShowCreateEval(false)}
                    onCreated={ev => setEvaluations(prev => [ev, ...prev])}
                />
            )}

            <main className="lg:ml-64 pt-16 transition-all duration-300">
                <div className="p-6 max-w-7xl mx-auto space-y-6">
                    {/* Breadcrumb */}
                    <div className="flex items-center text-sm text-text-secondary">
                        <button onClick={() => navigate('/faculty-dashboard')} className="hover:text-primary transition-colors flex items-center">
                            <Icon name="ArrowLeft" size={14} className="mr-1" />Back to Courses
                        </button>
                        <span className="mx-2">/</span>
                        <span className="font-medium text-text-primary">{course.code}</span>
                    </div>

                    <PageHeader
                        title={course.title}
                        description={`${course.code} • ${course.semester || ''} • ${course.department || ''}`}
                        actions={
                            <div className="flex space-x-3">
                                {(profile?.role === 'professor' || profile?.id === course.instructor_id) && (
                                    <button onClick={() => setShowCreateEval(true)}
                                        className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors shadow-sm flex items-center">
                                        <Icon name="Plus" size={16} className="mr-2" />
                                        <span>Create Evaluation</span>
                                    </button>
                                )}
                            </div>
                        }
                    />

                    {/* Stats */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        <MetricsCard title="Total Students" value={students.length} icon="Users" color="primary" trend="enrolled" />
                        <MetricsCard title="Evaluations" value={evaluations.length} icon="FileText" color="secondary" trend={`${evaluations.filter(e => e.status === 'grading').length} active`} />
                        <MetricsCard title="Teaching Team" value={tas.length + 1} icon="Shield" color="success" trend="1 instructor" />
                    </div>

                    {/* Tabs */}
                    <div className="border-b border-border">
                        <nav className="-mb-px flex space-x-8 overflow-x-auto" aria-label="Tabs">
                            {tabs.map(tab => (
                                <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                                    className={`group inline-flex items-center py-4 px-1 border-b-2 font-medium text-sm transition-colors whitespace-nowrap ${activeTab === tab.id ? 'border-primary text-primary' : 'border-transparent text-text-secondary hover:text-text-primary hover:border-secondary-300'}`}>
                                    <Icon name={tab.icon} size={18} className={`mr-2 ${activeTab === tab.id ? 'text-primary' : 'text-secondary-400'}`} />
                                    {tab.label}
                                </button>
                            ))}
                        </nav>
                    </div>

                    {/* Tab Content */}
                    <div className="bg-surface border border-border rounded-xl p-6 min-h-[400px]">

                        {/* ── OVERVIEW ── */}
                        {activeTab === 'overview' && (
                            <div className="space-y-4">
                                <h3 className="text-lg font-medium text-text-primary">Course Information</h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    <div className="p-4 bg-secondary-50 rounded-lg">
                                        <p className="text-xs text-text-secondary uppercase tracking-wider mb-1">Instructor</p>
                                        <p className="font-medium text-text-primary">{course.profiles?.name || '—'}</p>
                                    </div>
                                    <div className="p-4 bg-secondary-50 rounded-lg">
                                        <p className="text-xs text-text-secondary uppercase tracking-wider mb-1">Department</p>
                                        <p className="font-medium text-text-primary">{course.department || '—'}</p>
                                    </div>
                                    <div className="p-4 bg-secondary-50 rounded-lg">
                                        <p className="text-xs text-text-secondary uppercase tracking-wider mb-1">Semester</p>
                                        <p className="font-medium text-text-primary">{course.semester || '—'}</p>
                                    </div>
                                    <div className="p-4 bg-secondary-50 rounded-lg">
                                        <p className="text-xs text-text-secondary uppercase tracking-wider mb-1">Master Google Sheet</p>
                                        {course.master_sheet_url ? (
                                            <a href={course.master_sheet_url} target="_blank" rel="noopener noreferrer"
                                                className="text-primary hover:underline text-sm truncate block">
                                                Open Sheet ↗
                                            </a>
                                        ) : <p className="text-text-secondary text-sm">Not set — configure in Settings tab</p>}
                                    </div>
                                </div>
                                {course.description && (
                                    <div className="p-4 bg-secondary-50 rounded-lg">
                                        <p className="text-xs text-text-secondary uppercase tracking-wider mb-1">Description</p>
                                        <p className="text-text-primary">{course.description}</p>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ── EVALUATIONS ── */}
                        {activeTab === 'evaluations' && (
                            <div className="space-y-4">
                                <div className="flex items-center justify-between">
                                    <h3 className="text-lg font-medium text-text-primary">Course Evaluations</h3>
                                    <button onClick={() => setShowCreateEval(true)}
                                        className="px-3 py-1.5 bg-primary text-white rounded-lg text-sm hover:bg-primary-700 transition-colors flex items-center gap-2">
                                        <Icon name="Plus" size={14} />New Evaluation
                                    </button>
                                </div>
                                {evaluations.length === 0 ? (
                                    <div className="text-center py-16 text-text-secondary">
                                        <Icon name="FileText" size={40} className="mx-auto mb-3 text-secondary-300" />
                                        <p>No evaluations yet. Create your first one.</p>
                                    </div>
                                ) : (
                                    <div className="space-y-3">
                                        {evaluations.map(ev => (
                                            <div key={ev.id} className="border border-border rounded-xl p-5 hover:border-primary-300 transition-colors">
                                                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                                                    <div className="flex-1">
                                                        <div className="flex items-center gap-3 mb-1">
                                                            <h4 className="font-semibold text-text-primary">{ev.name}</h4>
                                                            <StatusBadge status={ev.status} />
                                                        </div>
                                                        <p className="text-sm text-text-secondary mb-2">
                                                            {ev.total_marks > 0 ? `${ev.total_marks} marks` : 'Marks not set'}
                                                            {ev.negative_marking > 0 ? ` • −${ev.negative_marking} negative` : ''}
                                                            {ev.subsheet_name ? ` • Sheet: ${ev.subsheet_name}` : ''}
                                                        </p>
                                                        {ev.evaluation_duties?.length > 0 && (
                                                            <div className="flex items-center gap-1 text-xs text-text-secondary">
                                                                <Icon name="Users" size={12} />
                                                                <span>Assigned to: {ev.evaluation_duties.map(d => d.profiles?.name).filter(Boolean).join(', ')}</span>
                                                            </div>
                                                        )}
                                                    </div>
                                                    <div className="flex items-center gap-2 flex-shrink-0">
                                                        <button
                                                            onClick={() => navigate(`/evaluate/${ev.id}`)}
                                                            className="px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary-700 transition-colors flex items-center gap-2">
                                                            <Icon name="Scan" size={14} />Start Grading
                                                        </button>
                                                        {ev.status !== 'published' && (
                                                            <select value={ev.status}
                                                                onChange={e => handleEvalStatusChange(ev.id, e.target.value)}
                                                                className="text-sm border border-border rounded-lg px-2 py-1.5 bg-surface text-text-secondary focus:ring-primary">
                                                                <option value="draft">Draft</option>
                                                                <option value="active">Active</option>
                                                                <option value="grading">Grading</option>
                                                                <option value="published">Published</option>
                                                            </select>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ── STUDENTS ── */}
                        {activeTab === 'students' && (
                            <div className="space-y-5">
                                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                                    <h3 className="text-lg font-medium text-text-primary">Students <span className="text-secondary-400 font-normal text-base">({students.length})</span></h3>
                                </div>
                                {/* Import from Google Sheet */}
                                <div className="p-4 border border-primary-100 bg-primary-50 rounded-xl">
                                    <p className="text-sm font-semibold text-primary mb-2 flex items-center gap-2">
                                        <Icon name="FileSpreadsheet" size={16} />Import from Master Google Sheet
                                    </p>
                                    <div className="flex gap-2">
                                        <input type="url" value={importUrl} onChange={e => setImportUrl(e.target.value)}
                                            placeholder="https://docs.google.com/spreadsheets/d/..."
                                            className="flex-1 px-3 py-2 border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary-500 bg-surface" />
                                        <button onClick={handleImportStudents} disabled={importLoading || !importUrl}
                                            className="px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors flex items-center gap-2">
                                            {importLoading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Icon name="Download" size={14} />}
                                            {importLoading ? 'Importing...' : 'Import'}
                                        </button>
                                    </div>
                                    {importMessage && <p className="mt-2 text-sm">{importMessage}</p>}
                                </div>

                                {students.length === 0 ? (
                                    <div className="text-center py-16 text-text-secondary">
                                        <Icon name="Users" size={40} className="mx-auto mb-3 text-secondary-300" />
                                        <p>No students imported yet. Use the import tool above.</p>
                                    </div>
                                ) : (
                                    <div className="overflow-x-auto">
                                        <table className="min-w-full divide-y divide-border">
                                            <thead className="bg-secondary-50">
                                                <tr>
                                                    <th className="px-6 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider">Name</th>
                                                    <th className="px-6 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider">Roll Number</th>
                                                    <th className="px-6 py-3 text-left text-xs font-medium text-text-secondary uppercase tracking-wider">Email</th>
                                                    <th className="px-6 py-3 text-right text-xs font-medium text-text-secondary uppercase tracking-wider">Actions</th>
                                                </tr>
                                            </thead>
                                            <tbody className="bg-surface divide-y divide-border">
                                                {students.map(s => (
                                                    <tr key={s.id} className="hover:bg-secondary-50 transition-colors">
                                                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-text-primary">{s.name}</td>
                                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-text-secondary font-mono">{s.roll_number}</td>
                                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">{s.email || '—'}</td>
                                                        <td className="px-6 py-4 whitespace-nowrap text-right">
                                                            <button onClick={() => handleRemoveStudent(s.id)}
                                                                className="text-error hover:text-error-700 text-sm transition-colors">Remove</button>
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ── TEACHING TEAM ── */}
                        {activeTab === 'team' && (
                            <div className="space-y-5">
                                <div className="flex items-center justify-between">
                                    <h3 className="text-lg font-medium text-text-primary">Teaching Team</h3>
                                </div>

                                {/* Instructor */}
                                <div>
                                    <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2">Instructor</p>
                                    <div className="border border-border rounded-lg p-4 flex items-center gap-4">
                                        <div className="w-10 h-10 rounded-full bg-primary-100 flex items-center justify-center text-primary-700 font-bold text-sm">
                                            {course.profiles?.name?.split(' ').map(n => n[0]).join('').slice(0, 2) || 'PR'}
                                        </div>
                                        <div>
                                            <p className="font-medium text-text-primary">{course.profiles?.name || 'Unknown'}</p>
                                            <p className="text-sm text-text-secondary">Course Instructor</p>
                                        </div>
                                    </div>
                                </div>

                                {/* TAs */}
                                <div>
                                    <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2">Teaching Assistants ({tas.length})</p>

                                    {/* Add TA search */}
                                    {profile?.role === 'professor' && (
                                        <div className="mb-4 relative">
                                            <div className="flex gap-2">
                                                <div className="relative flex-1">
                                                    <Icon name="Search" size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-secondary-400" />
                                                    <input type="text" value={taSearch} onChange={e => handleTaSearch(e.target.value)}
                                                        placeholder="Search TAs by name or entry number..."
                                                        className="w-full pl-9 pr-4 py-2.5 border border-border rounded-lg text-sm focus:ring-2 focus:ring-primary-500 transition-colors" />
                                                </div>
                                            </div>
                                            {taSearchResults.length > 0 && (
                                                <div className="absolute top-full left-0 right-0 mt-1 bg-surface border border-border rounded-lg shadow-lg z-10 overflow-hidden">
                                                    {taSearchResults.map(ta => (
                                                        <button key={ta.id} onClick={() => handleAddTA(ta)}
                                                            className="w-full flex items-center gap-3 px-4 py-3 hover:bg-primary-50 transition-colors text-left">
                                                            <div className="w-8 h-8 rounded-full bg-secondary-100 flex items-center justify-center text-secondary-600 text-xs font-bold">
                                                                {ta.name?.split(' ').map(n => n[0]).join('').slice(0, 2)}
                                                            </div>
                                                            <div>
                                                                <p className="text-sm font-medium text-text-primary">{ta.name}</p>
                                                                <p className="text-xs text-text-secondary">{ta.entry_number} • {ta.department}</p>
                                                            </div>
                                                            <Icon name="Plus" size={16} className="ml-auto text-primary" />
                                                        </button>
                                                    ))}
                                                </div>
                                            )}
                                            {taSearch.length >= 2 && taSearchLoading && (
                                                <div className="absolute top-full left-0 right-0 mt-1 bg-surface border border-border rounded-lg p-3 text-sm text-text-secondary">Searching...</div>
                                            )}
                                        </div>
                                    )}

                                    {tas.length === 0 ? (
                                        <p className="text-sm text-text-secondary">No TAs assigned yet.</p>
                                    ) : (
                                        <div className="space-y-2">
                                            {tas.map(ta => (
                                                <div key={ta.id} className="border border-border rounded-lg p-4 flex items-center justify-between">
                                                    <div className="flex items-center gap-3">
                                                        <div className="w-10 h-10 rounded-full bg-secondary-100 flex items-center justify-center text-secondary-600 font-bold text-sm">
                                                            {ta.name?.split(' ').map(n => n[0]).join('').slice(0, 2)}
                                                        </div>
                                                        <div>
                                                            <p className="font-medium text-text-primary">{ta.name}</p>
                                                            <p className="text-sm text-text-secondary">{ta.entry_number || ''} {ta.department ? `• ${ta.department}` : ''}</p>
                                                        </div>
                                                    </div>
                                                    {profile?.role === 'professor' && (
                                                        <button onClick={() => handleRemoveTA(ta.id)}
                                                            className="text-error hover:text-error-700 text-sm transition-colors">Remove</button>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* ── ANALYTICS ── */}
                        {activeTab === 'analytics' && (
                            <div className="space-y-5">
                                {!selectedEvalForAnalytics ? (
                                    <>
                                        <h3 className="text-lg font-medium text-text-primary">Exam Analytics</h3>
                                        <p className="text-sm text-text-secondary">Select an evaluation to view detailed analytics.</p>
                                        {evaluations.length === 0 ? (
                                            <div className="text-center py-16 text-text-secondary">
                                                <Icon name="BarChart3" size={40} className="mx-auto mb-3 text-secondary-300" />
                                                <p>No evaluations to analyze yet.</p>
                                            </div>
                                        ) : (
                                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                                {evaluations.map(ev => (
                                                    <div key={ev.id} onClick={() => loadAnalytics(ev)}
                                                        className="border border-border rounded-xl p-5 cursor-pointer hover:border-primary-300 hover:shadow-md transition-all group">
                                                        <div className="flex items-center gap-3 mb-3">
                                                            <div className="w-10 h-10 bg-primary-100 rounded-lg flex items-center justify-center text-primary-700 group-hover:bg-primary group-hover:text-white transition-colors">
                                                                <Icon name="FileText" size={20} />
                                                            </div>
                                                            <StatusBadge status={ev.status} />
                                                        </div>
                                                        <h4 className="font-semibold text-text-primary mb-1">{ev.name}</h4>
                                                        <p className="text-sm text-text-secondary">{ev.total_marks > 0 ? `${ev.total_marks} marks` : 'Marks not set'}</p>
                                                        <div className="flex items-center text-sm text-primary mt-3 group-hover:underline">
                                                            View Analytics <Icon name="ArrowRight" size={14} className="ml-1" />
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    <div className="space-y-6">
                                        <div className="flex items-center gap-3">
                                            <button onClick={() => { setSelectedEvalForAnalytics(null); setAnalytics(null); }}
                                                className="text-text-secondary hover:text-primary transition-colors flex items-center gap-1 text-sm">
                                                <Icon name="ArrowLeft" size={14} />Back
                                            </button>
                                            <span className="text-text-secondary">/</span>
                                            <span className="font-medium text-text-primary">{selectedEvalForAnalytics.name}</span>
                                        </div>

                                        {analyticsLoading ? (
                                            <div className="flex items-center justify-center py-16">
                                                <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
                                            </div>
                                        ) : !analytics ? (
                                            <div className="text-center py-16 text-text-secondary">
                                                <Icon name="BarChart3" size={40} className="mx-auto mb-3 text-secondary-300" />
                                                <p>No results found for this evaluation yet.</p>
                                                <button onClick={() => navigate(`/evaluate/${selectedEvalForAnalytics.id}`)}
                                                    className="mt-3 text-primary hover:underline text-sm">
                                                    Go to Evaluate page →
                                                </button>
                                            </div>
                                        ) : (
                                            <>
                                                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                                    <MetricsCard title="Average" value={`${analytics.averageScore}/${analytics.maxScore}`} icon="BarChart2" color="primary" />
                                                    <MetricsCard title="Median" value={`${analytics.medianScore}`} icon="Activity" color="secondary" />
                                                    <MetricsCard title="Highest" value={analytics.highestScore} icon="TrendingUp" color="success" />
                                                    <MetricsCard title="Graded" value={`${analytics.gradedCount}/${analytics.totalStudents}`} icon="CheckCircle" color="warning" />
                                                </div>
                                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                                    <div className="border border-border rounded-xl p-5">
                                                        <h4 className="font-medium text-text-primary mb-4">Score Distribution</h4>
                                                        <ResponsiveContainer width="100%" height={200}>
                                                            <BarChart data={analytics.distribution}>
                                                                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                                                                <XAxis dataKey="range" tick={{ fontSize: 12 }} />
                                                                <YAxis tick={{ fontSize: 12 }} />
                                                                <Tooltip />
                                                                <Bar dataKey="count" fill="var(--color-primary)" radius={[4, 4, 0, 0]} />
                                                            </BarChart>
                                                        </ResponsiveContainer>
                                                    </div>
                                                    <div className="border border-border rounded-xl p-5 space-y-4">
                                                        <h4 className="font-medium text-text-primary">Question Analysis</h4>
                                                        {analytics.hardestQuestion && (
                                                            <div className="p-4 bg-error-50 border border-error-100 rounded-lg">
                                                                <div className="flex items-center text-error-700 mb-1 gap-2">
                                                                    <Icon name="AlertTriangle" size={16} /><span className="font-semibold text-sm">Hardest</span>
                                                                </div>
                                                                <p className="text-sm font-medium">{analytics.hardestQuestion.question}</p>
                                                                <p className="text-xs text-text-secondary">{analytics.hardestQuestion.correctRate}% correct rate</p>
                                                            </div>
                                                        )}
                                                        {analytics.easiestQuestion && (
                                                            <div className="p-4 bg-success-50 border border-success-100 rounded-lg">
                                                                <div className="flex items-center text-success-700 mb-1 gap-2">
                                                                    <Icon name="Check" size={16} /><span className="font-semibold text-sm">Easiest</span>
                                                                </div>
                                                                <p className="text-sm font-medium">{analytics.easiestQuestion.question}</p>
                                                                <p className="text-xs text-text-secondary">{analytics.easiestQuestion.correctRate}% correct rate</p>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ── SETTINGS ── */}
                        {activeTab === 'settings' && (
                            <div className="space-y-6 max-w-lg">
                                <h3 className="text-lg font-medium text-text-primary">Course Settings</h3>
                                <div>
                                    <label className="block text-sm font-medium text-text-secondary mb-1">Master Google Sheet Link</label>
                                    <div className="flex gap-2">
                                        <input type="url" defaultValue={course.master_sheet_url || ''}
                                            id="masterSheetInput"
                                            className="flex-1 px-3 py-2 border border-border rounded-lg focus:ring-primary focus:border-primary"
                                            placeholder="https://docs.google.com/spreadsheets/d/..." />
                                        <button onClick={async () => {
                                            const val = document.getElementById('masterSheetInput').value;
                                            await courseService.updateCourse(courseId, { master_sheet_url: val });
                                            setCourse(prev => ({ ...prev, master_sheet_url: val }));
                                            setImportUrl(val);
                                            alert('Saved!');
                                        }}
                                            className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors text-sm">
                                            Save
                                        </button>
                                    </div>
                                    <p className="text-xs text-text-secondary mt-1">The central class list sheet for this course. Used to import students and export marks.</p>
                                </div>
                            </div>
                        )}

                    </div>
                </div>
            </main>
        </div>
    );
};

export default CourseDetail;
