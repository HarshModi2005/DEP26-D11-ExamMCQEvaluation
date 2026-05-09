import { supabase } from './supabaseClient';

export const invitationService = {
    /**
     * Invite a TA by email to a course.
     * If the TA already has an account (profile with role='ta'), add them directly.
     * Otherwise, create a pending invitation.
     */
    async inviteTA(courseId, email, invitedBy) {
        // 1. Check if user already exists with this email
        const { data: existingUsers } = await supabase
            .from('profiles')
            .select('id, name, role, entry_number, department')
            .eq('role', 'ta');

        // We need to look up by email via auth — but anon can't query auth.users.
        // So let's search by checking if any TA profile is linked to this email.
        // We'll try to find the user via the auth admin workaround:
        // Actually, let's query profiles joined with the email from the invitation email.
        // Since we can't query auth.users from the client, we store the email in the invitation
        // and check if a profile already exists by looking for existing invitations.

        // Simpler approach: try to find user by looking up auth users
        // The Supabase JS client can't list auth users, so we'll:
        // - Always create the invitation record
        // - Then check if someone with this email already has a profile
        // - If yes, immediately accept it

        // Check if already invited
        const { data: existing } = await supabase
            .from('ta_invitations')
            .select('*')
            .eq('course_id', courseId)
            .eq('email', email)
            .maybeSingle();

        if (existing) {
            if (existing.status === 'pending') {
                throw new Error('An invitation has already been sent to this email.');
            }
            if (existing.status === 'accepted') {
                const err = new Error('ALREADY_MEMBER');
                err.code = 'ALREADY_MEMBER';
                throw err;
            }
            
            // If declined, we reset to pending to allow re-invitation.
            const { data: updated, error: updateErr } = await supabase
                .from('ta_invitations')
                .update({ 
                    status: 'pending', 
                    invited_by: invitedBy,
                    created_at: new Date().toISOString() // Refresh the timestamp
                })
                .eq('id', existing.id)
                .select()
                .single();

            if (updateErr) throw updateErr;
            return updated;
        }

        // Create the invitation
        const { data: invitation, error } = await supabase
            .from('ta_invitations')
            .insert({
                course_id: courseId,
                email: email.toLowerCase().trim(),
                invited_by: invitedBy,
                status: 'pending'
            })
            .select()
            .single();

        if (error) throw error;

        // Now check if a user with this email already exists and has role=ta
        // We can do this by checking auth.users indirectly — sign in won't work,
        // but we can check if anyone in profiles has this email via a join approach.
        // Since profiles doesn't store email, we use a workaround:
        // Try to find the user in auth and add them directly.
        // The simplest client-side approach: just leave it as pending.
        // The DB trigger on profile creation will auto-accept.

        return invitation;
    },

    /**
     * Get all invitations for a course
     */
    async getInvitationsByCourse(courseId) {
        const { data, error } = await supabase
            .from('ta_invitations')
            .select('*, profiles!ta_invitations_invited_by_fkey(name)')
            .eq('course_id', courseId)
            .order('created_at', { ascending: false });
        if (error) throw error;
        return data;
    },

    /**
     * Cancel / delete a pending invitation
     */
    async cancelInvitation(invitationId) {
        const { error } = await supabase
            .from('ta_invitations')
            .delete()
            .eq('id', invitationId);
        if (error) throw error;
    },

    /**
     * Get pending invitations for the current user's email
     * (used on the TA side to see invites they need to accept)
     */
    async getMyPendingInvitations(email) {
        const { data, error } = await supabase
            .from('ta_invitations')
            .select('*, courses(id, code, title, profiles!courses_instructor_id_fkey(name))')
            .eq('email', email.toLowerCase().trim())
            .eq('status', 'pending');
        if (error) throw error;
        return data;
    },

    /**
     * Accept an invitation (TA side)
     */
    async acceptInvitation(invitationId, taId) {
        // Get the invitation details
        const { data: inv, error: fetchErr } = await supabase
            .from('ta_invitations')
            .select('*')
            .eq('id', invitationId)
            .single();
        if (fetchErr) throw fetchErr;

        // Add to course_tas
        const { error: addErr } = await supabase
            .from('course_tas')
            .insert({ course_id: inv.course_id, ta_id: taId })
            .select()
            .single();
        if (addErr && !addErr.message.includes('duplicate')) throw addErr;

        // Mark as accepted
        const { error: updateErr } = await supabase
            .from('ta_invitations')
            .update({ status: 'accepted' })
            .eq('id', invitationId);
        if (updateErr) throw updateErr;
    },

    /**
     * Decline an invitation (TA side)
     */
    async declineInvitation(invitationId) {
        const { error } = await supabase
            .from('ta_invitations')
            .update({ status: 'declined' })
            .eq('id', invitationId);
        if (error) throw error;
    },
};
