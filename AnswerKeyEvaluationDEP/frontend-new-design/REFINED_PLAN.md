# Refined Implementation Plan: Faculty Grading & Analytics Platform

This plan pivots the existing "TaskFlow Pro" design into a specialized platform for Faculty and TAs to manage grading via Google Drive/Sheets.

## Core Objectives
1.  **Analytics**: Shift from "Team Velocity" to "Exam Performance". Show a list of exams (e.g., "CS306 Quiz 1"). Clicking one reveals specific analytics (score distribution, item analysis).
2.  **Team Management**: Clean up the UI by removing "Online Status" and "Last Active" indicators to focus on role management (TA vs Faculty).
3.  **Grading Allocation (formerly Sprint Planning)**: Transform this into a "Duty Allocation" center. Faculty should be able to assign specific grading tasks (e.g., "Grade Q1-Q5") to specific TAs based on permissions.

---

## Step-by-Step Implementation

### Phase 1: Team Management Cleanup
**Goal**: Simplify the TAs/Faculty list.
- [ ] **Edit `src/pages/team-management/components/MemberTable.jsx`**:
    - Remove `isOnline` status indicators (green dots).
    - Remove `lastActive` column.
    - Keep "Role" (Admin/Faculty vs Member/TA) as this is crucial for the new permission system.

### Phase 2: Analytics Dashboard Overhaul
**Goal**: create a "Test-wise" analytics view.
- [ ] **Refactor `src/pages/analytics-dashboard/index.jsx`**:
    - **View 1 (Index)**: Display a grid/list of "Conducted Exams" (e.g., CS306 Quiz 1, Midsem, Endsem) instead of generic charts.
    - **View 2 (Detail)**: When an exam is clicked, show:
        - Average Score.
        - Score Distribution Histogram.
        - "Question Performance" (hardest/easiest questions).
        - TA Grading Progress (e.g., "TA A has graded 80/100 papers").

### Phase 3: "Grading Allocation" (Sprint Planning Redesign)
**Goal**: A localized place to assign grading duties.
- [ ] **Rename/Refactor concept**: Treat "Sprint Planning" as "Grading Duty Allocation".
- [ ] **UI Changes**:
    - **Selector**: Dropdown to select the "Exam" currently being graded.
    - **Columns**:
        - **"Unassigned Questions"**: List of question sets (e.g., Q1, Q2, Section A) derived from the Answer Key schema.
        - **"Assigned to TA"**: Drag-and-drop interface to assign a question set to a TA.
    - **Permissions**:
        - Add a mock "Current User Role" toggle.
        - If `Faculty`: Can drag/drop and assign duties.
        - If `TA`: Read-only view of their assigned duties.
    - **Clutter Reduction**: Remove "Backlog", "Story Points", and "Velocity" charts. Replace with simple "Questions" and "Assignee".

### Phase 4: Integration Points (Future/Backend)
- **Google Drive/Sheet Integration**:
    - In `CourseDetail`, add a "Connect Answer Key" button.
    - This will eventually link to the backend service that parses the Google Sheet to generate the "Unassigned Questions" list in the Allocation page.

---

## Immediate Next Steps (Actionable)
1.  **Modify `MemberTable.jsx`** to remove status columns.
2.  **Create `ExamList` component** for the Analytics page.
3.  **Scaffold `GradingAllocation.jsx`** to replace the complex `SprintPlanning` view.
