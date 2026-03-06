import React, { useEffect, useRef } from 'react';
import Icon from '../AppIcon';

const TaskDetailModal = ({ isOpen, onClose, taskId }) => {
    const modalRef = useRef(null);

    // Mock task details (would be fetched by ID in a real app)
    const task = {
        id: taskId,
        title: "Implement user authentication",
        description: "Add login and registration functionality using JWT tokens and secure password hashing. Include social login options (Google, GitHub) and email verification flow.",
        status: "In Progress",
        priority: "High",
        assignee: {
            name: "Sarah Chen",
            avatar: "SC"
        },
        reporter: {
            name: "Admin User",
            avatar: "AU"
        },
        dueDate: "Feb 28, 2024",
        createdAt: "Feb 15, 2024",
        tags: ["Backend", "Security", "Auth"],
        comments: [
            {
                id: 1,
                user: "David Kim",
                content: "I've started working on the JWT implementation. Should be ready for review by tomorrow.",
                timestamp: "2 hours ago"
            },
            {
                id: 2,
                user: "Sarah Chen",
                content: "Great! Let me know if you need help with the Google OAuth setup.",
                timestamp: "1 hour ago"
            }
        ]
    };

    useEffect(() => {
        if (isOpen) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = 'auto';
        }
        return () => {
            document.body.style.overflow = 'auto';
        };
    }, [isOpen]);

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (modalRef.current && !modalRef.current.contains(event.target)) {
                onClose();
            }
        };

        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
        }

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [isOpen, onClose]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-200 flex items-center justify-center p-4">
            <div
                ref={modalRef}
                className="w-full max-w-4xl bg-surface rounded-xl shadow-2xl border border-border h-[85vh] flex flex-col overflow-hidden"
            >
                {/* Header */}
                <div className="flex items-center justify-between p-6 border-b border-border bg-secondary-50">
                    <div className="flex items-center space-x-3">
                        <span className="text-secondary-500 font-mono text-sm">TASK-{taskId}</span>
                        <div className="h-4 w-px bg-border"></div>
                        <div className="flex items-center space-x-2">
                            <span className="px-2 py-0.5 bg-primary-100 text-primary-700 rounded text-xs font-medium">
                                {task.status}
                            </span>
                            <span className="px-2 py-0.5 bg-error-100 text-error-700 rounded text-xs font-medium">
                                {task.priority}
                            </span>
                        </div>
                    </div>
                    <div className="flex items-center space-x-2">
                        <button className="p-2 text-secondary-500 hover:text-text-primary hover:bg-secondary-200 rounded-lg transition-colors">
                            <Icon name="Share2" size={18} />
                        </button>
                        <button className="p-2 text-secondary-500 hover:text-text-primary hover:bg-secondary-200 rounded-lg transition-colors">
                            <Icon name="MoreHorizontal" size={18} />
                        </button>
                        <button
                            onClick={onClose}
                            className="p-2 text-secondary-500 hover:text-text-primary hover:bg-secondary-200 rounded-lg transition-colors"
                        >
                            <Icon name="X" size={20} />
                        </button>
                    </div>
                </div>

                {/* Body - Split View */}
                <div className="flex-1 flex overflow-hidden">
                    {/* Main Content (Left) */}
                    <div className="flex-1 overflow-y-auto p-8 border-r border-border">
                        <h2 className="text-2xl font-bold text-text-primary mb-6">{task.title}</h2>

                        <div className="mb-8">
                            <h3 className="text-sm font-bold text-text-secondary uppercase mb-3">Description</h3>
                            <div className="prose text-text-primary text-sm leading-relaxed">
                                <p>{task.description}</p>
                            </div>
                        </div>

                        <div className="mb-8">
                            <h3 className="text-sm font-bold text-text-secondary uppercase mb-3">Subtasks</h3>
                            <div className="space-y-2">
                                <div className="flex items-center space-x-3 p-2 hover:bg-secondary-50 rounded-lg group cursor-pointer">
                                    <input type="checkbox" className="rounded border-secondary-300 text-primary focus:ring-primary" />
                                    <span className="text-sm text-text-primary flex-1">Database Schema Design</span>
                                </div>
                                <div className="flex items-center space-x-3 p-2 hover:bg-secondary-50 rounded-lg group cursor-pointer">
                                    <input type="checkbox" className="rounded border-secondary-300 text-primary focus:ring-primary" />
                                    <span className="text-sm text-text-primary flex-1">API Endpoint Implementation</span>
                                </div>
                                <div className="flex items-center text-secondary-500 text-sm pl-2 cursor-pointer hover:text-primary mt-2">
                                    <Icon name="Plus" size={14} className="mr-2" />
                                    Add subtask
                                </div>
                            </div>
                        </div>

                        <div>
                            <h3 className="text-sm font-bold text-text-secondary uppercase mb-4">Activity & Comments</h3>
                            <div className="space-y-6">
                                {task.comments.map(comment => (
                                    <div key={comment.id} className="flex space-x-3">
                                        <div className="w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center text-primary-700 text-xs font-bold">
                                            {comment.user.charAt(0)}
                                        </div>
                                        <div className="flex-1">
                                            <div className="flex items-center space-x-2 mb-1">
                                                <span className="text-sm font-medium text-text-primary">{comment.user}</span>
                                                <span className="text-xs text-text-secondary">{comment.timestamp}</span>
                                            </div>
                                            <p className="text-sm text-text-secondary">{comment.content}</p>
                                        </div>
                                    </div>
                                ))}

                                <div className="flex space-x-3 mt-4">
                                    <div className="w-8 h-8 rounded-full bg-secondary-200 flex items-center justify-center text-secondary-600 text-xs font-bold">
                                        ME
                                    </div>
                                    <div className="flex-1">
                                        <textarea
                                            placeholder="Add a comment..."
                                            className="w-full border border-border rounded-lg p-3 text-sm focus:ring-2 focus:ring-primary focus:border-transparent min-h-[80px]"
                                        ></textarea>
                                        <div className="flex justify-end mt-2">
                                            <button className="px-3 py-1.5 bg-secondary-100 text-secondary-700 rounded hover:bg-secondary-200 text-xs font-medium mr-2">Attach</button>
                                            <button className="px-3 py-1.5 bg-primary text-white rounded hover:bg-primary-700 text-xs font-medium">Comment</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Sidebar (Right) */}
                    <div className="w-80 bg-secondary-50 p-6 overflow-y-auto">
                        <div className="space-y-6">
                            <div>
                                <h4 className="text-xs font-bold text-text-secondary uppercase mb-3">Details</h4>
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm text-text-secondary">Assignee</span>
                                        <div className="flex items-center space-x-2">
                                            <div className="w-6 h-6 rounded-full bg-primary-100 flex items-center justify-center text-primary-700 text-xs">
                                                {task.assignee.avatar}
                                            </div>
                                            <span className="text-sm text-text-primary">{task.assignee.name}</span>
                                        </div>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm text-text-secondary">Reporter</span>
                                        <div className="flex items-center space-x-2">
                                            <div className="w-6 h-6 rounded-full bg-secondary-200 flex items-center justify-center text-secondary-700 text-xs">
                                                {task.reporter.avatar}
                                            </div>
                                            <span className="text-sm text-text-primary">{task.reporter.name}</span>
                                        </div>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm text-text-secondary">Due Date</span>
                                        <span className="text-sm text-text-primary">{task.dueDate}</span>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm text-text-secondary">Estimation</span>
                                        <span className="text-sm text-text-primary">5 Points</span>
                                    </div>
                                </div>
                            </div>

                            <div className="pt-6 border-t border-border">
                                <h4 className="text-xs font-bold text-text-secondary uppercase mb-3">Tags</h4>
                                <div className="flex flex-wrap gap-2">
                                    {task.tags.map(tag => (
                                        <span key={tag} className="px-2 py-1 bg-secondary-200 text-secondary-700 rounded text-xs">
                                            {tag}
                                        </span>
                                    ))}
                                    <button className="px-2 py-1 border border-border border-dashed text-text-secondary rounded text-xs hover:border-secondary-400 hover:text-text-primary">
                                        + Add
                                    </button>
                                </div>
                            </div>

                            <div className="pt-6 border-t border-border">
                                <h4 className="text-xs font-bold text-text-secondary uppercase mb-3">Actions</h4>
                                <div className="space-y-2">
                                    <button className="w-full flex items-center px-3 py-2 bg-white border border-border rounded hover:bg-secondary-50 text-sm text-text-secondary transition-colors">
                                        <Icon name="Link" size={14} className="mr-2" />
                                        Copy Link
                                    </button>
                                    <button className="w-full flex items-center px-3 py-2 bg-white border border-border rounded hover:bg-secondary-50 text-sm text-text-secondary transition-colors">
                                        <Icon name="Archive" size={14} className="mr-2" />
                                        Archive Task
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default TaskDetailModal;
