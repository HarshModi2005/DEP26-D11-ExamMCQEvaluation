import React from 'react';
import Icon from '../../../components/AppIcon';

const WorkspaceSettings = () => {
    return (
        <div className="bg-surface border border-border rounded-xl p-6">
            <h3 className="text-lg font-medium text-text-primary mb-4 flex items-center">
                <Icon name="Settings" size={20} className="mr-2 text-secondary-500" />
                Workspace Settings
            </h3>

            <div className="space-y-4">
                <div className="flex items-center justify-between p-3 bg-secondary-50 rounded-lg">
                    <div>
                        <p className="text-sm font-medium text-text-primary">Workspace Name</p>
                        <p className="text-xs text-text-secondary">Development Team</p>
                    </div>
                    <button className="text-sm text-primary hover:text-primary-700">Edit</button>
                </div>

                <div className="flex items-center justify-between p-3 bg-secondary-50 rounded-lg">
                    <div>
                        <p className="text-sm font-medium text-text-primary">Default Role</p>
                        <p className="text-xs text-text-secondary">Member</p>
                    </div>
                    <button className="text-sm text-primary hover:text-primary-700">Change</button>
                </div>

                <div className="flex items-center justify-between p-3 bg-secondary-50 rounded-lg">
                    <div>
                        <p className="text-sm font-medium text-text-primary">Visibility</p>
                        <p className="text-xs text-text-secondary">Private</p>
                    </div>
                    <button className="text-sm text-primary hover:text-primary-700">Manage</button>
                </div>
            </div>

            <div className="mt-6 pt-4 border-t border-border">
                <button className="w-full py-2 px-4 border border-error text-error rounded-lg hover:bg-error-50 transition-colors text-sm font-medium flex items-center justify-center">
                    <Icon name="Trash2" size={16} className="mr-2" />
                    Delete Workspace
                </button>
            </div>
        </div>
    );
};

export default WorkspaceSettings;
