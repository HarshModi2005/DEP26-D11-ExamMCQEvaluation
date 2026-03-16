import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Icon from '../AppIcon';
import { useAuth } from '../../context/AuthContext';

const LogoutModal = ({ onConfirm, onClose }) => {
    return (
        <div className="fixed inset-0 z-[200] bg-black bg-opacity-50 flex items-center justify-center p-4">
            <div className="bg-surface rounded-2xl shadow-2xl w-full max-w-sm border border-border">
                <div className="p-8 text-center">
                    <h2 className="text-2xl font-semibold text-text-primary mb-6">Want to Log out??</h2>
                    <div className="flex flex-col gap-3">
                        <button onClick={onConfirm}
                            className="w-full py-3 bg-error text-white rounded-xl hover:bg-error-700 transition-colors font-semibold text-lg shadow-sm">
                            Log out
                        </button>
                        <button onClick={onClose}
                            className="w-full py-3 border border-border text-text-secondary rounded-xl hover:bg-secondary-50 transition-colors font-medium">
                            cancel
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

const Header = () => {
    const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
    const [showLogoutModal, setShowLogoutModal] = useState(false);
    const { profile, user, logout } = useAuth();
    const navigate = useNavigate();

    const displayName = profile?.name || user?.email?.split('@')[0] || 'User';

    const initials = displayName
        .split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase();

    const handleLogout = () => {
        setIsUserMenuOpen(false);
        setShowLogoutModal(true);
    };

    const confirmLogout = async () => {
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
                                <p className="text-sm font-medium text-text-primary leading-tight">{displayName}</p>
                                <p className="text-xs text-text-secondary capitalize">{profile?.role || user?.email || ''}</p>
                            </div>
                            <Icon name="ChevronDown" size={16} color="#64748B" />
                        </button>

                        {/* Dropdown */}
                        {isUserMenuOpen && (
                            <div className="absolute right-0 top-12 w-56 bg-surface border border-border rounded-lg shadow-xl z-150">
                                <div className="p-3 border-b border-border">
                                    <p className="text-sm font-semibold text-text-primary">{displayName}</p>
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

            {showLogoutModal && (
                <LogoutModal
                    onConfirm={confirmLogout}
                    onClose={() => setShowLogoutModal(false)}
                />
            )}
        </header>
    );
};

export default Header;