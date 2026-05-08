import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

console.log('[SupabaseClient] Initializing with URL:', supabaseUrl);
console.log('[SupabaseClient] Anon key present:', !!supabaseAnonKey);

// If VITE_SUPABASE_URL is accidentally set to your FastAPI host (Render, etc.), Auth
// requests hit FastAPI → HTTP 404 → {"detail":"Not Found"} on sign-up / login.
const WRONG_SUPABASE_HOSTS = ['onrender.com', 'vercel.app', 'netlify.app', 'railway.app', 'fly.dev'];
if (supabaseUrl && WRONG_SUPABASE_HOSTS.some((h) => supabaseUrl.includes(h))) {
    console.error(
        '[SupabaseClient] VITE_SUPABASE_URL looks like your app/API host, not Supabase. ' +
            'Use https://<project-ref>.supabase.co here, and put your API URL in VITE_BACKEND_URL only.'
    );
}

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

const authOptions = {
    lock: false,
    debug: true,
};
if (PROJECT_REF) {
    authOptions.storageKey = `sb-${PROJECT_REF}-auth-token`;
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
    auth: authOptions,
});

console.log('[SupabaseClient] Client created successfully');
