import { supabase } from './supabaseClient';

export const authService = {
    /**
     * Sign in with email and password
     */
    async signIn(email, password) {
        const { data, error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) {
            // Make error messages more user-friendly
            if (error.message === 'Invalid login credentials') {
                error.message = 'Invalid email or password. Please check your credentials and try again.';
            } else if (error.message === 'Email not confirmed') {
                error.message = 'Your email is not yet confirmed. Please check your inbox for the confirmation link, or contact your administrator.';
            }
            throw error;
        }
        return data;
    },

    /**
     * Sign up a new user and create their profile via Supabase Auth.
     * The handle_new_user trigger in Supabase will automatically create
     * the profile row in the profiles table.
     * 
     * Returns: { user, session, confirmEmail? }
     *   - If session is non-null: user is auto-confirmed and logged in
     *   - If session is null: email confirmation is required
     */
    async signUp(email, password, { name, role, entryNumber, department }) {
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

        if (error) throw error;
        return data;
    },

    /**
     * Sign out the current user
     */
    async signOut() {
        const { error } = await supabase.auth.signOut();
        if (error) throw error;
    },

    /**
     * Get the current session
     */
    async getSession() {
        const { data: { session } } = await supabase.auth.getSession();
        return session;
    },

    /**
     * Fetch the profile row for a given user ID.
     * Returns null gracefully if the profile doesn't exist yet
     * (e.g. the handle_new_user trigger hasn't completed).
     */
    async getProfile(userId) {
        const { data, error } = await supabase
            .from('profiles')
            .select('*')
            .eq('id', userId)
            .maybeSingle(); // Returns null instead of throwing when no row found
        if (error) {
            console.warn('Error fetching profile:', error.message);
            return null;
        }
        return data;
    },

    /**
     * Subscribe to auth state changes
     */
    onAuthStateChange(callback) {
        return supabase.auth.onAuthStateChange(callback);
    },

    /**
     * Send password reset email
     */
    async resetPassword(email) {
        const { error } = await supabase.auth.resetPasswordForEmail(email, {
            redirectTo: `${window.location.origin}/login-register`,
        });
        if (error) throw error;
    },
};
