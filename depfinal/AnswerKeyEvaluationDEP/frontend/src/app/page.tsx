import Link from "next/link";
import { ArrowRight, Sparkles } from "lucide-react";

export default function Home() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-blue-500 via-indigo-600 to-purple-700 p-4 relative overflow-hidden">
      {/* Decorative background elements */}
      <div className="absolute top-0 left-0 w-full h-full pointer-events-none">
        <div className="absolute top-[20%] left-[10%] w-64 h-64 bg-white opacity-5 rounded-full blur-3xl animate-pulse"></div>
        <div className="absolute bottom-[20%] right-[10%] w-96 h-96 bg-blue-300 opacity-10 rounded-full blur-3xl animate-pulse delay-700"></div>
      </div>

      <div className="bg-white/95 backdrop-blur-md p-12 rounded-3xl shadow-[0_20px_50px_rgba(0,0,0,0.2)] max-w-xl w-full text-center relative z-10 border border-white/20">
        <div className="inline-flex items-center gap-2 bg-indigo-100 text-indigo-700 px-4 py-1.5 rounded-full text-sm font-bold mb-6">
          <Sparkles className="w-4 h-4" /> <span>Next-Gen Grading</span>
        </div>

        <h1 className="text-6xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 mb-6 tracking-tight">
          AutoEval
        </h1>

        <p className="text-gray-600 mb-10 text-xl font-medium leading-relaxed">
          The ultimate AI-driven ecosystem for <span className="text-indigo-600 font-bold">automated paper evaluation</span> and student performance tracking.
        </p>

        <div className="space-y-4">
          <Link
            href="/login"
            className="flex items-center justify-center gap-3 w-full bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white font-black py-5 px-8 rounded-2xl transition-all shadow-xl hover:shadow-indigo-500/30 hover:-translate-y-1 active:scale-95 text-lg uppercase tracking-wider"
          >
            Get Started <ArrowRight className="w-6 h-6" />
          </Link>

          <p className="text-gray-400 text-xs font-bold uppercase tracking-widest pt-4">
            Secure Access for TAs & Students
          </p>
        </div>
      </div>
    </div>
  );
}
