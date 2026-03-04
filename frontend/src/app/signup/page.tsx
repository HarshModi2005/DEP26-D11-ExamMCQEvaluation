"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Lock, Mail, ShieldCheck, GraduationCap, ArrowRight, Loader2, AlertCircle, UserPlus } from "lucide-react";
import api from "@/lib/api";
import Link from "next/link";

export default function SignupPage() {
    const router = useRouter();
    const [role, setRole] = useState<"ta" | "student">("student");
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState(false);
    const [formData, setFormData] = useState({
        email: "",
        password: "",
        confirmPassword: "",
        rollNumber: "",
    });

    const handleSignup = async (e: React.FormEvent) => {
        e.preventDefault();

        if (formData.password !== formData.confirmPassword) {
            setError("Passwords do not match.");
            return;
        }

        setIsLoading(true);
        setError(null);

        try {
            await api.post("/auth/register", {
                email: formData.email,
                password: formData.password,
                role: role,
                roll_number: role === "student" ? formData.rollNumber : null
            });

            setSuccess(true);
            setTimeout(() => {
                router.push("/login");
            }, 2000);
        } catch (err: any) {
            console.error("Signup failed:", err);
            setError(err.response?.data?.detail || "Registration failed. Please try again.");
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 p-4 font-sans">
            {/* Background patterns */}
            <div className="absolute inset-0 overflow-hidden pointer-events-none">
                <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-white opacity-10 rounded-full blur-3xl animate-pulse"></div>
                <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-indigo-300 opacity-20 rounded-full blur-3xl animate-pulse delay-1000"></div>
            </div>

            <div className="relative w-full max-w-md">
                {/* Glassmorphic Card */}
                <div className="bg-white/10 backdrop-blur-xl border border-white/20 rounded-3xl shadow-2xl overflow-hidden p-8 transition-all hover:shadow-indigo-500/20">
                    <div className="text-center mb-8">
                        <h1 className="text-4xl font-black text-white tracking-tight mb-2">
                            Join AutoEval
                        </h1>
                        <p className="text-indigo-100/80 font-medium text-sm">
                            Create your account to get started
                        </p>
                    </div>

                    {error && (
                        <div className="mb-6 p-4 bg-red-500/20 shadow-lg border border-red-500/30 rounded-xl flex items-center gap-3 text-white text-sm font-medium animate-in fade-in slide-in-from-top-2">
                            <AlertCircle className="w-5 h-5 shrink-0" />
                            <p>{error}</p>
                        </div>
                    )}

                    {success && (
                        <div className="mb-6 p-4 bg-green-500/20 shadow-lg border border-green-500/30 rounded-xl flex items-center gap-3 text-white text-sm font-medium animate-in fade-in slide-in-from-top-2">
                            <ShieldCheck className="w-5 h-5 shrink-0" />
                            <p>Registration successful! Redirecting to login...</p>
                        </div>
                    )}

                    <form onSubmit={handleSignup} className="space-y-6">
                        {/* Role Selection */}
                        <div className="grid grid-cols-2 gap-4 mb-6">
                            <button
                                type="button"
                                onClick={() => setRole("student")}
                                className={`flex flex-col items-center justify-center p-4 rounded-2xl border-2 transition-all gap-2 ${role === "student"
                                    ? "bg-white/20 border-white text-white shadow-lg shadow-white/10"
                                    : "bg-white/5 border-transparent text-white/60 hover:bg-white/10"
                                    }`}
                            >
                                <GraduationCap className={`w-8 h-8 ${role === "student" ? "animate-bounce" : ""}`} />
                                <span className="text-xs font-bold uppercase tracking-wider">Student</span>
                            </button>
                            <button
                                type="button"
                                onClick={() => setRole("ta")}
                                className={`flex flex-col items-center justify-center p-4 rounded-2xl border-2 transition-all gap-2 ${role === "ta"
                                    ? "bg-white/20 border-white text-white shadow-lg shadow-white/10"
                                    : "bg-white/5 border-transparent text-white/60 hover:bg-white/10"
                                    }`}
                            >
                                <ShieldCheck className={`w-8 h-8 ${role === "ta" ? "animate-bounce" : ""}`} />
                                <span className="text-xs font-bold uppercase tracking-wider">TA / Faculty</span>
                            </button>
                        </div>

                        {/* Input Fields */}
                        <div className="space-y-4">
                            <div className="relative group">
                                <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/60 group-focus-within:text-white transition-colors" />
                                <input
                                    type="email"
                                    required
                                    placeholder="University Email"
                                    className="w-full bg-white/10 border border-white/20 rounded-xl py-4 pl-12 pr-4 text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-white/30 focus:bg-white/20 transition-all font-medium"
                                    value={formData.email}
                                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                                />
                            </div>

                            <div className="relative group">
                                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/60 group-focus-within:text-white transition-colors" />
                                <input
                                    type="password"
                                    required
                                    placeholder="Password"
                                    className="w-full bg-white/10 border border-white/20 rounded-xl py-4 pl-12 pr-4 text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-white/30 focus:bg-white/20 transition-all font-medium"
                                    value={formData.password}
                                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                                />
                            </div>

                            <div className="relative group">
                                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/60 group-focus-within:text-white transition-colors" />
                                <input
                                    type="password"
                                    required
                                    placeholder="Confirm Password"
                                    className="w-full bg-white/10 border border-white/20 rounded-xl py-4 pl-12 pr-4 text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-white/30 focus:bg-white/20 transition-all font-medium"
                                    value={formData.confirmPassword}
                                    onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                                />
                            </div>
                        </div>

                        {/* Entry Number (Only for Students) */}
                        {role === "student" && (
                            <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
                                <div className="relative group">
                                    <GraduationCap className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/60 group-focus-within:text-white transition-colors" />
                                    <input
                                        type="text"
                                        required={role === "student"}
                                        placeholder="Entry Number (e.g. 2023CSB1122)"
                                        className="w-full bg-white/10 border border-white/20 rounded-xl py-4 pl-12 pr-4 text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-white/30 focus:bg-white/20 transition-all font-medium"
                                        value={formData.rollNumber}
                                        onChange={(e) => setFormData({ ...formData, rollNumber: e.target.value })}
                                    />
                                </div>
                            </div>
                        )}

                        {/* Submit Button */}
                        <button
                            type="submit"
                            disabled={isLoading || success}
                            className="group w-full bg-white text-indigo-600 font-black py-4 rounded-xl shadow-xl shadow-indigo-900/10 hover:shadow-indigo-900/20 active:scale-95 transition-all flex items-center justify-center gap-3 disabled:opacity-70 disabled:active:scale-100"
                        >
                            {isLoading ? (
                                <Loader2 className="w-6 h-6 animate-spin" />
                            ) : success ? (
                                "ACCOUNT CREATED!"
                            ) : (
                                <>
                                    CREATE ACCOUNT <UserPlus className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                                </>
                            )}
                        </button>
                    </form>

                    <div className="mt-8 text-center border-t border-white/10 pt-6">
                        <p className="text-white/60 text-sm font-medium mb-2">
                            Already have an account?
                        </p>
                        <Link
                            href="/login"
                            className="text-white font-bold hover:text-indigo-200 transition-colors flex items-center justify-center gap-2 group"
                        >
                            Sign in here <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    );
}
