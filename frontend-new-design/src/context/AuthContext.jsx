import React, { createContext, useContext, useEffect, useState } from 'react';
import { authService } from '../services/authService';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [profile, setProfile] = useState(null);
    const [loading, setLoading] = useState(true);

    const loadProfile = async (userId) => {
        try {
            const profileData = await authService.getProfile(userId);
            setProfile(profileData);
        } catch (err) {
            console.error('Failed to load profile:', err);
            setProfile(null);
        }
    };

    useEffect(() => {
        // On mount: check for existing session
        authService.getSession().then(async (session) => {
            if (session?.user) {
                setUser(session.user);
                await loadProfile(session.user.id);
            }
            setLoading(false);
        });

        // Subscribe to auth changes
        const { data: { subscription } } = authService.onAuthStateChange(
            async (event, session) => {
                if (session?.user) {
                    setUser(session.user);
                    await loadProfile(session.user.id);
                } else {
                    setUser(null);
                    setProfile(null);
                }
                setLoading(false);
            }
        );

        return () => subscription.unsubscribe();
    }, []);

    const login = async (email, password) => {
        const data = await authService.signIn(email, password);
        return data;
    };

    const register = async (email, password, profileData) => {
        const data = await authService.signUp(email, password, profileData);
        return data;
    };

    const logout = async () => {
        await authService.signOut();
        setUser(null);
        setProfile(null);
    };

    const resetPassword = async (email) => {
        await authService.resetPassword(email);
    };

    return (
        <AuthContext.Provider value={{ user, profile, loading, login, register, logout, resetPassword }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
    return ctx;
};
