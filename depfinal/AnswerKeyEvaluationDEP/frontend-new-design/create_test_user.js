#!/usr/bin/env node

/**
 * Create a pre-confirmed test user in Supabase.
 * 
 * Usage:
 *   node create_test_user.js <SERVICE_ROLE_KEY>
 *   OR set SUPABASE_SERVICE_ROLE_KEY in .env
 * 
 * The service_role key is found in: Supabase Dashboard → Settings → API
 */

import 'dotenv/config';

const SUPABASE_URL = process.env.VITE_SUPABASE_URL;
const SERVICE_ROLE_KEY = process.argv[2] || process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!SUPABASE_URL) {
    console.error('❌ Missing VITE_SUPABASE_URL in .env');
    process.exit(1);
}

if (!SERVICE_ROLE_KEY) {
    console.error('');
    console.error('╔══════════════════════════════════════════════════════════╗');
    console.error('║  SUPABASE SERVICE ROLE KEY REQUIRED                     ║');
    console.error('╠══════════════════════════════════════════════════════════╣');
    console.error('║                                                          ║');
    console.error('║  1. Go to: https://supabase.com/dashboard               ║');
    console.error('║  2. Select your project                                  ║');
    console.error('║  3. Go to: Settings → API                               ║');
    console.error('║  4. Copy the "service_role" secret key                   ║');
    console.error('║  5. Run: node create_test_user.js <PASTE_KEY_HERE>       ║');
    console.error('║                                                          ║');
    console.error('║  ─── OR (easier) ───                                     ║');
    console.error('║                                                          ║');
    console.error('║  Disable email confirmation for development:             ║');
    console.error('║  1. Go to: Supabase Dashboard → Authentication           ║');
    console.error('║  2. Click: Providers → Email                             ║');
    console.error('║  3. Turn OFF "Confirm email"                             ║');
    console.error('║  4. Save → Now signup works instantly!                   ║');
    console.error('║                                                          ║');
    console.error('╚══════════════════════════════════════════════════════════╝');
    console.error('');
    process.exit(1);
}

async function createUser({ email, password, name, role, department, entry_number }) {
    console.log(`Creating: ${email} (${role})...`);

    const res = await fetch(`${SUPABASE_URL}/auth/v1/admin/users`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${SERVICE_ROLE_KEY}`,
            'apikey': SERVICE_ROLE_KEY,
        },
        body: JSON.stringify({
            email,
            password,
            email_confirm: true,
            user_metadata: { name, role, department, entry_number },
        }),
    });

    const result = await res.json();
    if (!res.ok) {
        if (JSON.stringify(result).includes('already been registered')) {
            console.log(`  ℹ️  ${email} already exists.`);
            return;
        }
        console.error(`  ❌ Failed:`, result.msg || result.message || JSON.stringify(result));
        return;
    }
    console.log(`  ✅ Created! (ID: ${result.id})`);
}

async function main() {
    console.log('');
    console.log('🔧 Creating test users...');
    console.log(`   Project: ${SUPABASE_URL}`);
    console.log('');

    await createUser({
        email: 'professor@evaldep.test',
        password: 'Professor123!',
        name: 'Dr. Test Professor',
        role: 'professor',
        department: 'Computer Science',
    });

    await createUser({
        email: 'ta@evaldep.test',
        password: 'TA123456!',
        name: 'Test TA',
        role: 'ta',
        department: 'Computer Science',
        entry_number: '2023CSB1099',
    });

    console.log('');
    console.log('┌──────────────────────────────────────────┐');
    console.log('│  Test Credentials                        │');
    console.log('├──────────────────────────────────────────┤');
    console.log('│  Professor: professor@evaldep.test       │');
    console.log('│  Password:  Professor123!                │');
    console.log('│                                          │');
    console.log('│  TA:        ta@evaldep.test              │');
    console.log('│  Password:  TA123456!                    │');
    console.log('└──────────────────────────────────────────┘');
    console.log('');
}

main().catch(console.error);
