import React from 'react';
import { useNavigate } from 'react-router-dom';
import Icon from '../../../components/AppIcon';

const CourseCard = ({ course }) => {
    const navigate = useNavigate();

    const handleClick = () => {
        navigate(`/course/${course.id}`);
    };

    return (
        <div
            onClick={handleClick}
            className="group bg-surface border border-border rounded-xl overflow-hidden hover:shadow-lg transition-all duration-300 cursor-pointer flex flex-col h-full"
        >
            {/* Header / Color Bar */}
            <div className={`h-24 ${course.color || 'bg-primary-600'} relative p-4 flex flex-col justify-between`}>
                <div className="absolute top-0 right-0 p-2 opacity-50 group-hover:opacity-100 transition-opacity">
                    <Icon name="MoreHorizontal" size={20} color="white" />
                </div>
                <h3 className="text-white font-bold text-lg leading-tight line-clamp-2 drop-shadow-sm">
                    {course.title}
                </h3>
            </div>

            {/* Content Body */}
            <div className="p-5 flex-1 flex flex-col">
                <div className="mb-4">
                    <span className="inline-block px-2.5 py-1 bg-secondary-100 text-secondary-700 text-xs font-medium rounded-md mb-2">
                        {course.code}
                    </span>
                    <p className="text-sm text-text-secondary line-clamp-2">
                        {course.description || 'No description provided.'}
                    </p>
                </div>

                <div className="mt-auto pt-4 border-t border-border flex items-center justify-between text-sm text-text-secondary">
                    <div className="flex items-center space-x-1" title="Students Enrolled">
                        <Icon name="Users" size={16} />
                        <span>{course.studentCount}</span>
                    </div>
                    {course.pendingTasks > 0 && (
                        <div className="flex items-center space-x-1 text-warning-600 font-medium" title="Pending Actions">
                            <Icon name="AlertCircle" size={16} />
                            <span>{course.pendingTasks} Pending</span>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default CourseCard;
