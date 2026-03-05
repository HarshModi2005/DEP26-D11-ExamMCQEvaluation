import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const ProtectedRoute = ({ children }) => {
    const { user, loading, profile } = useAuth();

    console.log('[ProtectedRoute] render — loading:', loading, 'user:', user?.email, 'profile:', profile?.name);

    if (loading) {
        console.log('[ProtectedRoute] showing loading spinner');
        return (
            <div className="min-h-screen bg-background flex items-center justify-center">
                <div className="flex flex-col items-center space-y-4">
                    <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full animate-spin" />
                    <p className="text-text-secondary font-medium">Loading...</p>
                </div>
            </div>
        );
    }

    if (!user) {
        console.log('[ProtectedRoute] no user, redirecting to /login-register');
        return <Navigate to="/login-register" replace />;
    }

    console.log('[ProtectedRoute] user authenticated, rendering children');
    return children;
};

export default ProtectedRoute;
