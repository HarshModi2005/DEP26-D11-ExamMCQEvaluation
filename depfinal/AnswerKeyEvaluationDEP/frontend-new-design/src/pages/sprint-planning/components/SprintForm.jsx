import React, { useState } from "react";
import Icon from "../../../components/AppIcon";

const SprintForm = ({ sprint, onUpdate }) => {
    const [isEditing, setIsEditing] = useState(false);
    const [formData, setFormData] = useState({
        name: sprint.name,
        startDate: sprint.startDate,
        endDate: sprint.endDate,
        goal: sprint.goal,
        capacity: sprint.capacity,
    });

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData({
            ...formData,
            [name]: value,
        });
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        onUpdate({ ...sprint, ...formData });
        setIsEditing(false);
    };

    const handleCancel = () => {
        setFormData({
            name: sprint.name,
            startDate: sprint.startDate,
            endDate: sprint.endDate,
            goal: sprint.goal,
            capacity: sprint.capacity,
        });
        setIsEditing(false);
    };

    // Calculate sprint duration in days
    const startDate = new Date(sprint.startDate);
    const endDate = new Date(sprint.endDate);
    const durationInDays = Math.round((endDate - startDate) / (1000 * 60 * 60 * 24));

    return (
        <div className="p-6">
            <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-medium text-text-primary">Sprint Details</h2>
                <button
                    onClick={() => setIsEditing(!isEditing)}
                    className="p-2 text-secondary-600 hover:text-text-primary hover:bg-secondary-100 rounded-lg transition-colors duration-200"
                >
                    <Icon name={isEditing ? "X" : "Edit"} size={18} />
                </button>
            </div>

            {isEditing ? (
                <form onSubmit={handleSubmit}>
                    <div className="space-y-4">
                        <div>
                            <label className="block text-sm font-medium text-text-primary mb-1">Sprint Name</label>
                            <input
                                type="text"
                                name="name"
                                value={formData.name}
                                onChange={handleChange}
                                className="w-full border border-border rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                                required
                            />
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-sm font-medium text-text-primary mb-1">Start Date</label>
                                <input
                                    type="date"
                                    name="startDate"
                                    value={formData.startDate}
                                    onChange={handleChange}
                                    className="w-full border border-border rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                                    required
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-text-primary mb-1">End Date</label>
                                <input
                                    type="date"
                                    name="endDate"
                                    value={formData.endDate}
                                    onChange={handleChange}
                                    className="w-full border border-border rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                                    required
                                />
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-text-primary mb-1">Sprint Goal</label>
                            <textarea
                                name="goal"
                                value={formData.goal}
                                onChange={handleChange}
                                rows={3}
                                className="w-full border border-border rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-text-primary mb-1">
                                Team Capacity (Story Points)
                            </label>
                            <input
                                type="number"
                                name="capacity"
                                value={formData.capacity}
                                onChange={handleChange}
                                min={1}
                                className="w-full border border-border rounded-lg px-3 py-2 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                                required
                            />
                        </div>

                        <div className="flex justify-end space-x-3 pt-4">
                            <button
                                type="button"
                                onClick={handleCancel}
                                className="px-4 py-2 border border-border rounded-lg hover:bg-secondary-100 transition-colors duration-200"
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-700 transition-colors duration-200"
                            >
                                Save Changes
                            </button>
                        </div>
                    </div>
                </form>
            ) : (
                <div className="space-y-6">
                    <div>
                        <h3 className="text-sm font-medium text-text-secondary mb-1">Sprint Name</h3>
                        <p className="text-text-primary">{sprint.name}</p>
                    </div>

                    <div className="grid grid-cols-2 gap-6">
                        <div>
                            <h3 className="text-sm font-medium text-text-secondary mb-1">Duration</h3>
                            <div className="flex items-center space-x-2">
                                <Icon name="Calendar" size={16} color="#64748B" />
                                <p className="text-text-primary">{durationInDays} days</p>
                            </div>
                        </div>
                        <div>
                            <h3 className="text-sm font-medium text-text-secondary mb-1">Dates</h3>
                            <p className="text-text-primary">
                                {new Date(sprint.startDate).toLocaleDateString()} - {new Date(sprint.endDate).toLocaleDateString()}
                            </p>
                        </div>
                    </div>

                    <div>
                        <h3 className="text-sm font-medium text-text-secondary mb-1">Sprint Goal</h3>
                        <p className="text-text-primary">{sprint.goal}</p>
                    </div>

                    <div>
                        <h3 className="text-sm font-medium text-text-secondary mb-1">Team Capacity</h3>
                        <div className="flex items-center space-x-2">
                            <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center">
                                <span className="text-sm font-bold text-white">{sprint.capacity}</span>
                            </div>
                            <p className="text-text-primary">story points</p>
                        </div>
                    </div>

                    <div className="pt-4">
                        <button className="w-full px-4 py-2 bg-primary-50 text-primary-700 rounded-lg hover:bg-primary-100 transition-colors duration-200 flex items-center justify-center space-x-2">
                            <Icon name="Play" size={16} />
                            <span>Start Sprint</span>
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};

export default SprintForm;