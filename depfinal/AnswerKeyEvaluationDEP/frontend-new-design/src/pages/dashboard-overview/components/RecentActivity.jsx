import React from 'react';
import Icon from '../../../components/AppIcon';

const RecentActivity = ({ activities, onTaskClick }) => {
    const getActivityIcon = (type) => {
        switch (type) {
            case 'task_created':
                return 'Plus';
            case 'task_completed':
                return 'CheckCircle';
            case 'task_assigned':
                return 'UserCheck';
            case 'sprint_started':
                return 'Play';
            case 'comment_added':
                return 'MessageCircle';
            default:
                return 'Activity';
        }
    };

    const getActivityColor = (type) => {
        switch (type) {
            case 'task_created':
                return 'text-primary';
            case 'task_completed':
                return 'text-success';
            case 'task_assigned':
                return 'text-warning-600';
            case 'sprint_started':
                return 'text-accent';
            case 'comment_added':
                return 'text-secondary';
            default:
                return 'text-secondary';
        }
    };

    const getPriorityColor = (priority) => {
        switch (priority) {
            case 'High':
                return 'bg-error-100 text-error-700';
            case 'Medium':
                return 'bg-warning-100 text-warning-700';
            case 'Low':
                return 'bg-success-100 text-success-700';
            default:
                return 'bg-secondary-100 text-secondary-700';
        }
    };

    return (
        <div className="bg-surface border border-border rounded-lg">
            <div className="p-6 border-b border-border">
                <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold text-text-primary">Recent Activity</h3>
                    <div className="flex items-center space-x-2">
                        <div className="flex items-center space-x-1">
                            <div className="w-2 h-2 bg-success rounded-full"></div>
                            <span className="text-xs text-text-secondary">Live</span>
                        </div>
                        <button className="p-1 text-secondary-600 hover:text-text-primary transition-colors duration-200">
                            <Icon name="MoreHorizontal" size={16} />
                        </button>
                    </div>
                </div>
            </div>

            <div className="max-h-96 overflow-y-auto">
                {activities.map((activity, index) => (
                    <div
                        key={activity.id}
                        className="p-4 border-b border-border-light last:border-b-0 hover:bg-secondary-50 transition-colors duration-150"
                    >
                        <div className="flex items-start space-x-3">
                            {/* User Avatar with Online Status */}
                            <div className="relative">
                                <div className="w-8 h-8 bg-secondary-100 rounded-full flex items-center justify-center">
                                    <span className="text-sm font-medium text-secondary-700">
                                        {activity.user.avatar}
                                    </span>
                                </div>
                                {activity.user.isOnline && (
                                    <div className="absolute -bottom-1 -right-1 w-3 h-3 bg-success border-2 border-surface rounded-full"></div>
                                )}
                            </div>

                            {/* Activity Content */}
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center space-x-2 mb-1">
                                    <Icon
                                        name={getActivityIcon(activity.type)}
                                        size={14}
                                        className={getActivityColor(activity.type)}
                                    />
                                    <span className="text-sm font-medium text-text-primary">
                                        {activity.user.name}
                                    </span>
                                    <span className="text-sm text-text-secondary">
                                        {activity.action}
                                    </span>
                                </div>

                                <div className="flex items-center space-x-2 mb-2">
                                    <button
                                        onClick={() => onTaskClick && onTaskClick(activity.target)}
                                        className="text-sm font-medium text-primary hover:text-primary-700 transition-colors duration-200 truncate"
                                    >
                                        {activity.target}
                                    </button>
                                    {activity.priority && (
                                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${getPriorityColor(activity.priority)}`}>
                                            {activity.priority}
                                        </span>
                                    )}
                                </div>

                                <div className="flex items-center justify-between">
                                    <span className="text-xs text-text-secondary">
                                        {activity.project}
                                    </span>
                                    <span className="text-xs text-text-secondary">
                                        {activity.timestamp}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                ))}
            </div>

            <div className="p-4 border-t border-border">
                <button className="w-full text-sm text-primary hover:text-primary-700 transition-colors duration-200 flex items-center justify-center space-x-2">
                    <Icon name="Eye" size={16} />
                    <span>View All Activity</span>
                </button>
            </div>
        </div>
    );
};

export default RecentActivity;