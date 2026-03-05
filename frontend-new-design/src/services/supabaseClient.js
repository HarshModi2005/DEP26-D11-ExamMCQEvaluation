import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

console.log('[SupabaseClient] Initializing with URL:', supabaseUrl);
console.log('[SupabaseClient] Anon key present:', !!supabaseAnonKey);

// Clean up stale auth tokens from other Supabase projects.
// These cause getSession() to hang trying to refresh tokens against the wrong project.
const PROJECT_REF = supabaseUrl?.match(/https:\/\/(.+)\.supabase\.co/)?.[1];
console.log('[SupabaseClient] Project ref:', PROJECT_REF);

if (PROJECT_REF) {
    Object.keys(localStorage).forEach(key => {
        if (key.startsWith('sb-') && key.endsWith('-auth-token') && !key.includes(PROJECT_REF)) {
            console.warn(`[SupabaseClient] Removing stale auth token from different project: ${key}`);
            localStorage.removeItem(key);
        }
    });
}

// List all sb- keys in localStorage for debugging
const sbKeys = Object.keys(localStorage).filter(k => k.startsWith('sb-'));
console.log('[SupabaseClient] All sb- localStorage keys:', sbKeys);

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
    auth: {
        // Disable lock — this prevents the "Lock broken by another request with the 'steal' option" error
        // See: https://github.com/supabase/supabase-js/issues/
        lock: false,
        storageKey: `sb-${PROJECT_REF}-auth-token`,
        debug: true, // Enable Supabase auth debug logging
    }
});

console.log('[SupabaseClient] Client created successfully');
