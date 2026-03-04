import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Icon from '../AppIcon';
import { useAuth } from '../../context/AuthContext';

const Header = () => {
    const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
    const { profile, user, logout } = useAuth();
    const navigate = useNavigate();

    const initials = profile?.name
        ? profile.name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()
        : '??';

    const handleLogout = async () => {
        await logout();
        navigate('/login-register');
    };

    return (
        <header className="fixed top-0 left-0 right-0 h-16 bg-surface border-b border-border z-100">
            <div className="flex items-center justify-between h-full px-6">
                {/* Left Section - Brand */}
                <div className="flex items-center space-x-3">
                    <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center shadow-sm">
                        <Icon name="GraduationCap" size={18} color="white" />
                    </div>
                    <div className="hidden sm:block">
                        <h1 className="text-lg font-bold text-text-primary">EvalDEP</h1>
                        <p className="text-xs text-text-secondary">Evaluation Platform</p>
                    </div>
                </div>

                {/* Center Section - Search hint */}
                <div className="flex-1 max-w-md mx-8 hidden md:block">
                    <div className="w-full bg-secondary-50 border border-border rounded-lg px-4 py-2 flex items-center space-x-3 cursor-text">
                        <Icon name="Search" size={16} color="#94a3b8" />
                        <span className="text-sm text-secondary-400">Navigate to course, evaluation...</span>
                    </div>
                </div>

                {/* Right Section - User */}
                <div className="flex items-center space-x-3">
                    {/* User Menu */}
                    <div className="relative">
                        <button
                            onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
                            className="flex items-center space-x-3 px-3 py-2 hover:bg-secondary-100 rounded-lg transition-colors duration-200"
                        >
                            <div className="w-8 h-8 bg-primary-100 rounded-full flex items-center justify-center">
                                <span className="text-sm font-semibold text-primary-700">{initials}</span>
                            </div>
                            <div className="hidden md:block text-left">
                                <p className="text-sm font-medium text-text-primary leading-tight">{profile?.name || 'Loading...'}</p>
                                <p className="text-xs text-text-secondary capitalize">{profile?.role || user?.email || ''}</p>
                            </div>
                            <Icon name="ChevronDown" size={16} color="#64748B" />
                        </button>

                        {/* Dropdown */}
                        {isUserMenuOpen && (
                            <div className="absolute right-0 top-12 w-56 bg-surface border border-border rounded-lg shadow-xl z-150">
                                <div className="p-3 border-b border-border">
                                    <p className="text-sm font-semibold text-text-primary">{profile?.name}</p>
                                    <p className="text-xs text-text-secondary capitalize">{profile?.role} {profile?.department ? `• ${profile.department}` : ''}</p>
                                    {profile?.entry_number && (
                                        <p className="text-xs text-text-secondary font-mono mt-0.5">{profile.entry_number}</p>
                                    )}
                                </div>
                                <div className="py-2">
                                    <button
                                        onClick={() => navigate('/faculty-dashboard')}
                                        className="w-full px-4 py-2 text-left text-sm text-text-primary hover:bg-secondary-50 transition-colors flex items-center space-x-3">
                                        <Icon name="BookOpen" size={16} />
                                        <span>My Courses</span>
                                    </button>
                                </div>
                                <div className="border-t border-border py-2">
                                    <button
                                        onClick={handleLogout}
                                        className="w-full px-4 py-2 text-left text-sm text-error hover:bg-error-50 transition-colors flex items-center space-x-3">
                                        <Icon name="LogOut" size={16} />
                                        <span>Sign Out</span>
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Click outside handler */}
            {isUserMenuOpen && (
                <div className="fixed inset-0 z-90" onClick={() => setIsUserMenuOpen(false)} />
            )}
        </header>
    );
};

export default Header;