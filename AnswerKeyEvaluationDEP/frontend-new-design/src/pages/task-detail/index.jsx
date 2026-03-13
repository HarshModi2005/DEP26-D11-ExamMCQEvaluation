import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import Header from '../../components/ui/Header';
import CommandPalette from '../../components/ui/CommandPalette';
import PageHeader from '../../components/ui/PageHeader';
import Icon from '../../components/AppIcon';
import TaskDetailHeader from './components/TaskDetailHeader';
import TaskDetailContent from './components/TaskDetailContent';
import TaskDetailSidebar from './components/TaskDetailSidebar';
import TaskDetailComments from './components/TaskDetailComments';
import TaskDetailAttachments from './components/TaskDetailAttachments';
import TaskDetailDependencies from './components/TaskDetailDependencies';


const TaskDetail = () => {
    const navigate = useNavigate();
    const location = useLocation();
    const [activeTab, setActiveTab] = useState('description');
    const [isEditing, setIsEditing] = useState(false);
    const [task, setTask] = useState(null);
    const [loading, setLoading] = useState(true);

    // Extract task ID from URL query parameters
    const queryParams = new URLSearchParams(location.search);
    const taskId = queryParams.get('id') || 'TASK-123';

    useEffect(() => {
        // Simulate API call to fetch task details
        const fetchTaskDetails = async () => {
            setLoading(true);
            try {
                // In a real app, this would be an API call
                // For now, we'll use mock data
                setTimeout(() => {
                    setTask(mockTaskData);
                    setLoading(false);
                }, 500);
            } catch (error) {
                console.error('Error fetching task details:', error);
                setLoading(false);
            }
        };

        fetchTaskDetails();
    }, [taskId]);

    const handleClose = () => {
        navigate('/kanban-board');
    };

    const handleSave = () => {
        // In a real app, this would save changes to the API
        setIsEditing(false);
        // Show success toast or notification
    };

    const handleStatusChange = (newStatus) => {
        setTask(prev => ({ ...prev, status: newStatus }));
    };

    const handlePriorityChange = (newPriority) => {
        setTask(prev => ({ ...prev, priority: newPriority }));
    };

    const handleAssigneeChange = (newAssignee) => {
        setTask(prev => ({ ...prev, assignee: newAssignee }));
    };

    const handleTitleChange = (newTitle) => {
        setTask(prev => ({ ...prev, title: newTitle }));
    };

    const handleDescriptionChange = (newDescription) => {
        setTask(prev => ({ ...prev, description: newDescription }));
    };

    const handleAddComment = (comment) => {
        const newComment = {
            id: Date.now(),
            author: 'John Doe',
            avatar: 'JD',
            content: comment,
            timestamp: new Date().toLocaleString(),
            isNew: true
        };

        setTask(prev => ({
            ...prev,
            comments: [newComment, ...prev.comments]
        }));
    };

    const handleAddAttachment = (attachment) => {
        const newAttachment = {
            id: Date.now(),
            name: attachment.name,
            size: `${Math.round(attachment.size / 1024)} KB`,
            type: attachment.type.startsWith('image/') ? 'image' : 'document',
            url: URL.createObjectURL(attachment)
        };

        setTask(prev => ({
            ...prev,
            attachments: [newAttachment, ...prev.attachments]
        }));
    };

    // Mock task data
    const mockTaskData = {
        id: taskId,
        title: "Implement user authentication system",
        description: `# Authentication System Implementation

## Overview
Create a secure authentication system with JWT tokens, password hashing, and session management. Include login, logout, and password reset functionality.

## Requirements
- Implement JWT-based authentication
- Add secure password hashing with bcrypt
- Create session management with refresh tokens
- Build password reset flow with email verification
- Add 2FA support with authenticator apps

## Technical Specifications
The authentication system should follow OAuth 2.0 standards and implement proper CSRF protection.

\`\`\`javascript
// Example JWT implementation
const jwt = require('jsonwebtoken');
const token = jwt.sign({ userId: user.id }, process.env.JWT_SECRET, { expiresIn: '1h' });
\`\`\`

## Design References
See the attached Figma designs for UI implementation details.`,
        status: "In Progress",
        priority: "High",
        assignee: {
            id: 1,
            name: "John Doe",
            avatar: "JD",
            email: "john.doe@company.com"
        },
        reporter: {
            id: 2,
            name: "Jane Smith",
            avatar: "JS",
            email: "jane.smith@company.com"
        },
        project: "TaskFlow Pro",
        sprint: "Sprint 12",
        storyPoints: 8,
        labels: ["Backend", "Security", "API"],
        dueDate: "2024-02-15",
        createdAt: "2024-01-28",
        updatedAt: "2024-02-01",
        comments: [
            {
                id: 1,
                author: "Jane Smith",
                avatar: "JS",
                content: "Please make sure to implement proper password validation according to our security guidelines.",
                timestamp: "2024-02-01 10:30 AM"
            },
            {
                id: 2,
                author: "John Doe",
                avatar: "JD",
                content: "Working on the JWT implementation. Should have the basic structure ready by tomorrow.",
                timestamp: "2024-02-01 2:15 PM"
            },
            {
                id: 3,
                author: "Michael Chen",
                avatar: "MC",
                content: "Don\'t forget to add rate limiting to prevent brute force attacks.",
                timestamp: "2024-02-02 9:45 AM"
            }
        ],
        attachments: [
            { id: 1, name: "auth-flow-diagram.png", size: "245 KB", type: "image", url: "https://picsum.photos/800/600" },
            { id: 2, name: "security-requirements.pdf", size: "1.2 MB", type: "document" },
            { id: 3, name: "api-documentation.md", size: "78 KB", type: "document" }
        ],
        timeTracking: {
            estimated: "32h",
            logged: "18h",
            remaining: "14h"
        },
        dependencies: [
            { id: "TASK-120", title: "Set up database schema", status: "Done", type: "blocks" },
            { id: "TASK-125", title: "Implement user profile page", status: "To Do", type: "blocked by" }
        ],
        activity: [
            { id: 1, type: "status_change", user: "John Doe", avatar: "JD", from: "To Do", to: "In Progress", timestamp: "2024-02-01 09:15 AM" },
            { id: 2, type: "comment_added", user: "Jane Smith", avatar: "JS", timestamp: "2024-02-01 10:30 AM" },
            { id: 3, type: "attachment_added", user: "John Doe", avatar: "JD", attachment: "auth-flow-diagram.png", timestamp: "2024-02-01 11:45 AM" },
            { id: 4, type: "description_updated", user: "John Doe", avatar: "JD", timestamp: "2024-02-01 1:30 PM" },
            { id: 5, type: "comment_added", user: "John Doe", avatar: "JD", timestamp: "2024-02-01 2:15 PM" },
            { id: 6, type: "points_updated", user: "Jane Smith", avatar: "JS", from: 5, to: 8, timestamp: "2024-02-01 4:20 PM" },
            { id: 7, type: "comment_added", user: "Michael Chen", avatar: "MC", timestamp: "2024-02-02 9:45 AM" }
        ],
        figmaEmbed: "https://www.figma.com/embed?embed_host=share&url=https%3A%2F%2Fwww.figma.com%2Ffile%2FexampleID%2FAuthentication-Flows",
        loomVideo: "https://www.loom.com/embed/exampleLoomID"
    };

    const mockTask = mockTaskData;

    if (loading) {
        return (
            <div className="min-h-screen bg-background">
                <Header />
                <div className="flex">
                    <div className="flex-1 pt-16">
                        <div className="flex items-center justify-center h-screen">
                            <div className="flex flex-col items-center">
                                <Icon name="Loader" size={48} className="animate-spin text-primary mb-4" />
                                <p className="text-text-secondary">Loading task details...</p>
                            </div>
                        </div>
                    </div>
                </div>
                <CommandPalette />
            </div>
        );
    }

    if (!task) {
        return (
            <div className="min-h-screen bg-background">
                <Header />
                <div className="flex">
                    <div className="flex-1 pt-16">
                        <div className="flex items-center justify-center h-screen">
                            <div className="text-center">
                                <Icon name="AlertTriangle" size={48} className="text-warning mx-auto mb-4" />
                                <h2 className="text-xl font-semibold text-text-primary mb-2">Task Not Found</h2>
                                <p className="text-text-secondary mb-6">The task you're looking for doesn't exist or has been moved.</p>
                                <button
                                    onClick={() => navigate('/kanban-board')}
                                    className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors duration-200"
                                >
                                    Return to Kanban Board
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
                <CommandPalette />
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-background">
            <Header />
            <div className="flex">
                <div className="flex-1 pt-16">
                    <div className="p-6">
                        {/* Page Header */}
                        <PageHeader
                            title={`Task Details - ${mockTask?.title || 'Loading...'}`}
                            description="View and manage task information"
                            actions={
                                <>
                                    <button className="px-4 py-2 bg-secondary-100 text-secondary-700 rounded-lg hover:bg-secondary-200 transition-colors duration-200 flex items-center space-x-2">
                                        <Icon name="Copy" size={16} />
                                        <span>Duplicate</span>
                                    </button>
                                    <button className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors duration-200 flex items-center space-x-2">
                                        <Icon name="Edit" size={16} />
                                        <span>Edit Task</span>
                                    </button>
                                </>
                            }
                        />
                        <div className="max-w-7xl mx-auto">
                            <div className="bg-surface border border-border rounded-lg shadow-sm overflow-hidden">
                                {/* Task Detail Header */}
                                <TaskDetailHeader
                                    task={task}
                                    isEditing={isEditing}
                                    setIsEditing={setIsEditing}
                                    onClose={handleClose}
                                    onSave={handleSave}
                                    onTitleChange={handleTitleChange}
                                    onStatusChange={handleStatusChange}
                                />

                                {/* Task Detail Content */}
                                <div className="flex flex-col lg:flex-row">
                                    {/* Main Content Area (70%) */}
                                    <div className="w-full lg:w-8/12 p-6 border-r border-border">
                                        {/* Tabs */}
                                        <div className="border-b border-border mb-6">
                                            <nav className="flex space-x-8">
                                                {['description', 'comments', 'attachments', 'dependencies'].map((tab) => (
                                                    <button
                                                        key={tab}
                                                        onClick={() => setActiveTab(tab)}
                                                        className={`py-2 px-1 border-b-2 font-medium text-sm transition-colors duration-200 ${activeTab === tab
                                                            ? 'border-primary text-primary' : 'border-transparent text-text-secondary hover:text-text-primary'
                                                            }`}
                                                    >
                                                        {tab.charAt(0).toUpperCase() + tab.slice(1)}
                                                    </button>
                                                ))}
                                            </nav>
                                        </div>

                                        {/* Tab Content */}
                                        {activeTab === 'description' && (
                                            <TaskDetailContent
                                                task={task}
                                                isEditing={isEditing}
                                                onDescriptionChange={handleDescriptionChange}
                                            />
                                        )}

                                        {activeTab === 'comments' && (
                                            <TaskDetailComments
                                                comments={task.comments}
                                                onAddComment={handleAddComment}
                                            />
                                        )}

                                        {activeTab === 'attachments' && (
                                            <TaskDetailAttachments
                                                attachments={task.attachments}
                                                onAddAttachment={handleAddAttachment}
                                            />
                                        )}

                                        {activeTab === 'dependencies' && (
                                            <TaskDetailDependencies
                                                dependencies={task.dependencies}
                                                navigate={navigate}
                                            />
                                        )}
                                    </div>

                                    {/* Sidebar (30%) */}
                                    <div className="w-full lg:w-4/12 p-6 bg-secondary-50">
                                        <TaskDetailSidebar
                                            task={task}
                                            onPriorityChange={handlePriorityChange}
                                            onAssigneeChange={handleAssigneeChange}
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <CommandPalette />
        </div>
    );
};

export default TaskDetail;