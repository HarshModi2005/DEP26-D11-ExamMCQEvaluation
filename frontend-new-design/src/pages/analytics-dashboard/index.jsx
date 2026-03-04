import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Header from '../../components/ui/Header';
import Sidebar from '../../components/ui/Sidebar';
import PageHeader from '../../components/ui/PageHeader';
import Icon from '../../components/AppIcon';
import { useAuth } from '../../context/AuthContext';
import { courseService } from '../../services/courseService';
import { evaluationService } from '../../services/evaluationService';
import { resultsService } from '../../services/resultsService';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const AnalyticsDashboard = () => {
    const navigate = useNavigate();
    const { user, profile } = useAuth();

    const [courses, setCourses] = useState([]);
    const [selectedCourse, setSelectedCourse] = useState(null);
    const [evaluations, setEvaluations] = useState([]);
    const [selectedEval, setSelectedEval] = useState(null);
    const [analytics, setAnalytics] = useState(null);
    const [loading, setLoading] = useState(true);
    const [evalLoading, setEvalLoading] = useState(false);
    const [analyticsLoading, setAnalyticsLoading] = useState(false);

    // Step 1: Load courses
    useEffect(() => {
        if (!user || !profile) return;
        const load = async () => {
            setLoading(true);
            try {
                let data;
                if (profile.role === 'professor') {
                    data = await courseService.getCoursesByProfessor(user.id);
                } else {
                    data = await courseService.getCoursesByTA(user.id);
                }
                setCourses(data || []);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        load();
    }, [user, profile]);

    // Step 2: When course selected, load evaluations
    useEffect(() => {
        if (!selectedCourse) return;
        const loadEvals = async () => {
            setEvalLoading(true);
            setEvaluations([]);
            setSelectedEval(null);
            setAnalytics(null);
            try {
                const data = await evaluationService.getEvaluationsByCourse(selectedCourse.id);
                setEvaluations(data || []);
            } catch (err) {
                console.error(err);
            } finally {
                setEvalLoading(false);
            }
        };
        loadEvals();
    }, [selectedCourse]);

    // Step 3: When eval selected, load analytics
    useEffect(() => {
        if (!selectedEval) return;
        const loadAnalytics = async () => {
            setAnalyticsLoading(true);
            setAnalytics(null);
            try {
                const data = await resultsService.getAnalytics(selectedEval.id);
                setAnalytics(data);
            } catch (err) {
                console.error(err);
            } finally {
                setAnalyticsLoading(false);
            }
        };
        loadAnalytics();
    }, [selectedEval]);

    return (
        <div className="min-h-screen bg-background">
            <Header />
            <Sidebar />
            <main className="lg:ml-64 pt-16 transition-all duration-300">
                <div className="p-6 max-w-7xl mx-auto space-y-6">
                    <PageHeader
                        title="Analytics"
                        description="View evaluation-wise performance analytics for your courses"
                    />

                    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
                        {/* Left column - Course & Eval selectors */}
                        <div className="space-y-4">
                            {/* Courses */}
                            <div className="bg-surface border border-border rounded-xl overflow-hidden">
                                <div className="p-3 border-b border-border bg-secondary-50">
                                    <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Courses</p>
                                </div>
                                {loading ? (
                                    <div className="p-4 space-y-2">
                                        {[1, 2, 3].map(i => <div key={i} className="h-10 bg-secondary-100 rounded animate-pulse" />)}
                                    </div>
                                ) : courses.length === 0 ? (
                                    <div className="p-4 text-center text-sm text-text-secondary">No courses found.</div>
                                ) : (
                                    <div className="divide-y divide-border">
                                        {courses.map(c => (
                                            <button key={c.id} onClick={() => setSelectedCourse(c)}
                                                className={`w-full text-left px-4 py-3 transition-colors ${selectedCourse?.id === c.id ? 'bg-primary-50 text-primary' : 'hover:bg-secondary-50 text-text-primary'}`}>
                                                <p className="text-sm font-medium">{c.code}</p>
                                                <p className={`text-xs truncate ${selectedCourse?.id === c.id ? 'text-primary-400' : 'text-text-secondary'}`}>{c.title}</p>
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Evaluations */}
                            {selectedCourse && (
                                <div className="bg-surface border border-border rounded-xl overflow-hidden">
                                    <div className="p-3 border-b border-border bg-secondary-50">
                                        <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Evaluations</p>
                                    </div>
                                    {evalLoading ? (
                                        <div className="p-4 space-y-2">
                                            {[1, 2].map(i => <div key={i} className="h-10 bg-secondary-100 rounded animate-pulse" />)}
                                        </div>
                                    ) : evaluations.length === 0 ? (
                                        <div className="p-4 text-center text-sm text-text-secondary">No evaluations yet.</div>
                                    ) : (
                                        <div className="divide-y divide-border">
                                            {evaluations.map(ev => (
                                                <button key={ev.id} onClick={() => setSelectedEval(ev)}
                                                    className={`w-full text-left px-4 py-3 transition-colors ${selectedEval?.id === ev.id ? 'bg-primary-50 text-primary' : 'hover:bg-secondary-50 text-text-primary'}`}>
                                                    <p className="text-sm font-medium">{ev.name}</p>
                                                    <p className={`text-xs capitalize ${selectedEval?.id === ev.id ? 'text-primary-400' : 'text-text-secondary'}`}>{ev.status}</p>
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Right column - Analytics view */}
                        <div className="lg:col-span-3">
                            {!selectedCourse && (
                                <div className="flex flex-col items-center justify-center h-80 bg-surface border border-dashed border-border rounded-xl text-text-secondary">
                                    <Icon name="BarChart3" size={40} className="mb-3 text-secondary-300" />
                                    <p className="font-medium">Select a course to view analytics</p>
                                    <p className="text-sm mt-1">Then select an evaluation to see detailed data</p>
                                </div>
                            )}

                            {selectedCourse && !selectedEval && (
                                <div className="flex flex-col items-center justify-center h-80 bg-surface border border-dashed border-border rounded-xl text-text-secondary">
                                    <Icon name="FileText" size={40} className="mb-3 text-secondary-300" />
                                    <p className="font-medium">{selectedCourse.title}</p>
                                    <p className="text-sm mt-1">Select an evaluation from the left panel</p>
                                </div>
                            )}

                            {selectedEval && analyticsLoading && (
                                <div className="flex items-center justify-center h-80 bg-surface border border-border rounded-xl">
                                    <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
                                </div>
                            )}

                            {selectedEval && !analyticsLoading && !analytics && (
                                <div className="flex flex-col items-center justify-center h-80 bg-surface border border-dashed border-border rounded-xl text-text-secondary">
                                    <Icon name="BarChart3" size={40} className="mb-3 text-secondary-300" />
                                    <p className="font-medium">No results yet for "{selectedEval.name}"</p>
                                    <p className="text-sm mt-1">Run the OCR pipeline to grade answer sheets first.</p>
                                    <button onClick={() => navigate(`/evaluate/${selectedEval.id}`)}
                                        className="mt-4 px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary-700 transition-colors flex items-center gap-2">
                                        <Icon name="Play" size={14} />Go to Evaluate Page
                                    </button>
                                </div>
                            )}

                            {selectedEval && !analyticsLoading && analytics && (
                                <div className="space-y-5">
                                    {/* Header */}
                                    <div className="bg-surface border border-border rounded-xl p-5">
                                        <div className="flex items-start justify-between mb-4">
                                            <div>
                                                <h2 className="text-xl font-bold text-text-primary">{selectedEval.name}</h2>
                                                <p className="text-text-secondary text-sm mt-0.5">
                                                    {selectedCourse.code} — {selectedCourse.title}
                                                </p>
                                            </div>
                                            <button onClick={() => navigate(`/evaluate/${selectedEval.id}`)}
                                                className="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-secondary-50 transition-colors flex items-center gap-1.5 text-text-secondary">
                                                <Icon name="ExternalLink" size={14} />Open Evaluation
                                            </button>
                                        </div>

                                        {/* Key metrics */}
                                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                            {[
                                                { label: 'Average', value: `${analytics.averageScore}/${analytics.maxScore}`, color: 'bg-blue-50 text-blue-700' },
                                                { label: 'Median', value: analytics.medianScore, color: 'bg-purple-50 text-purple-700' },
                                                { label: 'Highest', value: analytics.highestScore, color: 'bg-success-50 text-success-700' },
                                                { label: 'Graded', value: `${analytics.gradedCount}/${analytics.totalStudents}`, color: 'bg-warning-50 text-warning-700' },
                                            ].map(m => (
                                                <div key={m.label} className={`rounded-lg p-3 ${m.color}`}>
                                                    <p className="text-2xl font-bold">{m.value}</p>
                                                    <p className="text-xs font-medium">{m.label}</p>
                                                </div>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Charts row */}
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                                        {/* Score distribution */}
                                        <div className="bg-surface border border-border rounded-xl p-5">
                                            <h3 className="font-semibold text-text-primary mb-4">Score Distribution</h3>
                                            <ResponsiveContainer width="100%" height={200}>
                                                <BarChart data={analytics.distribution}>
                                                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                                                    <XAxis dataKey="range" tick={{ fontSize: 11 }} />
                                                    <YAxis tick={{ fontSize: 11 }} />
                                                    <Tooltip />
                                                    <Bar dataKey="count" fill="var(--color-primary)" radius={[4, 4, 0, 0]} name="Students" />
                                                </BarChart>
                                            </ResponsiveContainer>
                                        </div>

                                        {/* Question analysis */}
                                        <div className="bg-surface border border-border rounded-xl p-5 space-y-4">
                                            <h3 className="font-semibold text-text-primary">Question Analysis</h3>
                                            {analytics.hardestQuestion && (
                                                <div className="p-4 bg-error-50 border border-error-100 rounded-lg">
                                                    <p className="text-xs font-semibold text-error-600 uppercase tracking-wider mb-1">Most Difficult</p>
                                                    <p className="font-semibold text-text-primary">{analytics.hardestQuestion.question}</p>
                                                    <p className="text-sm text-text-secondary">{analytics.hardestQuestion.correctRate}% students got it right</p>
                                                </div>
                                            )}
                                            {analytics.easiestQuestion && (
                                                <div className="p-4 bg-success-50 border border-success-100 rounded-lg">
                                                    <p className="text-xs font-semibold text-success-600 uppercase tracking-wider mb-1">Easiest</p>
                                                    <p className="font-semibold text-text-primary">{analytics.easiestQuestion.question}</p>
                                                    <p className="text-sm text-text-secondary">{analytics.easiestQuestion.correctRate}% students got it right</p>
                                                </div>
                                            )}
                                            {!analytics.hardestQuestion && !analytics.easiestQuestion && (
                                                <p className="text-sm text-text-secondary">Question-level data not available. Ensure OCR results include answer details.</p>
                                            )}
                                        </div>
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

export default AnalyticsDashboard;