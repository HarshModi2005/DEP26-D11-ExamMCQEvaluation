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
    const loadProfile = useCallback(async (sessionUser, retries = 3) => {
        console.log('[AuthContext] loadProfile called for:', sessionUser?.email, 'retries:', retries);
        if (!sessionUser) {
            console.log('[AuthContext] loadProfile — no sessionUser, returning');
            return;
        }

        const fallbackProfile = {
            id: sessionUser.id,
            name: sessionUser.user_metadata?.name || sessionUser.email?.split('@')[0] || 'User',
            role: sessionUser.user_metadata?.role || 'professor',
            department: sessionUser.user_metadata?.department || '',
            entry_number: sessionUser.user_metadata?.entry_number || '',
        };

        for (let i = 0; i < retries; i++) {
            try {
                console.log(`[AuthContext] loadProfile attempt ${i + 1}/${retries}`);
                const profileData = await authService.getProfile(sessionUser.id);
                if (profileData) {
                    console.log('[AuthContext] loadProfile SUCCESS — got profile from DB:', profileData.name, profileData.role);
                    setProfile({
                        ...profileData,
                        name: profileData.name || fallbackProfile.name,
                        role: profileData.role || fallbackProfile.role,
                    });
                    return; // Success, exit the loop
                }
                console.log('[AuthContext] loadProfile — profile was null from DB');
            } catch (err) {
                console.warn(`[AuthContext] Profile fetch attempt ${i + 1} failed:`, err.message);
            }
            // Wait slightly before retrying (exponential backoff)
            if (i < retries - 1) {
                const delay = 500 * (i + 1);
                console.log(`[AuthContext] waiting ${delay}ms before retry...`);
                await new Promise(r => setTimeout(r, delay));
            }
        }

        // If all retries fail, use fallback immediately to unblock UI
        console.warn('[AuthContext] Profile not found in DB after retries, using metadata fallback:', fallbackProfile);
        setProfile(fallbackProfile);
    }, []);

    // ── Bootstrap: check existing session on mount ──
    useEffect(() => {
        let mounted = true;
        console.log('[AuthContext] Bootstrap useEffect running');

        const initAuth = async () => {
            console.log('[AuthContext] initAuth starting...');
            try {
                // Timeout: if getSession hangs (e.g. stale token), bail after 5s
                const sessionPromise = authService.getSession();
                const timeoutPromise = new Promise((_, reject) =>
                    setTimeout(() => reject(new Error('Session check timed out')), 5000)
                );
                const session = await Promise.race([sessionPromise, timeoutPromise]);
                console.log('[AuthContext] initAuth got session:', !!session, 'user:', session?.user?.email);
                if (session?.user && mounted) {
                    setUser(session.user);
                    await loadProfile(session.user);
                } else {
                    console.log('[AuthContext] initAuth — no session or unmounted');
                }
            } catch (err) {
                console.warn('[AuthContext] Auth init error (proceeding as logged out):', err.message);
            } finally {
                if (mounted) {
                    console.log('[AuthContext] initAuth complete, setting loading=false');
                    setLoading(false);
                }
            }
        };

        initAuth();

        // ── Listen for auth events (sign in from other tab, token refresh, etc.) ──
        const { data: { subscription } } = authService.onAuthStateChange(
            async (event, session) => {
                console.log('[AuthContext] onAuthStateChange:', event, 'mounted:', mounted, 'authInProgress:', authInProgress.current);
                if (!mounted) return;

                // Don't interfere when login() or register() is handling things
                if (authInProgress.current) {
                    console.log('[AuthContext] onAuthStateChange — SKIPPING (authInProgress=true)');
                    return;
                }

                if (event === 'SIGNED_IN' && session?.user) {
                    console.log('[AuthContext] onAuthStateChange — SIGNED_IN, loading profile...');
                    setUser(session.user);
                    await loadProfile(session.user);
                    setLoading(false);
                } else if (event === 'SIGNED_OUT') {
                    console.log('[AuthContext] onAuthStateChange — SIGNED_OUT');
                    setUser(null);
                    setProfile(null);
                    setLoading(false);
                } else if (event === 'TOKEN_REFRESHED' && session?.user) {
                    console.log('[AuthContext] onAuthStateChange — TOKEN_REFRESHED');
                    setUser(session.user);
                }
            }
        );

        return () => {
            console.log('[AuthContext] Bootstrap cleanup, setting mounted=false');
            mounted = false;
            subscription.unsubscribe();
        };
    }, [loadProfile]);

    // ── Login ──
    const login = async (email, password) => {
        console.log('[AuthContext] login called for:', email);
        authInProgress.current = true;
        setLoading(true);
        try {
            const data = await authService.signIn(email, password);
            if (data?.user) {
                console.log('[AuthContext] login — signIn success, setting user and loading profile...');
                setUser(data.user);
                await loadProfile(data.user);
            }
            console.log('[AuthContext] login complete');
            return data;
        } finally {
            setLoading(false);
            authInProgress.current = false;
        }
    };

    // ── Register ──
    const register = async (email, password, profileData) => {
        console.log('[AuthContext] register called for:', email);
        authInProgress.current = true;
        setLoading(true);
        try {
            const data = await authService.signUp(email, password, profileData);

            // No session = email confirmation required
            if (!data?.session) {
                console.log('[AuthContext] register — no session, email confirmation required');
                setLoading(false);
                authInProgress.current = false;
                return { ...data, confirmEmail: true };
            }

            // Auto-confirmed: user is signed in immediately
            if (data?.user) {
                console.log('[AuthContext] register — auto-confirmed, loading profile...');
                setUser(data.user);
                await loadProfile(data.user, 3);
            }
            console.log('[AuthContext] register complete');
            return data;
        } catch (error) {
            console.error('[AuthContext] register error:', error.message);
            setLoading(false);
            authInProgress.current = false;
            throw error;
        } finally {
            setLoading(false);
            authInProgress.current = false;
        }
    };

    // ── Logout ──
    const logout = async () => {
        console.log('[AuthContext] logout called');
        authInProgress.current = true;
        try {
            await authService.signOut();
            setUser(null);
            setProfile(null);
            console.log('[AuthContext] logout complete');
        } finally {
            authInProgress.current = false;
        }
    };

    // ── Password Reset ──
    const resetPassword = async (email) => {
        console.log('[AuthContext] resetPassword called for:', email);
        await authService.resetPassword(email);
    };

    console.log('[AuthContext] render — user:', user?.email, 'profile:', profile?.name, 'loading:', loading);

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
