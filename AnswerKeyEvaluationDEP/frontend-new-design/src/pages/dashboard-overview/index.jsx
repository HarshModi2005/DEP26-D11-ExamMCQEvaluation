import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Header from '../../components/ui/Header';
import CommandPalette from '../../components/ui/CommandPalette';
import TaskDetailModal from '../../components/ui/TaskDetailModal';
import PageHeader from '../../components/ui/PageHeader';
import Icon from '../../components/AppIcon';
import MetricsCard from './components/MetricsCard';
import RecentActivity from './components/RecentActivity';
import QuickActions from './components/QuickActions';
import SprintProgress from './components/SprintProgress';

const DashboardOverview = () => {
    const navigate = useNavigate();
    const [selectedTaskId, setSelectedTaskId] = useState(null);
    const [isTaskModalOpen, setIsTaskModalOpen] = useState(false);

    // Mock data for dashboard metrics
    const dashboardMetrics = {
        activeSprintsCount: 3,
        totalTasks: 127,
        teamVelocity: 42,
        upcomingDeadlines: 8,
        completedThisWeek: 23,
        inProgressTasks: 31
    };

    // Mock data for recent activities
    const recentActivities = [
        {
            id: 1,
            type: 'task_created',
            user: {
                name: 'Sarah Chen',
                avatar: 'SC',
                isOnline: true
            },
            action: 'created task',
            target: 'Implement user authentication',
            project: 'TaskFlow Pro',
            timestamp: '2 minutes ago',
            priority: 'High'
        },
        {
            id: 2,
            type: 'task_completed',
            user: {
                name: 'Mike Rodriguez',
                avatar: 'MR',
                isOnline: true
            },
            action: 'completed task',
            target: 'Fix navigation bug',
            project: 'Mobile App',
            timestamp: '15 minutes ago',
            priority: 'Medium'
        },
        {
            id: 3,
            type: 'sprint_started',
            user: {
                name: 'Emily Johnson',
                avatar: 'EJ',
                isOnline: false
            },
            action: 'started sprint',
            target: 'Sprint 15 - Q1 Features',
            project: 'TaskFlow Pro',
            timestamp: '1 hour ago',
            priority: null
        },
        {
            id: 4,
            type: 'task_assigned',
            user: {
                name: 'David Kim',
                avatar: 'DK',
                isOnline: true
            },
            action: 'assigned task',
            target: 'Design system updates',
            project: 'Design System',
            timestamp: '2 hours ago',
            priority: 'Low'
        },
        {
            id: 5,
            type: 'comment_added',
            user: {
                name: 'Lisa Wang',
                avatar: 'LW',
                isOnline: true
            },
            action: 'commented on',
            target: 'API integration review',
            project: 'Backend Services',
            timestamp: '3 hours ago',
            priority: null
        }
    ];

    // Mock data for quick actions
    const quickActions = [
        {
            id: 'create-task',
            title: 'Create Task',
            description: 'Add a new task to your backlog',
            icon: 'Plus',
            shortcut: 'Ctrl+N',
            color: 'primary',
            action: () => console.log('Create task')
        },
        {
            id: 'start-sprint',
            title: 'Start Sprint',
            description: 'Begin a new development sprint',
            icon: 'Play',
            shortcut: 'Ctrl+S',
            color: 'success',
            action: () => navigate('/sprint-planning')
        },
        {
            id: 'invite-member',
            title: 'Invite Member',
            description: 'Add team members to workspace',
            icon: 'UserPlus',
            shortcut: 'Ctrl+I',
            color: 'accent',
            action: () => navigate('/team-management')
        },
        {
            id: 'view-analytics',
            title: 'View Analytics',
            description: 'Check team performance metrics',
            icon: 'BarChart3',
            shortcut: 'Ctrl+A',
            color: 'warning',
            action: () => navigate('/analytics-dashboard')
        }
    ];

    // Mock data for sprint progress
    const sprintData = {
        currentSprint: {
            name: 'Sprint 15 - Q1 Features',
            startDate: '2024-02-01',
            endDate: '2024-02-14',
            totalPoints: 55,
            completedPoints: 32,
            remainingDays: 6,
            burndownData: [
                { day: 1, ideal: 55, actual: 55 },
                { day: 2, ideal: 50, actual: 52 },
                { day: 3, ideal: 45, actual: 48 },
                { day: 4, ideal: 40, actual: 45 },
                { day: 5, ideal: 35, actual: 40 },
                { day: 6, ideal: 30, actual: 35 },
                { day: 7, ideal: 25, actual: 32 },
                { day: 8, ideal: 20, actual: 28 },
                { day: 9, ideal: 15, actual: 23 }
            ]
        },
        velocityData: [
            { sprint: 'Sprint 11', velocity: 38 },
            { sprint: 'Sprint 12', velocity: 42 },
            { sprint: 'Sprint 13', velocity: 45 },
            { sprint: 'Sprint 14', velocity: 41 },
            { sprint: 'Sprint 15', velocity: 32 }
        ]
    };

    const handleTaskClick = (taskId) => {
        setSelectedTaskId(taskId);
        setIsTaskModalOpen(true);
    };

    const handleCloseTaskModal = () => {
        setIsTaskModalOpen(false);
        setSelectedTaskId(null);
    };

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (event) => {
            if (event.ctrlKey || event.metaKey) {
                switch (event.key) {
                    case 'n':
                        event.preventDefault();
                        console.log('Create new task');
                        break;
                    case 's':
                        event.preventDefault();
                        navigate('/sprint-planning');
                        break;
                    case 'i':
                        event.preventDefault();
                        navigate('/team-management');
                        break;
                    case 'a':
                        event.preventDefault();
                        navigate('/analytics-dashboard');
                        break;
                    default:
                        break;
                }
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [navigate]);

    return (
        <div className="min-h-screen bg-background">
            <Header />
            <CommandPalette />

            {/* Main Content */}
            <main className="pt-16">
                <div className="p-6">
                    {/* Page Header */}
                    <PageHeader
                        actions={
                            <>
                                <button
                                    onClick={() => navigate('/kanban-board')}
                                    className="px-4 py-2 bg-secondary-100 text-secondary-700 rounded-lg hover:bg-secondary-200 transition-colors duration-200 flex items-center space-x-2"
                                >
                                    <Icon name="Kanban" size={16} />
                                    <span>View Boards</span>
                                </button>
                                <button
                                    onClick={() => navigate('/sprint-planning')}
                                    className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors duration-200 flex items-center space-x-2"
                                >
                                    <Icon name="Calendar" size={16} />
                                    <span>Plan Sprint</span>
                                </button>
                            </>
                        }
                    />

                    {/* Metrics Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                        <MetricsCard
                            title="Active Sprints"
                            value={dashboardMetrics.activeSprintsCount}
                            icon="Calendar"
                            color="primary"
                            trend="+2 from last month"
                            onClick={() => navigate('/sprint-planning')}
                        />
                        <MetricsCard
                            title="Total Tasks"
                            value={dashboardMetrics.totalTasks}
                            icon="Square"
                            color="secondary"
                            trend="+15 this week"
                            onClick={() => navigate('/kanban-board')}
                        />
                        <MetricsCard
                            title="Team Velocity"
                            value={dashboardMetrics.teamVelocity}
                            icon="TrendingUp"
                            color="success"
                            trend="+8% from last sprint"
                            onClick={() => navigate('/analytics-dashboard')}
                        />
                        <MetricsCard
                            title="Upcoming Deadlines"
                            value={dashboardMetrics.upcomingDeadlines}
                            icon="Clock"
                            color="warning"
                            trend="3 due this week"
                            onClick={() => navigate('/kanban-board')}
                        />
                    </div>

                    {/* Main Dashboard Grid */}
                    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                        {/* Recent Activity - Left Column */}
                        <div className="lg:col-span-4">
                            <RecentActivity
                                activities={recentActivities}
                                onTaskClick={handleTaskClick}
                            />
                        </div>

                        {/* Quick Actions - Center Column */}
                        <div className="lg:col-span-4">
                            <QuickActions
                                actions={quickActions}
                            />
                        </div>

                        {/* Sprint Progress - Right Column */}
                        <div className="lg:col-span-4">
                            <SprintProgress
                                sprintData={sprintData}
                                onViewDetails={() => navigate('/sprint-planning')}
                            />
                        </div>
                    </div>

                    {/* Additional Stats Row */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-8">
                        {/* Team Performance Summary */}
                        <div className="bg-surface border border-border rounded-lg p-6">
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-semibold text-text-primary">Team Performance</h3>
                                <button
                                    onClick={() => navigate('/analytics-dashboard')}
                                    className="text-primary hover:text-primary-700 transition-colors duration-200"
                                >
                                    <Icon name="ExternalLink" size={16} />
                                </button>
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div className="text-center p-4 bg-success-50 rounded-lg">
                                    <p className="text-2xl font-bold text-success-600">{dashboardMetrics.completedThisWeek}</p>
                                    <p className="text-sm text-text-secondary">Completed This Week</p>
                                </div>
                                <div className="text-center p-4 bg-primary-50 rounded-lg">
                                    <p className="text-2xl font-bold text-primary">{dashboardMetrics.inProgressTasks}</p>
                                    <p className="text-sm text-text-secondary">In Progress</p>
                                </div>
                            </div>
                        </div>

                        {/* Workspace Overview */}
                        <div className="bg-surface border border-border rounded-lg p-6">
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-semibold text-text-primary">Workspace Overview</h3>
                                <button
                                    onClick={() => navigate('/team-management')}
                                    className="text-primary hover:text-primary-700 transition-colors duration-200"
                                >
                                    <Icon name="Settings" size={16} />
                                </button>
                            </div>
                            <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                    <span className="text-text-secondary">Active Projects</span>
                                    <span className="font-medium text-text-primary">5</span>
                                </div>
                                <div className="flex items-center justify-between">
                                    <span className="text-text-secondary">Team Members</span>
                                    <span className="font-medium text-text-primary">12</span>
                                </div>
                                <div className="flex items-center justify-between">
                                    <span className="text-text-secondary">Workspace Storage</span>
                                    <span className="font-medium text-text-primary">2.4 GB / 10 GB</span>
                                </div>
                                <div className="w-full bg-secondary-200 rounded-full h-2 mt-2">
                                    <div className="bg-primary h-2 rounded-full" style={{ width: '24%' }}></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </main>

            {/* Task Detail Modal */}
            <TaskDetailModal
                isOpen={isTaskModalOpen}
                onClose={handleCloseTaskModal}
                taskId={selectedTaskId}
            />
        </div>
    );
};

export default DashboardOverview;