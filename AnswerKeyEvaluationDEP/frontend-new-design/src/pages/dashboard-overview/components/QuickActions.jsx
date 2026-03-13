import React from 'react';
import Icon from '../../../components/AppIcon';

const QuickActions = ({ actions }) => {
    const getColorClasses = (color) => {
        switch (color) {
            case 'primary':
                return {
                    bg: 'bg-primary',
                    hover: 'hover:bg-primary-700',
                    text: 'text-white'
                };
            case 'success':
                return {
                    bg: 'bg-success',
                    hover: 'hover:bg-success-600',
                    text: 'text-white'
                };
            case 'accent':
                return {
                    bg: 'bg-accent',
                    hover: 'hover:bg-accent-700',
                    text: 'text-white'
                };
            case 'warning':
                return {
                    bg: 'bg-warning',
                    hover: 'hover:bg-warning-600',
                    text: 'text-white'
                };
            default:
                return {
                    bg: 'bg-secondary',
                    hover: 'hover:bg-secondary-600',
                    text: 'text-white'
                };
        }
    };

    return (
        <div className="bg-surface border border-border rounded-lg">
            <div className="p-6 border-b border-border">
                <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold text-text-primary">Quick Actions</h3>
                    <div className="flex items-center space-x-1">
                        <kbd className="px-2 py-1 text-xs bg-secondary-100 text-secondary-600 rounded border">Ctrl</kbd>
                        <span className="text-xs text-text-secondary">+ Key</span>
                    </div>
                </div>
                <p className="text-sm text-text-secondary mt-2">
                    Streamline your workflow with keyboard shortcuts
                </p>
            </div>

            <div className="p-6">
                <div className="grid grid-cols-1 gap-4">
                    {actions.map((action) => {
                        const colorClasses = getColorClasses(action.color);

                        return (
                            <button
                                key={action.id}
                                onClick={action.action}
                                className={`w-full p-4 ${colorClasses.bg} ${colorClasses.hover} ${colorClasses.text} rounded-lg transition-all duration-200 hover:scale-105 hover:shadow-md group`}
                            >
                                <div className="flex items-center space-x-4">
                                    <div className="w-10 h-10 bg-white bg-opacity-20 rounded-lg flex items-center justify-center">
                                        <Icon name={action.icon} size={20} />
                                    </div>
                                    <div className="flex-1 text-left">
                                        <div className="flex items-center justify-between mb-1">
                                            <h4 className="font-medium">{action.title}</h4>
                                            <div className="flex items-center space-x-1 opacity-75">
                                                <kbd className="px-2 py-1 text-xs bg-white bg-opacity-20 rounded border border-white border-opacity-30">
                                                    {action.shortcut}
                                                </kbd>
                                            </div>
                                        </div>
                                        <p className="text-sm opacity-90">{action.description}</p>
                                    </div>
                                    <Icon
                                        name="ArrowRight"
                                        size={16}
                                        className="opacity-75 group-hover:translate-x-1 transition-transform duration-200"
                                    />
                                </div>
                            </button>
                        );
                    })}
                </div>

                {/* Additional Quick Links */}
                <div className="mt-6 pt-6 border-t border-border">
                    <h4 className="text-sm font-medium text-text-primary mb-3">Quick Links</h4>
                    <div className="grid grid-cols-2 gap-3">
                        <button className="p-3 text-left bg-secondary-50 hover:bg-secondary-100 rounded-lg transition-colors duration-200">
                            <div className="flex items-center space-x-2">
                                <Icon name="FileText" size={16} color="#64748B" />
                                <span className="text-sm text-text-secondary">Documentation</span>
                            </div>
                        </button>
                        <button className="p-3 text-left bg-secondary-50 hover:bg-secondary-100 rounded-lg transition-colors duration-200">
                            <div className="flex items-center space-x-2">
                                <Icon name="HelpCircle" size={16} color="#64748B" />
                                <span className="text-sm text-text-secondary">Help Center</span>
                            </div>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default QuickActions;