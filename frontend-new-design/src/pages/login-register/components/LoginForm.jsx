import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Icon from '../../../components/AppIcon';
import { useAuth } from '../../../context/AuthContext';

const LoginForm = () => {
    const { login, resetPassword } = useAuth();
    const navigate = useNavigate();
    const [formData, setFormData] = useState({ email: '', password: '' });
    const [errors, setErrors] = useState({});
    const [showPassword, setShowPassword] = useState(false);
    const [showForgotPassword, setShowForgotPassword] = useState(false);
    const [resetEmail, setResetEmail] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [resetSent, setResetSent] = useState(false);

    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
        if (errors[name]) setErrors(prev => ({ ...prev, [name]: '' }));
    };

    const validateForm = () => {
        const newErrors = {};
        if (!formData.email) newErrors.email = 'Email is required';
        else if (!/\S+@\S+\.\S+/.test(formData.email)) newErrors.email = 'Please enter a valid email';
        if (!formData.password) newErrors.password = 'Password is required';
        return newErrors;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const newErrors = validateForm();
        if (Object.keys(newErrors).length > 0) { setErrors(newErrors); return; }
        setIsSubmitting(true);
        try {
            await login(formData.email, formData.password);
            navigate('/faculty-dashboard');
        } catch (err) {
            setErrors({ general: err.message || 'Invalid email or password.' });
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleResetSubmit = async (e) => {
        e.preventDefault();
        setIsSubmitting(true);
        try {
            await resetPassword(resetEmail);
            setResetSent(true);
        } catch (err) {
            setErrors({ reset: err.message });
        } finally {
            setIsSubmitting(false);
        }
    };

    if (showForgotPassword) {
        return (
            <div className="space-y-6">
                <div className="text-center">
                    <div className="w-16 h-16 bg-primary-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <Icon name="Mail" size={28} className="text-primary" />
                    </div>
                    <h3 className="text-xl font-semibold text-text-primary mb-2">Reset your password</h3>
                    <p className="text-text-secondary">Enter your email and we'll send a reset link.</p>
                </div>
                {resetSent ? (
                    <div className="p-4 bg-success-50 border border-success-100 rounded-lg text-center">
                        <p className="text-success-700 font-medium">Reset link sent! Check your inbox.</p>
                    </div>
                ) : (
                    <form onSubmit={handleResetSubmit} className="space-y-4">
                        <div>
                            <label htmlFor="resetEmail" className="block text-sm font-medium text-text-primary mb-2">Email address</label>
                            <input
                                type="email" id="resetEmail" required
                                value={resetEmail} onChange={e => setResetEmail(e.target.value)}
                                className="w-full px-4 py-3 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors"
                                placeholder="Enter your email"
                            />
                            {errors.reset && <p className="mt-1 text-sm text-error">{errors.reset}</p>}
                        </div>
                        <button type="submit" disabled={isSubmitting}
                            className="w-full bg-primary text-white py-3 px-4 rounded-lg hover:bg-primary-700 transition-colors font-medium disabled:opacity-50">
                            {isSubmitting ? 'Sending...' : 'Send Reset Link'}
                        </button>
                    </form>
                )}
                <button onClick={() => setShowForgotPassword(false)} className="w-full text-text-secondary hover:text-text-primary transition-colors text-sm">
                    Back to Sign In
                </button>
            </div>
        );
    }

    return (
        <form onSubmit={handleSubmit} className="space-y-6">
            {errors.general && (
                <div className="p-4 bg-error-50 border border-error-100 rounded-lg flex items-center space-x-2">
                    <Icon name="AlertCircle" size={16} className="text-error flex-shrink-0" />
                    <p className="text-sm text-error">{errors.general}</p>
                </div>
            )}

            <div>
                <label htmlFor="email" className="block text-sm font-medium text-text-primary mb-2">Email address</label>
                <div className="relative">
                    <input type="email" id="email" name="email" value={formData.email} onChange={handleInputChange}
                        className={`w-full px-4 py-3 pl-12 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors ${errors.email ? 'border-error' : 'border-border'}`}
                        placeholder="Enter your email" />
                    <Icon name="Mail" size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-secondary-400" />
                </div>
                {errors.email && <p className="mt-1 text-sm text-error flex items-center gap-1"><Icon name="AlertCircle" size={14} />{errors.email}</p>}
            </div>

            <div>
                <label htmlFor="password" className="block text-sm font-medium text-text-primary mb-2">Password</label>
                <div className="relative">
                    <input type={showPassword ? 'text' : 'password'} id="password" name="password"
                        value={formData.password} onChange={handleInputChange}
                        className={`w-full px-4 py-3 pl-12 pr-12 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors ${errors.password ? 'border-error' : 'border-border'}`}
                        placeholder="Enter your password" />
                    <Icon name="Lock" size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-secondary-400" />
                    <button type="button" onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-4 top-1/2 -translate-y-1/2 text-secondary-400 hover:text-text-primary transition-colors">
                        <Icon name={showPassword ? 'EyeOff' : 'Eye'} size={20} />
                    </button>
                </div>
                {errors.password && <p className="mt-1 text-sm text-error flex items-center gap-1"><Icon name="AlertCircle" size={14} />{errors.password}</p>}
            </div>

            <div className="flex items-center justify-end">
                <button type="button" onClick={() => setShowForgotPassword(true)}
                    className="text-sm text-primary hover:text-primary-700 transition-colors">
                    Forgot password?
                </button>
            </div>

            <button type="submit" disabled={isSubmitting}
                className="w-full bg-primary text-white py-3 px-4 rounded-lg hover:bg-primary-700 transition-colors font-medium flex items-center justify-center space-x-2 disabled:opacity-50">
                {isSubmitting ? (
                    <><div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" /><span>Signing in...</span></>
                ) : (
                    <><Icon name="LogIn" size={20} /><span>Sign In</span></>
                )}
            </button>
        </form>
    );
};

export default LoginForm;