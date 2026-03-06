import React, { useState } from "react";
import Icon from "../../../components/AppIcon";

const TaskBacklog = ({
    tasks,
    onTaskSelect,
    onAddToSprint,
    onBulkSelection,
    selectedTasks,
    onBulkEstimation
}) => {
    const [expandedTasks, setExpandedTasks] = useState([]);
    const [showEstimationModal, setShowEstimationModal] = useState(false);
    const [estimationPoints, setEstimationPoints] = useState(5);

    // Fibonacci sequence for story point suggestions
    const fibonacciPoints = [1, 2, 3, 5, 8, 13, 21];

    const handleToggleExpand = (taskId) => {
        setExpandedTasks(prev =>
            prev.includes(taskId)
                ? prev.filter(id => id !== taskId)
                : [...prev, taskId]
        );
    };

    const handleSelectTask = (taskId, isSelected) => {
        if (isSelected) {
            onBulkSelection([...selectedTasks, taskId]);
        } else {
            onBulkSelection(selectedTasks.filter(id => id !== taskId));
        }
    };

    const handleSelectAll = (isSelected) => {
        if (isSelected) {
            onBulkSelection(tasks.map(task => task.id));
        } else {
            onBulkSelection([]);
        }
    };

    const handleEstimateSelected = () => {
        setShowEstimationModal(true);
    };

    const handleEstimationSubmit = () => {
        onBulkEstimation(estimationPoints);
        setShowEstimationModal(false);
    };

    return (
        <div>
            {/* Table Header */}
            <div className="grid grid-cols-12 gap-4 px-6 py-3 bg-secondary-50 border-y border-border">
                <div className="col-span-1 flex items-center">
                    <input
                        type="checkbox"
                        checked={selectedTasks.length === tasks.length && tasks.length > 0}
                        onChange={(e) => handleSelectAll(e.target.checked)}
                        className="w-4 h-4 rounded border-secondary-300 text-primary focus:ring-primary"
                    />
                </div>
                <div className="col-span-5 text-xs font-medium text-text-secondary">Task</div>
                <div className="col-span-2 text-xs font-medium text-text-secondary">Story Points</div>
                <div className="col-span-2 text-xs font-medium text-text-secondary">Assignee</div>
                <div className="col-span-2 text-xs font-medium text-text-secondary">Actions</div>
            </div>

            {/* Task List */}
            {tasks.length === 0 ? (
                <div className="text-center py-12">
                    <Icon name="Search" size={48} color="#CBD5E1" className="mx-auto mb-4" />
                    <p className="text-text-secondary mb-2">No tasks found</p>
                    <p className="text-sm text-text-secondary">Try adjusting your filters</p>
                </div>
            ) : (
                <div className="divide-y divide-border">
                    {tasks.map(task => {
                        const isExpanded = expandedTasks.includes(task.id);
                        const isSelected = selectedTasks.includes(task.id);

                        return (
                            <div key={task.id} className={`transition-colors duration-200 ${isSelected ? 'bg-primary-50' : ''}`}>
                                {/* Task Row */}
                                <div className="grid grid-cols-12 gap-4 px-6 py-4 items-center">
                                    <div className="col-span-1">
                                        <input
                                            type="checkbox"
                                            checked={isSelected}
                                            onChange={(e) => handleSelectTask(task.id, e.target.checked)}
                                            className="w-4 h-4 rounded border-secondary-300 text-primary focus:ring-primary"
                                        />
                                    </div>

                                    <div className="col-span-5">
                                        <div className="flex items-start space-x-3">
                                            <button
                                                onClick={() => handleToggleExpand(task.id)}
                                                className="mt-1 p-1 text-secondary-600 hover:text-text-primary hover:bg-secondary-100 rounded transition-colors duration-200"
                                            >
                                                <Icon name={isExpanded ? "ChevronDown" : "ChevronRight"} size={14} />
                                            </button>

                                            <div>
                                                <div className="flex items-center space-x-2 mb-1">
                                                    <span className="text-xs font-mono text-text-secondary">{task.id}</span>
                                                    <div className={`px-2 py-0.5 rounded-full text-xs font-medium ${task.priority === "High" ? "bg-error-100 text-error-700"
                                                            : task.priority === "Medium" ? "bg-warning-100 text-warning-700" : "bg-secondary-100 text-secondary-700"
                                                        }`}>
                                                        {task.priority}
                                                    </div>
                                                </div>

                                                <h4
                                                    className="text-sm font-medium text-text-primary hover:text-primary cursor-pointer transition-colors duration-200"
                                                    onClick={() => onTaskSelect(task.id)}
                                                >
                                                    {task.title}
                                                </h4>

                                                <div className="flex items-center space-x-2 mt-1">
                                                    <span className="px-2 py-0.5 bg-secondary-100 text-secondary-700 rounded-full text-xs">
                                                        {task.epic}
                                                    </span>
                                                    {task.labels.map((label, index) => (
                                                        <span
                                                            key={index}
                                                            className="px-2 py-0.5 bg-primary-50 text-primary-700 rounded-full text-xs"
                                                        >
                                                            {label}
                                                        </span>
                                                    ))}
                                                </div>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="col-span-2">
                                        <div className="flex items-center space-x-2">
                                            <div className="w-8 h-8 bg-primary-100 rounded-lg flex items-center justify-center">
                                                <span className="text-sm font-medium text-primary-700">{task.storyPoints || "-"}</span>
                                            </div>
                                            <button className="p-1 text-secondary-600 hover:text-text-primary hover:bg-secondary-100 rounded transition-colors duration-200">
                                                <Icon name="Edit2" size={14} />
                                            </button>
                                        </div>
                                    </div>

                                    <div className="col-span-2">
                                        <div className="flex items-center space-x-2">
                                            <div className="w-8 h-8 bg-secondary-100 rounded-full flex items-center justify-center">
                                                <span className="text-xs font-medium text-secondary-700">{task.assignee.avatar}</span>
                                            </div>
                                            <span className="text-sm text-text-secondary">{task.assignee.name}</span>
                                        </div>
                                    </div>

                                    <div className="col-span-2">
                                        <button
                                            onClick={() => onAddToSprint(task.id)}
                                            className="px-3 py-1.5 bg-primary-50 text-primary-700 rounded-lg hover:bg-primary-100 transition-colors duration-200 text-sm"
                                        >
                                            Add to Sprint
                                        </button>
                                    </div>
                                </div>

                                {/* Expanded Task Details */}
                                {isExpanded && (
                                    <div className="px-6 py-4 bg-secondary-50 border-t border-border">
                                        <div className="ml-8">
                                            <p className="text-sm text-text-secondary mb-4">{task.description}</p>

                                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                                <div>
                                                    <h5 className="text-xs font-medium text-text-secondary mb-1">Epic</h5>
                                                    <p className="text-sm text-text-primary">{task.epic}</p>
                                                </div>
                                                <div>
                                                    <h5 className="text-xs font-medium text-text-secondary mb-1">Priority</h5>
                                                    <p className="text-sm text-text-primary">{task.priority}</p>
                                                </div>
                                                <div>
                                                    <h5 className="text-xs font-medium text-text-secondary mb-1">Status</h5>
                                                    <p className="text-sm text-text-primary">{task.status}</p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Bulk Actions Footer */}
            {selectedTasks.length > 0 && (
                <div className="sticky bottom-0 left-0 right-0 bg-surface border-t border-border p-4 shadow-md">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-2">
                            <span className="text-sm text-text-secondary">
                                {selectedTasks.length} {selectedTasks.length === 1 ? 'task' : 'tasks'} selected
                            </span>
                            <button
                                onClick={() => onBulkSelection([])}
                                className="text-sm text-primary hover:text-primary-700 transition-colors duration-200"
                            >
                                Clear
                            </button>
                        </div>

                        <div className="flex items-center space-x-3">
                            <button
                                onClick={handleEstimateSelected}
                                className="px-4 py-2 bg-secondary-100 text-secondary-700 rounded-lg hover:bg-secondary-200 transition-colors duration-200 text-sm"
                            >
                                Estimate Points
                            </button>
                            <button
                                onClick={() => {
                                    const allTasksSelected = tasks.every(task => selectedTasks.includes(task.id));
                                    if (allTasksSelected) {
                                        tasks.forEach(task => onAddToSprint(task.id));
                                    } else {
                                        selectedTasks.forEach(taskId => onAddToSprint(taskId));
                                    }
                                }}
                                className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors duration-200 text-sm"
                            >
                                Add to Sprint
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Estimation Modal */}
            {showEstimationModal && (
                <div className="fixed inset-0 bg-black bg-opacity-50 z-200 flex items-center justify-center p-4">
                    <div className="w-full max-w-md bg-surface rounded-lg shadow-xl border border-border overflow-hidden">
                        <div className="p-6 border-b border-border">
                            <h3 className="text-lg font-medium text-text-primary">Estimate Story Points</h3>
                            <p className="text-sm text-text-secondary mt-1">
                                Assign story points to {selectedTasks.length} selected {selectedTasks.length === 1 ? 'task' : 'tasks'}
                            </p>
                        </div>

                        <div className="p-6">
                            <div className="mb-6">
                                <label className="block text-sm font-medium text-text-primary mb-2">Story Points</label>
                                <input
                                    type="number"
                                    value={estimationPoints}
                                    onChange={(e) => setEstimationPoints(parseInt(e.target.value) || 0)}
                                    min={0}
                                    className="w-full border border-border rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                                />
                            </div>

                            <div className="mb-6">
                                <label className="block text-sm font-medium text-text-primary mb-2">Suggested Values</label>
                                <div className="flex flex-wrap gap-2">
                                    {fibonacciPoints.map(point => (
                                        <button
                                            key={point}
                                            onClick={() => setEstimationPoints(point)}
                                            className={`px-3 py-1.5 rounded-lg text-sm ${estimationPoints === point
                                                    ? 'bg-primary text-white' : 'bg-secondary-100 text-secondary-700 hover:bg-secondary-200'
                                                } transition-colors duration-200`}
                                        >
                                            {point}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            <div className="flex justify-end space-x-3">
                                <button
                                    onClick={() => setShowEstimationModal(false)}
                                    className="px-4 py-2 border border-border rounded-lg hover:bg-secondary-100 transition-colors duration-200"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleEstimationSubmit}
                                    className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors duration-200"
                                >
                                    Apply Estimation
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Click outside to close */}
                    <div
                        className="absolute inset-0 -z-10"
                        onClick={() => setShowEstimationModal(false)}
                    />
                </div>
            )}
        </div>
    );
};

export default TaskBacklog;