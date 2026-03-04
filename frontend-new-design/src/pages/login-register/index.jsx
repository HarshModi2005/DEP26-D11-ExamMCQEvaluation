import React, { useState } from 'react';
import Icon from '../../components/AppIcon';
import LoginForm from './components/LoginForm';
import RegisterForm from './components/RegisterForm';

const LoginRegister = () => {
    const [activeTab, setActiveTab] = useState('login');

    return (
        <div className="min-h-screen bg-gradient-to-br from-primary-50 via-background to-secondary-50 flex items-center justify-center px-4 py-8">
            <div className="w-full max-w-6xl">
                {/* Header */}
                <div className="text-center mb-8">
                    <div className="flex items-center justify-center space-x-3 mb-4">
                        <div className="w-12 h-12 bg-primary rounded-xl flex items-center justify-center shadow-lg">
                            <Icon name="GraduationCap" size={24} color="white" />
                        </div>
                        <h1 className="text-3xl font-bold text-text-primary">EvalDEP</h1>
                    </div>
                    <p className="text-text-secondary text-lg">
                        AI-powered answer sheet evaluation platform for faculty and TAs
                    </p>
                </div>

                {/* Authentication Card */}
                <div className="bg-surface rounded-2xl shadow-xl border border-border overflow-hidden">
                    {/* Tab Navigation */}
                    <div className="border-b border-border bg-secondary-50">
                        <div className="flex">
                            <button
                                onClick={() => setActiveTab('login')}
                                className={`flex-1 py-4 px-6 text-center font-medium transition-all duration-200 ${activeTab === 'login'
                                    ? 'text-primary border-b-2 border-primary bg-surface'
                                    : 'text-text-secondary hover:text-text-primary hover:bg-secondary-100'
                                    }`}
                            >
                                <div className="flex items-center justify-center space-x-2">
                                    <Icon name="LogIn" size={20} />
                                    <span>Sign In</span>
                                </div>
                            </button>
                            <button
                                onClick={() => setActiveTab('register')}
                                className={`flex-1 py-4 px-6 text-center font-medium transition-all duration-200 ${activeTab === 'register'
                                    ? 'text-primary border-b-2 border-primary bg-surface'
                                    : 'text-text-secondary hover:text-text-primary hover:bg-secondary-100'
                                    }`}
                            >
                                <div className="flex items-center justify-center space-x-2">
                                    <Icon name="UserPlus" size={20} />
                                    <span>Create Account</span>
                                </div>
                            </button>
                        </div>
                    </div>

                    {/* Form Content */}
                    <div className="grid lg:grid-cols-2 min-h-[580px]">
                        {/* Left Panel - Form */}
                        <div className="p-8 lg:p-12">
                            <div className="max-w-md mx-auto">
                                <div className="mb-8">
                                    <h2 className="text-2xl font-semibold text-text-primary mb-2">
                                        {activeTab === 'login' ? 'Welcome back!' : 'Join EvalDEP'}
                                    </h2>
                                    <p className="text-text-secondary">
                                        {activeTab === 'login'
                                            ? 'Sign in to manage your courses and evaluations.'
                                            : 'Create your account as a professor or teaching assistant.'}
                                    </p>
                                </div>
                                {activeTab === 'login' ? <LoginForm /> : <RegisterForm />}
                            </div>
                        </div>

                        {/* Right Panel - Feature highlights */}
                        <div className="bg-gradient-to-br from-primary-600 to-primary-800 p-8 lg:p-12 text-white flex flex-col justify-center">
                            <div className="max-w-md mx-auto">
                                <h3 className="text-2xl font-semibold mb-6">
                                    {activeTab === 'login' ? 'Streamline your grading workflow' : 'Built for academic efficiency'}
                                </h3>
                                <div className="space-y-5">
                                    {[
                                        { icon: 'Scan', title: 'AI-Powered OCR', desc: 'Automatically extract and evaluate student answers from scanned sheets using Vertex AI.' },
                                        { icon: 'BookOpen', title: 'Course Management', desc: 'Manage courses, students, and teaching assistants in one centralized platform.' },
                                        { icon: 'FileSpreadsheet', title: 'Google Sheets Integration', desc: 'Import class lists and export marks directly to Google Sheets with one click.' },
                                        { icon: 'BarChart3', title: 'Detailed Analytics', desc: 'Track performance metrics, score distributions, and question-wise analysis.' },
                                    ].map(feature => (
                                        <div key={feature.icon} className="flex items-start space-x-4">
                                            <div className="w-9 h-9 bg-white bg-opacity-20 rounded-lg flex items-center justify-center flex-shrink-0">
                                                <Icon name={feature.icon} size={18} color="white" />
                                            </div>
                                            <div>
                                                <h4 className="font-semibold mb-0.5">{feature.title}</h4>
                                                <p className="text-primary-100 text-sm leading-relaxed">{feature.desc}</p>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="text-center mt-6 text-sm text-text-secondary">
                    <p>By continuing, you agree to our <button className="text-primary hover:underline">Terms of Service</button> and <button className="text-primary hover:underline">Privacy Policy</button></p>
                </div>
            </div>
        </div>
    );
};

export default LoginRegister;