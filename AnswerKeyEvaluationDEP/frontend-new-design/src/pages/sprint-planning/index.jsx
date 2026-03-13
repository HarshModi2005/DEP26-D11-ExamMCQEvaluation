import React, { useState } from 'react';
import Header from '../../components/ui/Header';
import PageHeader from '../../components/ui/PageHeader';
import Icon from '../../components/AppIcon';

const GradingDutyAllocation = () => {
    // Mock data for exams and TAs
    const exams = [
        { id: 'CS306 Quiz 1', name: 'CS306 Quiz 1' },
        { id: 'CS306 Midsem', name: 'CS306 Midsem' },
    ];

    const teachingAssistants = [
        { id: 'ta1', name: 'Michael Rodriguez', role: 'Head TA', avatar: 'MR' },
        { id: 'ta2', name: 'David Kim', role: 'TA', avatar: 'DK' },
        { id: 'ta3', name: 'Lisa Martinez', role: 'Junior TA', avatar: 'LM' },
    ];

    const questions = [
        { id: 'q1', label: 'Q1: Arrays & Lists', points: 10 },
        { id: 'q2', label: 'Q2: Tree Traversal', points: 15 },
        { id: 'q3', label: 'Q3: Graph Algorithms', points: 20 },
        { id: 'q4', label: 'Q4: Dynamic Programming', points: 25 },
        { id: 'q5', label: 'Q5: System Design', points: 30 },
    ];

    const [selectedExam, setSelectedExam] = useState(exams[0].id);
    const [allocations, setAllocations] = useState({}); // { questionId: taId }

    const handleAssign = (questionId, taId) => {
        setAllocations(prev => ({
            ...prev,
            [questionId]: taId
        }));
    };

    return (
        <div className="min-h-screen bg-background">
            <Header />

            <main className="pt-16">
                <div className="p-6 max-w-7xl mx-auto space-y-6">
                    <PageHeader
                        title="Grading Duty Allocation"
                        description="Assign grading responsibilities to Teaching Assistants for specific questions."
                        actions={
                            <div className="flex items-center space-x-3">
                                <span className="text-sm font-medium text-text-secondary">Select Exam:</span>
                                <select
                                    value={selectedExam}
                                    onChange={(e) => setSelectedExam(e.target.value)}
                                    className="px-3 py-2 border border-border rounded-lg bg-surface text-text-primary focus:ring-2 focus:ring-primary"
                                >
                                    {exams.map(exam => (
                                        <option key={exam.id} value={exam.id}>{exam.name}</option>
                                    ))}
                                </select>
                            </div>
                        }
                    />

                    <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden">
                        <div className="grid grid-cols-12 gap-0 divide-x divide-border bg-secondary-50 border-b border-border">
                            <div className="col-span-5 p-4 font-medium text-text-secondary text-sm uppercase tracking-wider">Question / Section</div>
                            <div className="col-span-2 p-4 font-medium text-text-secondary text-sm uppercase tracking-wider text-center">Points</div>
                            <div className="col-span-5 p-4 font-medium text-text-secondary text-sm uppercase tracking-wider">Assigned TA</div>
                        </div>

                        <div className="divide-y divide-border">
                            {questions.map((question) => (
                                <div key={question.id} className="grid grid-cols-12 gap-0 divide-x divide-border items-center hover:bg-secondary-50 transition-colors">
                                    <div className="col-span-5 p-4">
                                        <div className="flex items-center">
                                            <div className="w-8 h-8 rounded-lg bg-primary-100 flex items-center justify-center text-primary-700 mr-3">
                                                <Icon name="HelpCircle" size={18} />
                                            </div>
                                            <span className="font-medium text-text-primary">{question.label}</span>
                                        </div>
                                    </div>
                                    <div className="col-span-2 p-4 text-center text-text-secondary font-medium">
                                        {question.points}
                                    </div>
                                    <div className="col-span-5 p-4">
                                        <div className="relative">
                                            <select
                                                value={allocations[question.id] || ''}
                                                onChange={(e) => handleAssign(question.id, e.target.value)}
                                                className={`w-full appearance-none pl-10 pr-8 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary transition-all cursor-pointer ${allocations[question.id] ? 'bg-primary-50 border-primary-200 text-primary-900' : 'bg-surface border-border text-text-secondary'}`}
                                            >
                                                <option value="" disabled>Unassigned</option>
                                                {teachingAssistants.map(ta => (
                                                    <option key={ta.id} value={ta.id}>{ta.name} ({ta.role})</option>
                                                ))}
                                            </select>
                                            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                                <Icon name="User" size={16} className={`${allocations[question.id] ? 'text-primary-500' : 'text-text-secondary'}`} />
                                            </div>
                                            <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
                                                <Icon name="ChevronDown" size={16} className={`${allocations[question.id] ? 'text-primary-500' : 'text-text-secondary'}`} />
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className="p-4 bg-secondary-50 border-t border-border flex justify-end">
                            <button className="px-6 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors shadow-sm flex items-center font-medium">
                                <Icon name="Save" size={16} className="mr-2" />
                                Save Allocations
                            </button>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    );
};

export default GradingDutyAllocation;