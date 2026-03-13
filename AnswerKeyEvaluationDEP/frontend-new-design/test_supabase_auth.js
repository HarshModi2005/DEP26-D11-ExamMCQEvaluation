import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';
dotenv.config();

const supabaseUrl = process.env.VITE_SUPABASE_URL;
const supabaseKey = process.env.VITE_SUPABASE_ANON_KEY;

console.log('URL:', supabaseUrl ? 'Found' : 'Missing');
console.log('KEY:', supabaseKey ? 'Found' : 'Missing');

if (!supabaseUrl || !supabaseKey) {
  console.error("Missing credentials in .env");
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseKey);

async function testAuth() {
  console.log('--- Testing Registration ---');
  const testEmail = `test_${Date.now()}@example.com`;
  
  const { data: signUpData, error: signUpError } = await supabase.auth.signUp({
    email: testEmail,
    password: 'password123',
    options: {
      data: {
        name: 'Test Agent',
        role: 'professor',
      }
    }
  });

  if (signUpError) {
    console.error('Registration Error:', signUpError.message);
  } else {
    console.log('Registration Success!');
    console.log('User ID:', signUpData.user?.id);
  }

  console.log('\n--- Testing Login ---');
  // I will test logging in with a completely invalid user to see if the API actually responds, 
  // or if there is a network/CORS/credential issue.
  const { data: signInData, error: signInError } = await supabase.auth.signInWithPassword({
    email: 'nonexistent_user_999@example.com',
    password: 'wrongpassword'
  });

  if (signInError) {
    if (signInError.message.includes('Invalid login credentials')) {
         console.log('Login API is working correctly (returned Invalid credentials for fake user)');
    } else {
         console.error('Login API Error:', signInError.message);
    }
  } else {
    console.log('Login Success (Unexpected!)');
  }
}

testAuth();
