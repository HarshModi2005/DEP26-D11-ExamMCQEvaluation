import { supabase } from './supabaseClient';

export const authService = {
    /**
     * Sign in with email and password
     */
    async signIn(email, password) {
        console.log('[AuthService] signIn called for:', email);
        const { data, error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) {
            console.error('[AuthService] signIn error:', error.message);
            // Make error messages more user-friendly
            if (error.message === 'Invalid login credentials') {
                error.message = 'Invalid email or password. Please check your credentials and try again.';
            } else if (error.message === 'Email not confirmed') {
                error.message = 'Your email is not yet confirmed. Please check your inbox for the confirmation link, or contact your administrator.';
            }
            throw error;
        }
        console.log('[AuthService] signIn success, user id:', data?.user?.id);
        return data;
    },

    /**
     * Sign up a new user and create their profile via Supabase Auth.
     */
    async signUp(email, password, { name, role, entryNumber, department }) {
        console.log('[AuthService] signUp called for:', email, 'role:', role);
        const { data, error } = await supabase.auth.signUp({
            email,
            password,
            options: {
                data: {
                    name,
                    role,
                    entry_number: entryNumber || null,
                    department: department || null,
                }
            }
        });

        if (error) {
            console.error('[AuthService] signUp error:', error.message);
            throw error;
        }
        console.log('[AuthService] signUp success, user id:', data?.user?.id, 'session:', !!data?.session);

        // DECOUPLED PROFILE CREATION
        if (data?.user) {
            console.log('[AuthService] Inserting profile row asynchronously...');
            supabase.from('profiles').insert([{
                id: data.user.id,
                name: name || email.split('@')[0] || 'User',
                role: role || 'professor',
                entry_number: entryNumber || null,
                department: department || null,
            }]).then(({ error: profileError }) => {
                if (profileError) {
                    console.warn("[AuthService] Manual profile creation failed or skipped:", profileError);
                } else {
                    console.log('[AuthService] Profile row inserted successfully');
                }
            });
        }

        return data;
    },

    /**
     * Sign out the current user
     */
    async signOut() {
        console.log('[AuthService] signOut called');
        const { error } = await supabase.auth.signOut();
        if (error) {
            console.error('[AuthService] signOut error:', error.message);
            throw error;
        }
        console.log('[AuthService] signOut success');
    },

    /**
     * Get the current session
     */
    async getSession() {
        console.log('[AuthService] getSession called');
        const startTime = Date.now();
        const { data: { session } } = await supabase.auth.getSession();
        const elapsed = Date.now() - startTime;
        console.log('[AuthService] getSession completed in', elapsed, 'ms, session:', !!session, 'user:', session?.user?.email);
        return session;
    },

    /**
     * Fetch the profile row for a given user ID.
     */
    async getProfile(userId) {
        console.log('[AuthService] getProfile called for userId:', userId);
        const startTime = Date.now();
        const { data, error } = await supabase
            .from('profiles')
            .select('*')
            .eq('id', userId)
            .maybeSingle();
        const elapsed = Date.now() - startTime;
        if (error) {
            console.warn('[AuthService] getProfile error after', elapsed, 'ms:', error.message);
            return null;
        }
        console.log('[AuthService] getProfile success after', elapsed, 'ms, profile:', data?.name, 'role:', data?.role);
        return data;
    },

    /**
     * Subscribe to auth state changes
     */
    onAuthStateChange(callback) {
        console.log('[AuthService] Setting up onAuthStateChange listener');
        return supabase.auth.onAuthStateChange((event, session) => {
            console.log('[AuthService] onAuthStateChange event:', event, 'session:', !!session, 'user:', session?.user?.email);
            callback(event, session);
        });
    },

    /**
     * Send password reset email
     */
    async resetPassword(email) {
        console.log('[AuthService] resetPassword called for:', email);
        const { error } = await supabase.auth.resetPasswordForEmail(email, {
            redirectTo: `${window.location.origin}/login-register`,
        });
        if (error) {
            console.error('[AuthService] resetPassword error:', error.message);
            throw error;
        }
        console.log('[AuthService] resetPassword email sent');
    },
};
