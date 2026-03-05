import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

// Clean up stale auth tokens from other Supabase projects.
// These cause getSession() to hang trying to refresh tokens against the wrong project.
const PROJECT_REF = supabaseUrl?.match(/https:\/\/(.+)\.supabase\.co/)?.[1];
if (PROJECT_REF) {
    Object.keys(localStorage).forEach(key => {
        if (key.startsWith('sb-') && key.endsWith('-auth-token') && !key.includes(PROJECT_REF)) {
            console.warn(`Removing stale auth token from different project: ${key}`);
            localStorage.removeItem(key);
        }
    });
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
