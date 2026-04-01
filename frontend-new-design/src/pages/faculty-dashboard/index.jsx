import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Header from '../../components/ui/Header';
import PageHeader from '../../components/ui/PageHeader';
import Icon from '../../components/AppIcon';
import { useAuth } from '../../context/AuthContext';
import { courseService } from '../../services/courseService';
import { invitationService } from '../../services/invitationService';
import { evaluationService } from '../../services/evaluationService';

import { createPortal } from 'react-dom';

const GRADIENT_COLORS = [
    'from-blue-500 to-blue-600',
    'from-emerald-500 to-emerald-600',
    'from-purple-500 to-purple-600',
    'from-orange-500 to-orange-600',
    'from-pink-500 to-pink-600',
    'from-teal-500 to-teal-600',
];

const CreateCourseModal = ({ onClose, onCreated, userId }) => {
    const [form, setForm] = useState({ code: '', title: '', description: '', department: '', semester: '', masterSheetUrl: '' });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleChange = e => setForm(prev => ({ ...prev, [e.target.name]: e.target.value }));

    const handleSubmit = async e => {
        e.preventDefault();
        if (!form.code || !form.title) { setError('Code and title are required.'); return; }
        setLoading(true);
        try {
            const course = await courseService.createCourse({ ...form, instructorId: userId, masterSheetUrl: form.masterSheetUrl || null });
            onCreated(course);
            onClose();
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    return createPortal(
        <div className="fixed inset-0 z-[200] bg-black bg-opacity-50 flex items-center justify-center p-4">
            <div className="bg-surface rounded-2xl shadow-2xl w-full max-w-lg border border-border">
                <div className="flex items-center justify-between p-6 border-b border-border">
                    <h2 className="text-xl font-semibold text-text-primary">Create New Course</h2>
                    <button onClick={onClose} className="p-2 hover:bg-secondary-100 rounded-lg transition-colors">
                        <Icon name="X" size={20} className="text-secondary-500" />
                    </button>
                </div>
                <form onSubmit={handleSubmit} className="p-6 space-y-4">
                    {error && (
                        <div className="p-3 bg-error-50 border border-error-100 rounded-lg text-sm text-error">{error}</div>
                    )}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-text-primary mb-1">Course Code *</label>
                            <input type="text" name="code" value={form.code} onChange={handleChange}
                                className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                                placeholder="e.g. CS306" />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-text-primary mb-1">Semester</label>
                            <input type="text" name="semester" value={form.semester} onChange={handleChange}
                                className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                                placeholder="e.g. Spring 2026" />
                        </div>
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-text-primary mb-1">Course Title *</label>
                        <input type="text" name="title" value={form.title} onChange={handleChange}
                            className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                            placeholder="e.g. Data Structures and Algorithms" />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-text-primary mb-1">Department</label>
                        <input type="text" name="department" value={form.department} onChange={handleChange}
                            className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                            placeholder="e.g. Computer Science" />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-text-primary mb-1">Description</label>
                        <textarea name="description" value={form.description} onChange={handleChange} rows={2}
                            className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors resize-none"
                            placeholder="Short description of the course" />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-text-primary mb-1">
                            Master Google Sheet URL <span className="text-text-secondary font-normal">(optional, can be set later)</span>
                        </label>
                        <input type="url" name="masterSheetUrl" value={form.masterSheetUrl} onChange={handleChange}
                            className="w-full px-3 py-2.5 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                            placeholder="https://docs.google.com/spreadsheets/d/..." />
                    </div>
                    <div className="flex justify-end gap-3 pt-2">
                        <button type="button" onClick={onClose}
                            className="px-4 py-2 border border-border text-text-secondary rounded-lg hover:bg-secondary-50 transition-colors">
                            Cancel
                        </button>
                        <button type="submit" disabled={loading}
                            className="px-5 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-50 flex items-center gap-2">
                            {loading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Icon name="Plus" size={16} />}
                            {loading ? 'Creating...' : 'Create Course'}
                        </button>
                    </div>
                </form>
            </div>
        </div>,
        document.body
    );
};

const AcceptInviteModal = ({ invitation, onConfirm, onClose, loading }) => {
    if (!invitation) return null;
    return createPortal(
        <div className="fixed inset-0 z-[200] bg-black bg-opacity-50 flex items-center justify-center p-4">
            <div className="bg-surface rounded-2xl shadow-2xl w-full max-w-md border border-border">
                <div className="flex items-center justify-between p-6 border-b border-border">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-primary-50 rounded-lg flex items-center justify-center">
                            <Icon name="Check" size={20} className="text-primary" />
                        </div>
                        <h2 className="text-xl font-semibold text-text-primary">Accept Invitation</h2>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-secondary-100 rounded-lg transition-colors">
                        <Icon name="X" size={20} className="text-secondary-500" />
                    </button>
                </div>
                <div className="p-6">
                    <p className="text-text-primary mb-6">
                        Are you sure you want to accept the invitation to be a TA for <span className="font-semibold">{invitation.courses?.code} — {invitation.courses?.title}</span>?
                    </p>
                    <div className="flex justify-end gap-3">
                        <button onClick={onClose}
                            className="px-4 py-2 border border-border text-text-secondary rounded-lg hover:bg-secondary-50 transition-colors">
                            Cancel
                        </button>
                        <button onClick={onConfirm} disabled={loading}
                            className="px-5 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors shadow-sm flex items-center gap-2">
                            {loading && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                            Confirm Accept
                        </button>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
};

const DeclineInviteModal = ({ invitation, onConfirm, onClose, loading }) => {
    if (!invitation) return null;
    return createPortal(
        <div className="fixed inset-0 z-[200] bg-black bg-opacity-50 flex items-center justify-center p-4">
            <div className="bg-surface rounded-2xl shadow-2xl w-full max-w-md border border-border">
                <div className="flex items-center justify-between p-6 border-b border-border">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-error-50 rounded-lg flex items-center justify-center">
                            <Icon name="X" size={20} className="text-error" />
                        </div>
                        <h2 className="text-xl font-semibold text-text-primary">Decline Invitation</h2>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-secondary-100 rounded-lg transition-colors">
                        <Icon name="X" size={20} className="text-secondary-500" />
                    </button>
                </div>
                <div className="p-6">
                    <p className="text-text-primary mb-6">
                        Are you sure you want to decline the invitation for <span className="font-semibold">{invitation.courses?.code} — {invitation.courses?.title}</span>? This action cannot be undone.
                    </p>
                    <div className="flex justify-end gap-3">
                        <button onClick={onClose}
                            className="px-4 py-2 border border-border text-text-secondary rounded-lg hover:bg-secondary-50 transition-colors">
                            Cancel
                        </button>
                        <button onClick={onConfirm} disabled={loading}
                            className="px-5 py-2 bg-error text-white rounded-lg hover:bg-error-700 transition-colors shadow-sm flex items-center gap-2">
                            {loading && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                            Confirm Decline
                        </button>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
};

const FacultyDashboard = () => {
    const navigate = useNavigate();
    const { user, profile } = useAuth();
    const [courses, setCourses] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [search, setSearch] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [pendingInvites, setPendingInvites] = useState([]);
    const [acceptingId, setAcceptingId] = useState(null);
    const [showAcceptModal, setShowAcceptModal] = useState(false);
    const [showDeclineModal, setShowDeclineModal] = useState(false);
    const [activeInvite, setActiveInvite] = useState(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [allEvaluations, setAllEvaluations] = useState([]);

    // We now use allEvaluations instead of mockTasks
    useEffect(() => {
        console.log('[FacultyDashboard] useEffect triggered — user:', user?.email, 'profile:', profile?.name, profile?.role);
        if (!user || !profile) {
            console.log('[FacultyDashboard] useEffect — user or profile missing, skipping fetch');
            return;
        }
        const fetchCourses = async (retries = 3) => {
            console.log(`[FacultyDashboard] fetchCourses called, retries remaining: ${retries}, role: ${profile.role}`);
            setLoading(true);
            try {
                let data;
                if (profile.role === 'professor') {
                    console.log('[FacultyDashboard] Calling getCoursesByProfessor...');
                    data = await courseService.getCoursesByProfessor(user.id);
                } else {
                    console.log('[FacultyDashboard] Calling getCoursesByTA...');
                    data = await courseService.getCoursesByTA(user.id);
                }
                console.log('[FacultyDashboard] fetchCourses SUCCESS, courses loaded:', data?.length);
                setCourses(data || []);
                setError('');
                if (data && data.length > 0) {
                    const courseIds = data.map(c => c.id);
                    try {
                        const evals = await evaluationService.getEvaluationsByCourses(courseIds);
                        setAllEvaluations(evals || []);
                    } catch (evalErr) {
                        console.error('Failed to load evaluations:', evalErr);
                    }
                }
            } catch (err) {
                console.error('[FacultyDashboard] fetchCourses ERROR:', err.name, err.message, err);
                if (err.name === 'AbortError' || err.message?.includes('Lock broken') || err.message?.includes('steal')) {
                    if (retries > 0) {
                        console.warn(`[FacultyDashboard] Lock collision! Retrying in 500ms... (${retries} retries left)`);
                        setTimeout(() => fetchCourses(retries - 1), 500);
                        return;
                    }
                    console.error('[FacultyDashboard] Lock collision — all retries exhausted!');
                }
                setError('Failed to load courses: ' + err.message);
            } finally {
                setLoading(false);
            }
        };
        fetchCourses();

        // Fetch pending invitations for TAs
        if (profile.role === 'ta' && user.email) {
            console.log('[FacultyDashboard] Fetching pending invitations for TA...');
            invitationService.getMyPendingInvitations(user.email)
                .then(data => {
                    console.log('[FacultyDashboard] Pending invitations loaded:', data?.length);
                    setPendingInvites(data || []);
                })
                .catch((err) => {
                    console.warn('[FacultyDashboard] Failed to load invitations:', err.message);
                });
        }
    }, [user, profile]);

    const handleAcceptInvite = async () => {
        if (!activeInvite) return;
        setActionLoading(true);
        try {
            await invitationService.acceptInvitation(activeInvite.id, user.id);
            setPendingInvites(prev => prev.filter(i => i.id !== activeInvite.id));
            // Refresh courses
            const data = await courseService.getCoursesByTA(user.id);
            setCourses(data || []);
            setShowAcceptModal(false);
            setActiveInvite(null);
        } catch (err) {
            setError('Failed to accept invitation: ' + err.message);
        } finally {
            setActionLoading(false);
        }
    };

    const handleDeclineInvite = async () => {
        if (!activeInvite) return;
        setActionLoading(true);
        try {
            await invitationService.declineInvitation(activeInvite.id);
            setPendingInvites(prev => prev.filter(i => i.id !== activeInvite.id));
            setShowDeclineModal(false);
            setActiveInvite(null);
        } catch (err) {
            setError('Failed to decline invitation: ' + err.message);
        } finally {
            setActionLoading(false);
        }
    };

    const filtered = courses.filter(c =>
        c.title?.toLowerCase().includes(search.toLowerCase()) ||
        c.code?.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div className="min-h-screen bg-background">
            <Header />

            {showCreateModal && (
                <CreateCourseModal
                    onClose={() => setShowCreateModal(false)}
                    onCreated={c => setCourses(prev => [c, ...prev])}
                    userId={user.id}
                />
            )}

            {showAcceptModal && (
                <AcceptInviteModal
                    invitation={activeInvite}
                    onConfirm={handleAcceptInvite}
                    onClose={() => { setShowAcceptModal(false); setActiveInvite(null); }}
                    loading={actionLoading}
                />
            )}

            {showDeclineModal && (
                <DeclineInviteModal
                    invitation={activeInvite}
                    onConfirm={handleDeclineInvite}
                    onClose={() => { setShowDeclineModal(false); setActiveInvite(null); }}
                    loading={actionLoading}
                />
            )}

            <main className="pt-16 transition-all duration-300">
                <div className="p-6 max-w-7xl mx-auto space-y-6">
                    <PageHeader
                        title="My Courses"
                        description={`Welcome back, ${profile?.name || ''}. Manage your active courses.`}
                        actions={
                            profile?.role === 'professor' && (
                                <button
                                    onClick={() => setShowCreateModal(true)}
                                    className="flex items-center px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors shadow-sm"
                                >
                                    <Icon name="Plus" size={16} className="mr-2" />
                                    <span>Create New Course</span>
                                </button>
                            )
                        }
                    />
                    {/* Pending Course Invitations for TAs */}
                    {pendingInvites.length > 0 && (
                        <div className="bg-primary-50 border border-primary-200 rounded-xl p-5">
                            <div className="flex items-center gap-2 mb-3">
                                <Icon name="Mail" size={20} className="text-primary" />
                                <h3 className="font-semibold text-text-primary">Course Invitations</h3>
                                <span className="px-2 py-0.5 bg-primary text-white text-xs rounded-full">{pendingInvites.length}</span>
                            </div>
                            <div className="space-y-2">
                                {pendingInvites.map(inv => (
                                    <div key={inv.id} className="bg-surface border border-border rounded-lg p-4 flex items-center justify-between">
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 rounded-full bg-primary-100 flex items-center justify-center text-primary-700">
                                                <Icon name="BookOpen" size={20} />
                                            </div>
                                            <div>
                                                <p className="font-medium text-text-primary">
                                                    {inv.courses?.code ? `${inv.courses.code} — ` : ''}{inv.courses?.title || 'Unknown Course'}
                                                </p>
                                                <p className="text-xs text-text-secondary">
                                                    Invited by {inv.courses?.profiles?.name || 'a professor'}
                                                </p>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <button onClick={() => { setActiveInvite(inv); setShowDeclineModal(true); }}
                                                className="px-3 py-1.5 border border-border text-text-secondary rounded-lg hover:bg-secondary-50 transition-colors text-sm">
                                                Decline
                                            </button>
                                            <button onClick={() => { setActiveInvite(inv); setShowAcceptModal(true); }}
                                                className="px-4 py-1.5 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors text-sm flex items-center gap-1">
                                                <Icon name="Check" size={14} />
                                                Accept
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    {/* Search */}
                    <div className="flex items-center space-x-4">
                        <div className="relative flex-1 max-w-md">
                            <Icon name="Search" className="absolute left-3 top-1/2 -translate-y-1/2 text-secondary-400" size={18} />
                            <input
                                type="text"
                                placeholder="Search by course name or code..."
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                className="w-full pl-10 pr-4 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent outline-none transition-all"
                            />
                        </div>
                    </div>

                    {/* States */}
                    {error && (
                        <div className="p-4 bg-error-50 border border-error-100 rounded-lg text-error text-sm">{error}</div>
                    )}

                    {loading ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                            {[1, 2, 3, 4].map(i => (
                                <div key={i} className="bg-surface border border-border rounded-xl p-6 animate-pulse">
                                    <div className="h-24 bg-secondary-100 rounded-lg mb-4" />
                                    <div className="h-4 bg-secondary-100 rounded w-3/4 mb-2" />
                                    <div className="h-3 bg-secondary-100 rounded w-1/2" />
                                </div>
                            ))}
                        </div>
                    ) : filtered.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                            {filtered.map((course, idx) => (
                                <div
                                    key={course.id}
                                    onClick={() => navigate(`/course/${course.id}`)}
                                    className="bg-surface border border-border rounded-xl overflow-hidden cursor-pointer hover:shadow-lg transition-all duration-200 hover:-translate-y-0.5 group"
                                >
                                    <div className={`h-24 bg-gradient-to-r ${GRADIENT_COLORS[idx % GRADIENT_COLORS.length]} flex items-center justify-center`}>
                                        <Icon name="BookOpen" size={36} className="text-white opacity-80" />
                                    </div>
                                    <div className="p-5">
                                        <div className="flex items-start justify-between mb-2">
                                            <span className="px-2 py-0.5 bg-primary-50 text-primary-700 text-xs font-semibold rounded">{course.code}</span>
                                            {course.semester && <span className="text-xs text-text-secondary">{course.semester}</span>}
                                        </div>
                                        <h3 className="font-semibold text-text-primary text-sm leading-tight mb-1 group-hover:text-primary transition-colors">
                                            {course.title}
                                        </h3>
                                        {course.description && (
                                            <p className="text-xs text-text-secondary line-clamp-2 mb-3">{course.description}</p>
                                        )}
                                        <div className="flex items-center text-xs text-primary font-medium">
                                            View Course <Icon name="ArrowRight" size={12} className="ml-1" />
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="text-center py-20 bg-surface rounded-xl border border-dashed border-border">
                            <div className="bg-secondary-50 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
                                <Icon name="BookOpen" size={32} className="text-secondary-400" />
                            </div>
                            <h3 className="text-lg font-medium text-text-primary">No courses found</h3>
                            <p className="text-secondary-500 mt-1">
                                {profile?.role === 'professor' ? 'Get started by creating your first course.' : 'You have not been assigned to any courses yet.'}
                            </p>
                            {profile?.role === 'professor' && (
                                <button onClick={() => setShowCreateModal(true)}
                                    className="mt-4 px-5 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors">
                                    + Create Course
                                </button>
                            )}
                        </div>
                    )}

                    {/* Pending Tasks Section - Kanban Style */}
                    <div className="pt-8 border-t border-border mt-8 space-y-6">
                        <PageHeader
                            title="My Pending Tasks"
                            description="Tasks assigned to you across all your courses."
                            actions={
                                <button
                                    onClick={() => navigate('/kanban-board')}
                                    className="px-4 py-2 text-sm bg-secondary-100 text-secondary-700 hover:bg-secondary-200 rounded-lg font-medium flex items-center gap-2 transition-colors"
                                >
                                    View Full Board <Icon name="ArrowRight" size={16} />
                                </button>
                            }
                        />

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                            {['Active', 'Grading', 'Published'].map(columnName => {
                                const columnTasks = allEvaluations.filter(t => t.status === columnName.toLowerCase());
                                return (
                                    <div key={columnName} className="bg-secondary-50/50 border border-border rounded-xl p-4 flex flex-col h-full min-h-[300px]">
                                        <div className="flex items-center justify-between mb-4">
                                            <div className="flex items-center gap-2">
                                                <h3 className="font-semibold text-text-primary text-sm">{columnName}</h3>
                                                <span className="px-2 py-0.5 bg-secondary-200 text-secondary-700 text-xs rounded-full font-medium">
                                                    {columnTasks.length}
                                                </span>
                                            </div>
                                        </div>
                                        <div className="space-y-3 flex-1">
                                            {columnTasks.map(task => (
                                                <div key={task.id}
                                                    className="bg-surface border border-border p-3.5 rounded-lg shadow-sm hover:shadow transition-shadow cursor-pointer hover:border-primary-300"
                                                    onClick={() => navigate(`/course/${task.course_id}`)}>
                                                    <div className="flex justify-between items-start mb-2">
                                                        <span className="text-xs font-semibold text-text-secondary bg-secondary-100 px-2 py-0.5 rounded">
                                                            {task.courses?.code || 'Course'}
                                                        </span>
                                                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wider ${task.status === 'active' ? 'text-primary-700 bg-primary-50' :
                                                                task.status === 'grading' ? 'text-warning-700 bg-warning-50' :
                                                                    'text-success-700 bg-success-50'
                                                            }`}>
                                                            {task.status}
                                                        </span>
                                                    </div>
                                                    <h4 className="text-sm font-medium text-text-primary mb-3">{task.name}</h4>
                                                    <div className="flex items-center justify-between mt-auto pt-2 border-t border-border border-dashed text-xs text-text-secondary">
                                                        <div className="flex items-center gap-1.5">
                                                            <Icon name="Calendar" size={12} />
                                                            <span>{new Date(task.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
                                                        </div>
                                                        {task.status === 'grading' && (
                                                            <div className="flex items-center gap-1 text-warning-600 font-medium">
                                                                <Icon name="Activity" size={12} />
                                                                <span>In Progress</span>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            ))}
                                            {columnTasks.length === 0 && (
                                                <div className="h-full flex flex-col items-center justify-center text-text-secondary text-sm border-2 border-dashed border-border rounded-lg p-6 bg-surface/50">
                                                    <Icon name="CheckCircle2" size={24} className="mb-2 text-secondary-300" />
                                                    All clear!
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                </div>
            </main >
        </div >
    );
};

export default FacultyDashboard;
