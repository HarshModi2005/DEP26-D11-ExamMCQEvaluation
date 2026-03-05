import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import { authService } from '../services/authService';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [profile, setProfile] = useState(null);
    const [loading, setLoading] = useState(true);

    // When true, login/register is in progress — onAuthStateChange should not
    // interfere with state (prevents race conditions that cause redirect loops).
    const authInProgress = useRef(false);

    /**
     * Load the user's profile from the profiles table.
     * Falls back to user_metadata so we ALWAYS end up with a usable profile.
     */
    const loadProfile = useCallback(async (sessionUser) => {
        if (!sessionUser) return;

        const fallbackProfile = {
            id: sessionUser.id,
            name: sessionUser.user_metadata?.name || sessionUser.email?.split('@')[0] || 'User',
            role: sessionUser.user_metadata?.role || 'professor',
            department: sessionUser.user_metadata?.department || '',
            entry_number: sessionUser.user_metadata?.entry_number || '',
        };

        try {
            const profileData = await authService.getProfile(sessionUser.id);
            if (profileData) {
                setProfile({
                    ...profileData,
                    name: profileData.name || fallbackProfile.name,
                    role: profileData.role || fallbackProfile.role,
                });
            } else {
                setProfile(fallbackProfile);
            }
        } catch (err) {
            console.warn('Profile not found in DB, using metadata fallback:', err.message);
            setProfile(fallbackProfile);
        }
    }, []);

    // ── Bootstrap: check existing session on mount ──
    useEffect(() => {
        let mounted = true;

        const initAuth = async () => {
            try {
                // Timeout: if getSession hangs (e.g. stale token), bail after 5s
                const sessionPromise = authService.getSession();
                const timeoutPromise = new Promise((_, reject) =>
                    setTimeout(() => reject(new Error('Session check timed out')), 5000)
                );
                const session = await Promise.race([sessionPromise, timeoutPromise]);
                if (session?.user && mounted) {
                    setUser(session.user);
                    await loadProfile(session.user);
                }
            } catch (err) {
                console.warn('Auth init error (proceeding as logged out):', err.message);
            } finally {
                if (mounted) setLoading(false);
            }
        };

        initAuth();

        // ── Listen for auth events (sign in from other tab, token refresh, etc.) ──
        const { data: { subscription } } = authService.onAuthStateChange(
            async (event, session) => {
                if (!mounted) return;

                // Don't interfere when login() or register() is handling things
                if (authInProgress.current) return;

                if (event === 'SIGNED_IN' && session?.user) {
                    setUser(session.user);
                    await loadProfile(session.user);
                    setLoading(false);
                } else if (event === 'SIGNED_OUT') {
                    setUser(null);
                    setProfile(null);
                    setLoading(false);
                } else if (event === 'TOKEN_REFRESHED' && session?.user) {
                    // Just update the user object (new JWT), don't reload profile
                    setUser(session.user);
                }
            }
        );

        return () => {
            mounted = false;
            subscription.unsubscribe();
        };
    }, [loadProfile]);

    // ── Login ──
    const login = async (email, password) => {
        authInProgress.current = true;
        setLoading(true);
        try {
            const data = await authService.signIn(email, password);
            if (data?.user) {
                setUser(data.user);
                await loadProfile(data.user);
            }
            return data;
        } finally {
            setLoading(false);
            authInProgress.current = false;
        }
    };

    // ── Register ──
    const register = async (email, password, profileData) => {
        authInProgress.current = true;
        setLoading(true);
        try {
            const data = await authService.signUp(email, password, profileData);

            // No session = email confirmation required
            if (!data?.session) {
                setLoading(false);
                authInProgress.current = false;
                return { ...data, confirmEmail: true };
            }

            // Auto-confirmed: user is signed in immediately
            if (data?.user) {
                setUser(data.user);
                // Brief delay so the handle_new_user DB trigger can create the profile row
                await new Promise(r => setTimeout(r, 800));
                await loadProfile(data.user);
            }
            return data;
        } finally {
            setLoading(false);
            authInProgress.current = false;
        }
    };

    // ── Logout ──
    const logout = async () => {
        authInProgress.current = true;
        try {
            await authService.signOut();
            setUser(null);
            setProfile(null);
        } finally {
            authInProgress.current = false;
        }
    };

    // ── Password Reset ──
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
