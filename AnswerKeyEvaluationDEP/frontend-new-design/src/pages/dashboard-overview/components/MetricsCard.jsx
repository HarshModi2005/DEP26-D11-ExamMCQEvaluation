import React from 'react';
import Icon from '../../../components/AppIcon';

const MetricsCard = ({ title, value, icon, color, trend, onClick }) => {
    // Map color names to Tailwind classes
    const colorMap = {
        primary: 'bg-primary-50 text-primary-600',
        secondary: 'bg-secondary-50 text-secondary-600',
        success: 'bg-success-50 text-success-600',
        warning: 'bg-warning-50 text-warning-600',
        error: 'bg-error-50 text-error-600',
        accent: 'bg-accent-50 text-accent-600',
    };

    const iconColorClass = colorMap[color] || colorMap.primary;

    return (
        <div
            onClick={onClick}
            className="bg-surface border border-border rounded-xl p-6 hover:shadow-lg transition-all duration-200 cursor-pointer group"
        >
            <div className="flex items-start justify-between mb-4">
                <div className={`p-3 rounded-lg ${iconColorClass} group-hover:scale-110 transition-transform duration-200`}>
                    <Icon name={icon} size={24} />
                </div>
                {trend && (
                    <span className="text-xs font-medium px-2 py-1 bg-secondary-50 text-secondary-600 rounded-full">
                        {trend}
                    </span>
                )}
            </div>

            <h3 className="text-sm font-medium text-text-secondary mb-1">{title}</h3>
            <p className="text-2xl font-bold text-text-primary">{value}</p>
        </div>
    );
};

export default MetricsCard;
