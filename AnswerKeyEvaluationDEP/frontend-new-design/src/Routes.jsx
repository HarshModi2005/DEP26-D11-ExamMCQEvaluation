import React from "react";
import { BrowserRouter, Routes as RouterRoutes, Route, Navigate } from "react-router-dom";
import ScrollToTop from "./components/ScrollToTop";
import ErrorBoundary from "./components/ErrorBoundary";
import ProtectedRoute from "./components/ProtectedRoute";

// Page imports
import LoginRegister from "./pages/login-register";
import DashboardOverview from "./pages/dashboard-overview";
import KanbanBoard from "./pages/kanban-board";
import TaskDetail from "./pages/task-detail";
import AnalyticsDashboard from "./pages/analytics-dashboard";
import FacultyDashboard from "./pages/faculty-dashboard";
import CourseDetail from "./pages/course-detail";
import EvaluatePage from "./pages/evaluate";

const Routes = () => {
    return (
        <BrowserRouter>
            <ErrorBoundary>
                <ScrollToTop />
                <RouterRoutes>
                    {/* Public routes */}
                    <Route path="/login-register" element={<LoginRegister />} />
                    <Route path="/" element={<Navigate to="/login-register" replace />} />

                    {/* Protected routes */}
                    <Route path="/dashboard-overview" element={<ProtectedRoute><DashboardOverview /></ProtectedRoute>} />
                    <Route path="/faculty-dashboard" element={<ProtectedRoute><FacultyDashboard /></ProtectedRoute>} />
                    <Route path="/course/:courseId" element={<ProtectedRoute><CourseDetail /></ProtectedRoute>} />
                    <Route path="/evaluate/:evaluationId" element={<ProtectedRoute><EvaluatePage /></ProtectedRoute>} />
                    <Route path="/kanban-board" element={<ProtectedRoute><KanbanBoard /></ProtectedRoute>} />
                    <Route path="/task-detail" element={<ProtectedRoute><TaskDetail /></ProtectedRoute>} />
                    <Route path="/analytics-dashboard" element={<ProtectedRoute><AnalyticsDashboard /></ProtectedRoute>} />

                    {/* Catch-all */}
                    <Route path="*" element={<Navigate to="/login-register" replace />} />
                </RouterRoutes>
            </ErrorBoundary>
        </BrowserRouter>
    );
};

export default Routes;