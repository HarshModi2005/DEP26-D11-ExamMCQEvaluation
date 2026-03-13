import React from 'react';
import Icon from '../../../components/AppIcon';

const SprintProgress = ({ sprintData, onViewDetails }) => {
    const { currentSprint } = sprintData;

    // Calculate progress percentage
    const progress = Math.round((currentSprint.completedPoints / currentSprint.totalPoints) * 100);

    return (
        <div className="bg-surface border border-border rounded-xl p-6 h-full flex flex-col">
            <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-semibold text-text-primary">Sprint Progress</h3>
                <button
                    onClick={onViewDetails}
                    className="text-primary hover:text-primary-700 transition-colors duration-200"
                >
                    <Icon name="ArrowRight" size={20} />
                </button>
            </div>

            <div className="flex-1">
                <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-text-primary">{currentSprint.name}</span>
                    <span className="text-xs text-text-secondary">{currentSprint.remainingDays} days remaining</span>
                </div>

                {/* Progress Bar */}
                <div className="w-full bg-secondary-200 rounded-full h-3 mb-4">
                    <div
                        className="bg-primary h-3 rounded-full transition-all duration-500 ease-out"
                        style={{ width: `${progress}%` }}
                    ></div>
                </div>

                <div className="flex justify-between text-sm text-text-secondary mb-6">
                    <span>{currentSprint.completedPoints} pts completed</span>
                    <span>{currentSprint.totalPoints} pts total</span>
                </div>

                {/* Minified Burndown Chart Placeholder */}
                <div className="bg-secondary-50 rounded-lg p-4 flex items-center justify-center border border-border border-dashed h-40">
                    <div className="text-center">
                        <Icon name="BarChart2" size={24} className="mx-auto text-secondary-400 mb-2" />
                        <p className="text-xs text-secondary-500">Burndown Chart Visualization</p>
                    </div>
                </div>
            </div>

            <div className="mt-6 pt-4 border-t border-border flex items-center justify-between">
                <div>
                    <p className="text-xs text-text-secondary">Start Date</p>
                    <p className="text-sm font-medium text-text-primary">{currentSprint.startDate}</p>
                </div>
                <div className="text-right">
                    <p className="text-xs text-text-secondary">End Date</p>
                    <p className="text-sm font-medium text-text-primary">{currentSprint.endDate}</p>
                </div>
            </div>
        </div>
    );
};

export default SprintProgress;
