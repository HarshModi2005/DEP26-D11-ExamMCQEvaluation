import React from "react";
import Icon from "../../../components/AppIcon";

const SprintCapacityIndicator = ({ capacity }) => {
    const { total, used, remaining } = capacity;

    // Calculate percentage used
    const percentUsed = total > 0 ? Math.round((used / total) * 100) : 0;

    // Determine status color
    const getStatusColor = () => {
        if (percentUsed >= 90) return "bg-error";
        if (percentUsed >= 75) return "bg-warning";
        return "bg-success";
    };

    // Determine text color
    const getTextColor = () => {
        if (percentUsed >= 90) return "text-error";
        if (percentUsed >= 75) return "text-warning-600";
        return "text-success-600";
    };

    // Determine icon
    const getStatusIcon = () => {
        if (percentUsed >= 90) return "AlertTriangle";
        if (percentUsed >= 75) return "AlertCircle";
        return "CheckCircle";
    };

    return (
        <div className="space-y-4">
            {/* Progress Bar */}
            <div className="w-full h-3 bg-secondary-100 rounded-full overflow-hidden">
                <div
                    className={`h-full ${getStatusColor()} transition-all duration-500 ease-in-out`}
                    style={{ width: `${percentUsed}%` }}
                />
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                    <p className="text-xs text-text-secondary mb-1">Total Capacity</p>
                    <p className="text-lg font-semibold text-text-primary">{total}</p>
                </div>
                <div>
                    <p className="text-xs text-text-secondary mb-1">Used</p>
                    <p className="text-lg font-semibold text-primary">{used}</p>
                </div>
                <div>
                    <p className="text-xs text-text-secondary mb-1">Remaining</p>
                    <p className={`text-lg font-semibold ${getTextColor()}`}>{remaining}</p>
                </div>
            </div>

            {/* Status Message */}
            <div className={`flex items-center space-x-2 p-3 rounded-lg ${percentUsed >= 90
                    ? "bg-error-50"
                    : percentUsed >= 75
                        ? "bg-warning-50" : "bg-success-50"
                }`}>
                <Icon
                    name={getStatusIcon()}
                    size={18}
                    color={
                        percentUsed >= 90
                            ? "var(--color-error)"
                            : percentUsed >= 75
                                ? "var(--color-warning)"
                                : "var(--color-success)"
                    }
                />
                <span className={`text-sm ${percentUsed >= 90
                        ? "text-error-700"
                        : percentUsed >= 75
                            ? "text-warning-700" : "text-success-700"
                    }`}>
                    {percentUsed >= 90
                        ? "Sprint is overloaded. Consider reducing scope."
                        : percentUsed >= 75
                            ? "Sprint is nearing capacity. Add tasks carefully." : "Sprint has good capacity balance."}
                </span>
            </div>

            {/* Monte Carlo Forecast */}
            <div className="border border-border rounded-lg p-4">
                <h4 className="text-xs font-medium text-text-secondary mb-3">Monte Carlo Forecast</h4>
                <div className="flex items-center justify-between">
                    <div>
                        <p className="text-sm text-text-primary mb-1">Completion Probability</p>
                        <div className="flex items-center space-x-1">
                            <Icon name="TrendingUp" size={16} color="var(--color-success)" />
                            <span className="text-sm font-medium text-success-600">
                                {percentUsed >= 90 ? "65%" : percentUsed >= 75 ? "80%" : "95%"}
                            </span>
                        </div>
                    </div>
                    <div>
                        <p className="text-sm text-text-primary mb-1">Forecast Completion</p>
                        <p className="text-sm font-medium text-text-primary">
                            {percentUsed >= 90
                                ? new Date(new Date(capacity.endDate).setDate(new Date(capacity.endDate).getDate() + 2)).toLocaleDateString()
                                : percentUsed >= 75
                                    ? new Date(new Date(capacity.endDate).setDate(new Date(capacity.endDate).getDate() + 1)).toLocaleDateString()
                                    : new Date(capacity.endDate).toLocaleDateString()}
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SprintCapacityIndicator;