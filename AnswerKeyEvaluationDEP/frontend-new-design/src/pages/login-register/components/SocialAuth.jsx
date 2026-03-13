import React from 'react';
import Icon from '../../../components/AppIcon';

const SocialAuth = ({ onSuccess }) => {
    const handleSocialLogin = (provider) => {
        // Simulate social authentication
        console.log(`Authenticating with ${provider}`);
        setTimeout(() => {
            onSuccess();
        }, 1000);
    };

    return (
        <div className="mt-8">
            {/* Divider */}
            <div className="relative my-6">
                <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-border" />
                </div>
                <div className="relative flex justify-center text-sm">
                    <span className="px-4 bg-surface text-text-secondary">Or continue with</span>
                </div>
            </div>

            {/* Social Login Buttons */}
            <div className="space-y-3">
                <button
                    onClick={() => handleSocialLogin('Google')}
                    className="w-full flex items-center justify-center space-x-3 px-4 py-3 border border-border rounded-lg hover:bg-secondary-50 transition-colors duration-200"
                >
                    <div className="w-5 h-5 bg-red-500 rounded-full flex items-center justify-center">
                        <span className="text-white text-xs font-bold">G</span>
                    </div>
                    <span className="text-text-primary font-medium">Continue with Google</span>
                </button>

                <button
                    onClick={() => handleSocialLogin('GitHub')}
                    className="w-full flex items-center justify-center space-x-3 px-4 py-3 border border-border rounded-lg hover:bg-secondary-50 transition-colors duration-200"
                >
                    <Icon name="Github" size={20} color="#24292e" />
                    <span className="text-text-primary font-medium">Continue with GitHub</span>
                </button>
            </div>

            {/* Additional Info */}
            <div className="mt-6 text-center">
                <p className="text-xs text-text-secondary">
                    Secure authentication powered by industry-standard OAuth 2.0
                </p>
            </div>
        </div>
    );
};

export default SocialAuth;