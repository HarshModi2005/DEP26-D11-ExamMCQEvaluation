import React from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

const VelocityChart = () => {
    // Mock data for team velocity
    const velocityData = [
        { sprint: "Sprint 7", committed: 85, completed: 78 },
        { sprint: "Sprint 8", committed: 90, completed: 82 },
        { sprint: "Sprint 9", committed: 95, completed: 90 },
        { sprint: "Sprint 10", committed: 100, completed: 88 },
        { sprint: "Sprint 11", committed: 110, completed: 105 },
    ];

    // Calculate average velocity
    const averageVelocity = Math.round(
        velocityData.reduce((sum, sprint) => sum + sprint.completed, 0) / velocityData.length
    );

    // Custom tooltip
    const CustomTooltip = ({ active, payload, label }) => {
        if (active && payload && payload.length) {
            return (
                <div className="bg-surface p-3 border border-border rounded-lg shadow-md">
                    <p className="text-sm font-medium text-text-primary mb-2">{label}</p>
                    <div className="space-y-1">
                        <p className="text-xs">
                            <span className="inline-block w-3 h-3 bg-primary rounded-sm mr-2"></span>
                            Committed: <span className="font-medium">{payload[0].value} points</span>
                        </p>
                        <p className="text-xs">
                            <span className="inline-block w-3 h-3 bg-success rounded-sm mr-2"></span>
                            Completed: <span className="font-medium">{payload[1].value} points</span>
                        </p>
                    </div>
                </div>
            );
        }
        return null;
    };

    return (
        <div className="space-y-4">
            <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                        data={velocityData}
                        margin={{ top: 10, right: 10, left: 0, bottom: 20 }}
                        barGap={4}
                    >
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
                        <XAxis
                            dataKey="sprint"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 12, fill: '#475569' }}
                            dy={10}
                        />
                        <YAxis
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 12, fill: '#475569' }}
                            width={30}
                        />
                        <Tooltip content={<CustomTooltip />} />
                        <ReferenceLine
                            y={averageVelocity}
                            stroke="#059669"
                            strokeDasharray="3 3"
                            strokeWidth={2}
                        />
                        <Bar dataKey="committed" fill="#3B82F6" radius={[4, 4, 0, 0]} maxBarSize={40} />
                        <Bar dataKey="completed" fill="#10B981" radius={[4, 4, 0, 0]} maxBarSize={40} />
                    </BarChart>
                </ResponsiveContainer>
            </div>

            <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4">
                    <div className="flex items-center space-x-2">
                        <div className="w-3 h-3 bg-primary rounded-sm"></div>
                        <span className="text-xs text-text-secondary">Committed</span>
                    </div>
                    <div className="flex items-center space-x-2">
                        <div className="w-3 h-3 bg-success rounded-sm"></div>
                        <span className="text-xs text-text-secondary">Completed</span>
                    </div>
                </div>

                <div className="flex items-center space-x-2">
                    <div className="w-3 h-0.5 bg-success"></div>
                    <span className="text-xs text-text-secondary">Avg: {averageVelocity} points</span>
                </div>
            </div>

            <div className="border border-border rounded-lg p-4">
                <h4 className="text-xs font-medium text-text-secondary mb-3">Velocity Insights</h4>
                <div className="grid grid-cols-3 gap-4 text-center">
                    <div>
                        <p className="text-xs text-text-secondary mb-1">Average Velocity</p>
                        <p className="text-lg font-semibold text-text-primary">{averageVelocity}</p>
                    </div>
                    <div>
                        <p className="text-xs text-text-secondary mb-1">Completion Rate</p>
                        <p className="text-lg font-semibold text-success-600">
                            {Math.round(
                                (velocityData.reduce((sum, sprint) => sum + sprint.completed, 0) /
                                    velocityData.reduce((sum, sprint) => sum + sprint.committed, 0)) * 100
                            )}%
                        </p>
                    </div>
                    <div>
                        <p className="text-xs text-text-secondary mb-1">Trend</p>
                        <p className="text-lg font-semibold text-primary">
                            {velocityData[velocityData.length - 1].completed > velocityData[0].completed ? "↗" : "↘"}
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default VelocityChart;