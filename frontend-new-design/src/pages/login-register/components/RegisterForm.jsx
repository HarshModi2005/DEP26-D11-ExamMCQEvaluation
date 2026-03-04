import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Icon from '../../../components/AppIcon';
import { useAuth } from '../../../context/AuthContext';

const RegisterForm = () => {
    const { register } = useAuth();
    const navigate = useNavigate();
    const [formData, setFormData] = useState({
        firstName: '', lastName: '', email: '', password: '', confirmPassword: '',
        role: 'ta', entryNumber: '', department: '', agreeToTerms: false,
    });
    const [errors, setErrors] = useState({});
    const [showPassword, setShowPassword] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [passwordStrength, setPasswordStrength] = useState({ score: 0, feedback: [] });

    const handleInputChange = (e) => {
        const { name, value, type, checked } = e.target;
        setFormData(prev => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));
        if (errors[name]) setErrors(prev => ({ ...prev, [name]: '' }));
        if (name === 'password') checkPasswordStrength(value);
    };

    const checkPasswordStrength = (password) => {
        const feedback = [];
        let score = 0;
        if (password.length >= 8) score++; else feedback.push('At least 8 characters');
        if (/[A-Z]/.test(password)) score++; else feedback.push('One uppercase letter');
        if (/[a-z]/.test(password)) score++; else feedback.push('One lowercase letter');
        if (/\d/.test(password)) score++; else feedback.push('One number');
        if (/[!@#$%^&*]/.test(password)) score++; else feedback.push('One special character');
        setPasswordStrength({ score, feedback });
    };

    const strengthColor = () => {
        if (passwordStrength.score <= 1) return 'bg-error';
        if (passwordStrength.score <= 3) return 'bg-warning';
        return 'bg-success';
    };

    const strengthLabel = () => {
        if (passwordStrength.score <= 1) return 'Weak';
        if (passwordStrength.score <= 3) return 'Medium';
        return 'Strong';
    };

    const validateForm = () => {
        const newErrors = {};
        if (!formData.firstName.trim()) newErrors.firstName = 'Required';
        if (!formData.lastName.trim()) newErrors.lastName = 'Required';
        if (!formData.email) newErrors.email = 'Email is required';
        else if (!/\S+@\S+\.\S+/.test(formData.email)) newErrors.email = 'Invalid email';
        if (!formData.password) newErrors.password = 'Password is required';
        else if (passwordStrength.score < 3) newErrors.password = 'Password is too weak';
        if (formData.password !== formData.confirmPassword) newErrors.confirmPassword = 'Passwords do not match';
        if (formData.role === 'ta' && !formData.entryNumber.trim()) newErrors.entryNumber = 'Entry number is required for TAs';
        if (!formData.agreeToTerms) newErrors.agreeToTerms = 'You must agree to the terms';
        return newErrors;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const newErrors = validateForm();
        if (Object.keys(newErrors).length > 0) { setErrors(newErrors); return; }
        setIsSubmitting(true);
        try {
            await register(formData.email, formData.password, {
                name: `${formData.firstName} ${formData.lastName}`,
                role: formData.role,
                entryNumber: formData.entryNumber,
                department: formData.department,
            });
            navigate('/faculty-dashboard');
        } catch (err) {
            setErrors({ general: err.message || 'Registration failed. Please try again.' });
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <form onSubmit={handleSubmit} className="space-y-5">
            {errors.general && (
                <div className="p-4 bg-error-50 border border-error-100 rounded-lg flex items-center space-x-2">
                    <Icon name="AlertCircle" size={16} className="text-error flex-shrink-0" />
                    <p className="text-sm text-error">{errors.general}</p>
                </div>
            )}

            {/* Name */}
            <div className="grid grid-cols-2 gap-4">
                <div>
                    <label htmlFor="firstName" className="block text-sm font-medium text-text-primary mb-1">First name</label>
                    <input type="text" id="firstName" name="firstName" value={formData.firstName} onChange={handleInputChange}
                        className={`w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors ${errors.firstName ? 'border-error' : 'border-border'}`}
                        placeholder="John" />
                    {errors.firstName && <p className="mt-1 text-xs text-error">{errors.firstName}</p>}
                </div>
                <div>
                    <label htmlFor="lastName" className="block text-sm font-medium text-text-primary mb-1">Last name</label>
                    <input type="text" id="lastName" name="lastName" value={formData.lastName} onChange={handleInputChange}
                        className={`w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors ${errors.lastName ? 'border-error' : 'border-border'}`}
                        placeholder="Doe" />
                    {errors.lastName && <p className="mt-1 text-xs text-error">{errors.lastName}</p>}
                </div>
            </div>

            {/* Role */}
            <div>
                <label className="block text-sm font-medium text-text-primary mb-2">I am a</label>
                <div className="grid grid-cols-2 gap-3">
                    {[{ value: 'professor', label: 'Professor / Faculty', icon: 'GraduationCap' },
                    { value: 'ta', label: 'Teaching Assistant', icon: 'Users' }].map(opt => (
                        <label key={opt.value}
                            className={`flex items-center gap-3 p-3 border-2 rounded-lg cursor-pointer transition-all ${formData.role === opt.value ? 'border-primary bg-primary-50' : 'border-border hover:border-primary-200'}`}>
                            <input type="radio" name="role" value={opt.value} checked={formData.role === opt.value} onChange={handleInputChange} className="sr-only" />
                            <Icon name={opt.icon} size={18} className={formData.role === opt.value ? 'text-primary' : 'text-secondary-400'} />
                            <span className={`text-sm font-medium ${formData.role === opt.value ? 'text-primary' : 'text-text-secondary'}`}>{opt.label}</span>
                        </label>
                    ))}
                </div>
            </div>

            {/* Email */}
            <div>
                <label htmlFor="reg-email" className="block text-sm font-medium text-text-primary mb-1">Email address</label>
                <div className="relative">
                    <input type="email" id="reg-email" name="email" value={formData.email} onChange={handleInputChange}
                        className={`w-full px-4 py-3 pl-12 border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors ${errors.email ? 'border-error' : 'border-border'}`}
                        placeholder="you@university.edu" />
                    <Icon name="Mail" size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-secondary-400" />
                </div>
                {errors.email && <p className="mt-1 text-xs text-error">{errors.email}</p>}
            </div>

            {/* Entry Number (TA only) */}
            {formData.role === 'ta' && (
                <div>
                    <label htmlFor="entryNumber" className="block text-sm font-medium text-text-primary mb-1">Entry Number</label>
                    <input type="text" id="entryNumber" name="entryNumber" value={formData.entryNumber} onChange={handleInputChange}
                        className={`w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors ${errors.entryNumber ? 'border-error' : 'border-border'}`}
                        placeholder="e.g. 2022CSB1099" />
                    {errors.entryNumber && <p className="mt-1 text-xs text-error">{errors.entryNumber}</p>}
                </div>
            )}

            {/* Department */}
            <div>
                <label htmlFor="department" className="block text-sm font-medium text-text-primary mb-1">Department <span className="text-text-secondary font-normal">(optional)</span></label>
                <input type="text" id="department" name="department" value={formData.department} onChange={handleInputChange}
                    className="w-full px-4 py-3 border border-border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors"
                    placeholder="e.g. Computer Science" />
            </div>

            {/* Password */}
            <div>
                <label htmlFor="reg-password" className="block text-sm font-medium text-text-primary mb-1">Password</label>
                <div className="relative">
                    <input type={showPassword ? 'text' : 'password'} id="reg-password" name="password"
                        value={formData.password} onChange={handleInputChange}
                        className={`w-full px-4 py-3 pl-12 pr-12 border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors ${errors.password ? 'border-error' : 'border-border'}`}
                        placeholder="Create a strong password" />
                    <Icon name="Lock" size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-secondary-400" />
                    <button type="button" onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-4 top-1/2 -translate-y-1/2 text-secondary-400 hover:text-text-primary transition-colors">
                        <Icon name={showPassword ? 'EyeOff' : 'Eye'} size={20} />
                    </button>
                </div>
                {formData.password && (
                    <div className="mt-2">
                        <div className="flex items-center gap-2 mb-1">
                            <div className="flex-1 bg-secondary-200 rounded-full h-1.5">
                                <div className={`h-1.5 rounded-full transition-all duration-300 ${strengthColor()}`} style={{ width: `${(passwordStrength.score / 5) * 100}%` }} />
                            </div>
                            <span className="text-xs font-medium text-text-secondary">{strengthLabel()}</span>
                        </div>
                    </div>
                )}
                {errors.password && <p className="mt-1 text-xs text-error">{errors.password}</p>}
            </div>

            {/* Confirm Password */}
            <div>
                <label htmlFor="confirmPassword" className="block text-sm font-medium text-text-primary mb-1">Confirm password</label>
                <div className="relative">
                    <input type="password" id="confirmPassword" name="confirmPassword"
                        value={formData.confirmPassword} onChange={handleInputChange}
                        className={`w-full px-4 py-3 pl-12 border rounded-lg focus:ring-2 focus:ring-primary-500 transition-colors ${errors.confirmPassword ? 'border-error' : 'border-border'}`}
                        placeholder="Confirm your password" />
                    <Icon name="Lock" size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-secondary-400" />
                </div>
                {errors.confirmPassword && <p className="mt-1 text-xs text-error">{errors.confirmPassword}</p>}
            </div>

            {/* Terms */}
            <div>
                <label className="flex items-start gap-3 cursor-pointer">
                    <input type="checkbox" name="agreeToTerms" checked={formData.agreeToTerms} onChange={handleInputChange}
                        className="w-4 h-4 text-primary border-border rounded focus:ring-primary-500 mt-0.5" />
                    <span className="text-sm text-text-secondary">I agree to the <button type="button" className="text-primary hover:text-primary-700">Terms of Service</button> and <button type="button" className="text-primary hover:text-primary-700">Privacy Policy</button></span>
                </label>
                {errors.agreeToTerms && <p className="mt-1 text-xs text-error">{errors.agreeToTerms}</p>}
            </div>

            <button type="submit" disabled={isSubmitting}
                className="w-full bg-primary text-white py-3 px-4 rounded-lg hover:bg-primary-700 transition-colors font-medium flex items-center justify-center space-x-2 disabled:opacity-50">
                {isSubmitting ? (
                    <><div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" /><span>Creating account...</span></>
                ) : (
                    <><Icon name="UserPlus" size={20} /><span>Create Account</span></>
                )}
            </button>
        </form>
    );
};

export default RegisterForm;