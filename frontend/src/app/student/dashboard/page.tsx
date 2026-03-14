"use client"
import { useState } from 'react';
import api from '@/lib/api';
import { Search, CheckCircle, XCircle, LogOut } from 'lucide-react';
import { useRouter } from 'next/navigation';


export default function StudentDashboard() {
    const [rollNumber, setRollNumber] = useState('');
    const [results, setResults] = useState<any[]>([]);
    const [searched, setSearched] = useState(false);
    const [loading, setLoading] = useState(false);
    const [isLogoutModalOpen, setIsLogoutModalOpen] = useState(false);
    const router = useRouter();


    const handleLogout = async () => {
        try {
            await api.post('/auth/logout');
        } catch (error) {
            console.error("Logout failed:", error);
        } finally {
            // Always clear localStorage and redirect
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            router.push('/login');
        }
    };


    const handleSearch = async () => {
        if (!rollNumber) return;
        setLoading(true);
        try {
            const res = await api.get('/results');
            // Client-side filtering for MVP
            const studentResults = res.data.filter((r: any) =>
                r.student_id && r.student_id.toLowerCase() === rollNumber.toLowerCase()
            );
            setResults(studentResults);
            setSearched(true);
        } catch (error) {
            console.error("Error fetching results:", error);
            alert("Failed to fetch results.");
        }
        setLoading(false);
    };

    return (
        <div className="min-h-screen bg-gray-50 p-8 text-gray-800">
            <div className="max-w-3xl mx-auto">
                <header className="mb-10 flex justify-between items-start">
                    <div className="flex-1 text-center">
                        <h1 className="text-3xl font-bold text-gray-900">Student Portal</h1>
                        <p className="text-gray-500">View your assessment results</p>
                    </div>
                    <button
                        onClick={() => setIsLogoutModalOpen(true)}
                        className="flex items-center gap-2 bg-white border border-gray-200 text-gray-600 px-4 py-2 rounded-xl hover:bg-red-50 hover:text-red-600 hover:border-red-100 transition-all shadow-sm font-medium text-sm group"
                    >
                        <LogOut className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
                        Logout
                    </button>
                </header>

                {/* Logout Confirmation Modal */}
                {isLogoutModalOpen && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-300">
                        <div className="bg-white rounded-3xl shadow-2xl w-full max-w-sm overflow-hidden animate-in zoom-in-95 duration-300">
                            <div className="p-8 text-center">
                                <div className="w-16 h-16 bg-red-50 rounded-2xl flex items-center justify-center mx-auto mb-6">
                                    <LogOut className="w-8 h-8 text-red-500" />
                                </div>
                                <h3 className="text-2xl font-bold text-gray-900 mb-2">Confirm Logout</h3>
                                <p className="text-gray-500 mb-8">
                                    Are you sure you want to log out of your student account?
                                </p>
                                <div className="grid grid-cols-2 gap-4">
                                    <button
                                        onClick={() => setIsLogoutModalOpen(false)}
                                        className="py-3 px-6 rounded-xl border border-gray-200 text-gray-600 font-bold hover:bg-gray-50 transition-all active:scale-95"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        onClick={handleLogout}
                                        className="py-3 px-6 rounded-xl bg-red-600 text-white font-bold hover:bg-red-700 shadow-lg shadow-red-200 transition-all active:scale-95"
                                    >
                                        Logout
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}


                <div className="bg-white p-8 rounded-2xl shadow-sm mb-8">
                    <label className="block text-sm font-medium text-gray-700 mb-2">Student Roll Number</label>
                    <div className="flex gap-3">
                        <input
                            type="text"
                            placeholder="e.g., 2023CS001"
                            className="flex-1 border border-gray-300 p-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
                            value={rollNumber}
                            onChange={(e) => setRollNumber(e.target.value)}
                        />
                        <button
                            onClick={handleSearch}
                            className="bg-indigo-600 text-white px-6 py-3 rounded-xl hover:bg-indigo-700 transition flex items-center gap-2 font-medium"
                            disabled={loading}
                        >
                            {loading ? 'Searching...' : <><Search className="w-5 h-5" /> Check Results</>}
                        </button>
                    </div>
                </div>

                {searched && (
                    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                        <h3 className="text-xl font-semibold text-gray-800">Performance History</h3>
                        {results.length === 0 ? (
                            <div className="bg-white p-10 rounded-2xl shadow-sm text-center text-gray-400">
                                No results found for <span className="text-gray-900 font-medium">{rollNumber}</span>.
                            </div>
                        ) : (
                            results.map((res, idx) => (
                                <div key={idx} className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
                                    <div className="flex justify-between items-center mb-4 border-b border-gray-100 pb-4">
                                        <div>
                                            <h4 className="text-lg font-bold text-gray-900">Exam: {res.exam_id}</h4>
                                            <p className="text-sm text-gray-500">Submission ID: {res.submission_id.substring(0, 8)}</p>
                                        </div>
                                        <div className="text-right">
                                            <div className="text-3xl font-bold text-indigo-600">{res.score}</div>
                                            <div className="text-xs text-gray-400 uppercase tracking-wide">Total Score</div>
                                        </div>
                                    </div>

                                    <div className="bg-gray-50 p-4 rounded-xl mb-4">
                                        <h5 className="text-sm font-semibold text-gray-700 mb-2">Feedback Summary</h5>
                                        <p className="text-gray-600">{res.feedback}</p>
                                    </div>

                                    {res.details && (() => {
                                        const details = JSON.parse(res.details || '{}');
                                        const answers = details.details || [];
                                        return (
                                            <div className="overflow-x-auto">
                                                <table className="w-full text-sm text-left">
                                                    <thead className="text-xs text-gray-500 uppercase bg-gray-50">
                                                        <tr>
                                                            <th className="px-4 py-2 rounded-l-lg">Q</th>
                                                            <th className="px-4 py-2">Marked</th>
                                                            <th className="px-4 py-2">Correct</th>
                                                            <th className="px-4 py-2 rounded-r-lg">Status</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {answers.map((ans: any, i: number) => (
                                                            <tr key={i} className="border-b border-gray-50 last:border-0">
                                                                <td className="px-4 py-3 font-medium">{ans.question_number}</td>
                                                                <td className="px-4 py-3">{ans.marked || '-'}</td>
                                                                <td className="px-4 py-3">{ans.correct}</td>
                                                                <td className="px-4 py-3">
                                                                    {ans.is_correct ? (
                                                                        <span className="flex items-center gap-1 text-green-600 font-medium">
                                                                            <CheckCircle className="w-4 h-4" /> Correct
                                                                        </span>
                                                                    ) : (
                                                                        <span className="flex items-center gap-1 text-red-500 font-medium">
                                                                            <XCircle className="w-4 h-4" /> Incorrect
                                                                        </span>
                                                                    )}
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            </div>
                                        );
                                    })()}
                                </div>
                            ))
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
