# DEP — Formal Implementation Plan
**Version:** 1.0  
**Date:** 2026-03-04  
**Status:** Planning

---

## 1. Executive Summary

This document outlines the plan to evolve the current frontend (a React + Vite + TailwindCSS app with mock data) into a fully integrated platform connected to **Supabase** as the primary database. The backend (FastAPI) handles OCR/AI evaluation; this plan covers the database schema design, frontend restructuring, new pages, and how every layer ties together.

---

## 2. Current State Audit

### Frontend (`/frontend-new-design`)
| Page | Route | Current State |
|---|---|---|
| Login/Register | `/login-register` | UI only, no auth |
| My Courses | `/faculty-dashboard` | Mock data, no DB |
| Course Detail | `/course/:courseId` | Mock data, tabs partially built |
| Analytics | `/analytics-dashboard` | Mock data, not course-scoped |
| Sprint Planning (Duty Alloc.) | `/sprint-planning` | Question-wise, to be repurposed |
| Team Management | `/team-management` | Standalone page, to move inside Course |
| Kanban Board | `/kanban-board` | **Untouched — leave as-is** |
| Task Detail | `/task-detail` | Separate task tool — leave |
| Evaluate | *(missing)* | **New page needed** |

### Backend (`/backend`)
| Service | Description |
|---|---|
| `ocr_service.py` | Extracts MCQ answers from answer sheet images via Vertex AI |
| `evaluation_service.py` | Scores student answers against an answer key |
| `answer_key_service.py` | Loads/saves answer key from Drive or file upload |
| `drive_service.py` | Google Drive integration (list, download files) |
| `sheets_service.py` | Google Sheets read/write (class list import, marks export) |
| `database.py` | SQLite DB (Student, Submission, EvaluationResult) — to be replaced by Supabase |

---

## 3. Database Schema (Supabase / PostgreSQL)

All tables live in Supabase. Auth is handled by **Supabase Auth** (email/password).

### 3.1 `profiles` (extends `auth.users`)
```sql
CREATE TABLE profiles (
  id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  entry_number TEXT,          -- For TAs: e.g. "2022CSB1099"
  role        TEXT NOT NULL CHECK (role IN ('professor', 'ta')),
  department  TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);
```

### 3.2 `courses`
```sql
CREATE TABLE courses (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code            TEXT NOT NULL,         -- e.g. "CS306"
  title           TEXT NOT NULL,
  description     TEXT,
  department      TEXT,
  semester        TEXT,                  -- e.g. "Spring 2026"
  instructor_id   UUID REFERENCES profiles(id),
  master_sheet_url TEXT,                 -- Central Google Sheet link
  created_at      TIMESTAMPTZ DEFAULT now()
);
```

### 3.3 `course_tas` (Many-to-Many: courses ↔ TAs)
```sql
CREATE TABLE course_tas (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id  UUID REFERENCES courses(id) ON DELETE CASCADE,
  ta_id      UUID REFERENCES profiles(id) ON DELETE CASCADE,
  UNIQUE(course_id, ta_id)
);
```

### 3.4 `students`
```sql
CREATE TABLE students (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  roll_number   TEXT NOT NULL UNIQUE,  -- e.g. "2023CSB1010"
  email         TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);
```

### 3.5 `course_students` (Many-to-Many: courses ↔ students, imported from Google Sheet)
```sql
CREATE TABLE course_students (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id   UUID REFERENCES courses(id) ON DELETE CASCADE,
  student_id  UUID REFERENCES students(id) ON DELETE CASCADE,
  imported_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(course_id, student_id)
);
```

### 3.6 `evaluations` (one per exam)
```sql
CREATE TABLE evaluations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id       UUID REFERENCES courses(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,         -- e.g. "Quiz 1", "Mid Semester Exam"
  total_marks     NUMERIC DEFAULT 0,
  negative_marking NUMERIC DEFAULT 0,
  status          TEXT DEFAULT 'draft' CHECK (status IN ('draft','active','grading','published')),
  subsheet_name   TEXT,                  -- Tab name in the master Google Sheet
  drive_folder_url TEXT,                 -- Google Drive folder with student answer sheets
  answer_key_data JSONB,                 -- Stores the answer key JSON (from existing AnswerKey model)
  created_by      UUID REFERENCES profiles(id),
  created_at      TIMESTAMPTZ DEFAULT now()
);
```

### 3.7 `evaluation_duties` (TA assignments per evaluation)
```sql
CREATE TABLE evaluation_duties (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_id  UUID REFERENCES evaluations(id) ON DELETE CASCADE,
  assignee_id    UUID REFERENCES profiles(id),   -- TA or Professor
  role_note      TEXT,                            -- e.g. "primary grader"
  assigned_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE(evaluation_id, assignee_id)
);
```

### 3.8 `submission_results` (one row per student per evaluation)
```sql
CREATE TABLE submission_results (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_id   UUID REFERENCES evaluations(id) ON DELETE CASCADE,
  student_id      UUID REFERENCES students(id) ON DELETE CASCADE,
  graded_by       UUID REFERENCES profiles(id),
  total_score     NUMERIC,
  max_score       NUMERIC,
  correct_count   INT,
  incorrect_count INT,
  unattempted_count INT,
  negative_deduction NUMERIC DEFAULT 0,
  details         JSONB,    -- Array of QuestionResult objects
  comments        TEXT,
  created_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE(evaluation_id, student_id)
);
```

---

## 4. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    React Frontend (Vite)                     │
│                                                             │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │  Auth    │  │  Supabase   │  │    FastAPI Backend    │   │
│  │  (login) │  │  JS Client  │  │    (OCR + Scoring)   │   │
│  └──┬───────┘  └──────┬──────┘  └──────────┬───────────┘   │
│     │                 │                     │                │
└─────┼─────────────────┼─────────────────────┼───────────────┘
      │                 │                     │
      ▼                 ▼                     ▼
  Supabase Auth    Supabase DB         FastAPI on localhost
  (JWT tokens)    (PostgreSQL)         (runs OCR pipeline)
```

**Key principle:** Supabase is the source of truth for all structured data. The FastAPI backend is only called for the heavy lifting: OCR processing, answer key parsing, and results scoring. Once scored, results are written back to Supabase and the Google Sheet.

---

## 5. Supabase Integration Setup

### 5.1 Package Installation
```bash
cd /Users/harsh/Desktop/DEP/frontend-new-design
npm install @supabase/supabase-js
```

### 5.2 Environment Variables (`.env`)
```env
VITE_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
VITE_SUPABASE_ANON_KEY=YOUR_ANON_KEY
VITE_BACKEND_URL=http://localhost:8000
```

### 5.3 Supabase Client (`src/services/supabaseClient.js`)
```js
import { createClient } from '@supabase/supabase-js';
export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);
```

### 5.4 Auth Context (`src/context/AuthContext.jsx`)
- Wrap the app with a React context that exposes: `user`, `profile`, `login()`, `logout()`, `loading`
- On mount: call `supabase.auth.getSession()` and `supabase.auth.onAuthStateChange()`
- After login: fetch the `profiles` row for the logged-in user to get `role`, `name`, etc.
- Redirect to `/faculty-dashboard` after successful login

---

## 6. Page-by-Page Specification

---

### 6.1 Login / Register (`/login-register`) — **Modify**

**Current:** UI only  
**Changes:**
- Wire up to `supabase.auth.signInWithPassword()` and `supabase.auth.signUp()`
- On sign-up, also create a row in `profiles` (via trigger or client-side)
- Role selection on sign-up: "Professor" or "Teaching Assistant"
- Redirect after login: → `/faculty-dashboard`

---

### 6.2 My Courses (`/faculty-dashboard`) — **Modify**

**Current:** Mock course cards  
**Changes:**
- If `role === 'professor'`: query `courses WHERE instructor_id = user.id`
- If `role === 'ta'`: query `course_tas JOIN courses WHERE ta_id = user.id`
- Show real course cards with actual metadata
- "Create New Course" button → opens a modal to insert a new row into `courses`
  - Fields: code, title, description, department, semester, master_sheet_url

---

### 6.3 Course Detail (`/course/:courseId`) — **Major Restructure**

**Current:** 5 tabs with mock data  
**Tabs (keep same design, wire up real data):**

#### Tab 1: Overview
- Show course metadata from Supabase
- Show master Google Sheet link (from `courses.master_sheet_url`)
- Recent activity feed (latest evaluations, recent results)

#### Tab 2: Evaluations *(primary tab)*
- List evaluations for this course from `evaluations WHERE course_id = :id`
- Show: name, status badge, graded count vs total students
- **"Create Evaluation" button** → opens a modal with fields:
  - Evaluation name
  - Total marks, negative marking
  - Subsheet name (tab within the master Google Sheet)
  - Google Drive folder URL (where student answer sheets are)
  - **Assign Duties:** Multi-select to assign TAs or self → inserts into `evaluation_duties`
- Each evaluation row has:
  - **"Start Grading" → navigate to `/evaluate/:evaluationId`**
  - Status toggle (draft → active → published)

#### Tab 3: Students
- Query `course_students JOIN students WHERE course_id = :id`
- Show table of students with roll number
- **"Import from Google Sheet" button**:
  - Calls the existing backend `GET /api/sheets/preview?sheet_url=...`
  - Parses the class list (roll numbers + names) from the master sheet
  - Upserts into `students` table and `course_students` junction table

#### Tab 4: Teaching Team *(was standalone Team Management page)*
- Query `course_tas JOIN profiles WHERE course_id = :id`
- Show list of TAs
- "Invite TA" button → search by entry number or email → insert into `course_tas`
- Show the course instructor (from `courses.instructor_id`)

#### Tab 5: Analytics *(per-course, evaluation-wise)*
- Query `evaluations WHERE course_id = :id` → show list of exams
- Click an exam → show `submission_results WHERE evaluation_id = :id`
- Metrics: average, median, highest, lowest, score distribution (bar chart using recharts)
- Question analysis (correctRate per question computed from `details` JSONB)

---

### 6.4 Evaluate Page (`/evaluate/:evaluationId`) — **New Page**

This is the core operational page where OCR-based grading happens.

**Who sees it:** Professor or any TA assigned via `evaluation_duties`

**Layout:**
```
┌────────────────────────────────────────────────────────┐
│  Header + Sidebar                                      │
├──────────────────────────┬─────────────────────────────┤
│  LEFT PANEL              │  RIGHT PANEL                │
│  • Evaluation info card  │  • Answer Sheet Preview     │
│  • Drive folder URL      │    (after processing)        │
│  • Answer Key Panel      │                             │
│    (load / view / set)   │  • Per-student result table │
│  • "Run OCR Pipeline"    │    (roll no, score, status) │
│    button                │                             │
│  • Progress indicator    │  • "Export to Sheet" button │
└──────────────────────────┴─────────────────────────────┘
```

**Workflow:**
1. Page loads → fetches `evaluation` row from Supabase (gets drive_folder_url, answer_key_data, subsheet_name)
2. **Load Answer Key section:**
   - If `evaluation.answer_key_data` is not null → show existing key
   - "Load from Drive" → calls `POST /api/answer-key/extract-from-drive`
   - "Upload File" → calls `POST /api/answer-key/upload`
   - "Set Manually" → JSON editor / form
   - Once set → save `answer_key_data` back to Supabase `evaluations` table
3. **Run OCR Pipeline:**
   - Button calls `POST /api/process-drive-folder` with `drive_folder_url`
   - Progress bar shown during processing
   - On completion → results returned by backend as `StudentResult[]`
   - Save each result to Supabase `submission_results` table (match student by roll_number)
4. **Results Table:**
   - Displays all `submission_results` for this evaluation from Supabase
   - Columns: Roll No, Name, Score/Max, Correct/Incorrect/Unattempted, Status
   - Inline comment editing per student
5. **Export to Sheet:**
   - Calls `POST /api/export-to-sheets` with `master_sheet_url` + `subsheet_name` as query params
   - Updates evaluation status to `published` in Supabase

---

### 6.5 Analytics Dashboard (`/analytics-dashboard`) — **Modify**

**Current:** Standalone, shows mock exams  
**Changes:**
- Repurpose as an **aggregate view** across all courses the user is part of
- Or: redirect to course-level analytics via the Course Detail > Analytics tab
- Show a high-level overview: total evaluations, total students graded, overall averages
- Drill down into a specific course → opens Course Detail

---

### 6.6 Sprint Planning / Grading Allocation — **Remove**

- **Remove from sidebar navigation entirely**
- Duty allocation is now embedded in the "Create Evaluation" modal inside Course Detail

---

### 6.7 Team Management (`/team-management`) — **Repurpose / Retire**

- The standalone Team Management page is folded into **Course Detail > Teaching Team tab**
- The `/team-management` route can be removed from `Routes.jsx` or redirected
- The existing `WorkspaceSettings.jsx` component can be reused inside the Course Detail tab

---

### 6.8 Kanban Board (`/kanban-board`) — **Untouched**
No changes to this page.

---

## 7. Service Layer (`src/services/`)

Create a clean service layer so pages never call Supabase directly:

```
src/services/
  supabaseClient.js       ← Supabase client singleton
  authService.js          ← login, logout, signup, getProfile
  courseService.js        ← getCourses, getCourseById, createCourse
  evaluationService.js    ← getEvaluations, createEvaluation, updateStatus
  studentService.js       ← getStudents, importFromSheet
  teamService.js          ← getTAs, addTA, removeTA
  resultsService.js       ← saveResults, getResults, getAnalytics
  backendService.js       ← wrappers around FastAPI OCR endpoints
```

---

## 8. Navigation & Routing Changes

### Updated `Routes.jsx`
| Route | Component | Change |
|---|---|---|
| `/` | → redirect to `/login-register` | No change |
| `/login-register` | `LoginRegister` | Wire auth |
| `/faculty-dashboard` | `FacultyDashboard` | Wire Supabase |
| `/course/:courseId` | `CourseDetail` | Major update |
| `/evaluate/:evaluationId` | `EvaluatePage` | **New** |
| `/analytics-dashboard` | `AnalyticsDashboard` | Modify |
| `/kanban-board` | `KanbanBoard` | No change |
| `/task-detail` | `TaskDetail` | No change |
| `/sprint-planning` | — | **Remove** |
| `/team-management` | — | **Remove** |

### Sidebar Updates
Remove "Sprint Planning" and "Team Management" links.  
Ensure "Analytics" navigates to `/analytics-dashboard`.

---

## 9. Backend Changes (FastAPI)

The FastAPI backend requires **minimal changes** since its OCR/scoring pipeline is already solid:

### 9.1 New Environment Variable
Add `SUPABASE_URL` and `SUPABASE_KEY` to backend `.env` for the backend to optionally write results directly to Supabase (optional — frontend can also write results after fetching from OCR).

### 9.2 Google Sheets Subsheet Support
`sheets_service.py` should accept a `sheet_name` parameter to target a specific tab (subsheet) in the master Google Sheet for a given evaluation.

```python
# In export-to-sheets endpoint, add optional subsheet_name query param
@router.post("/export-to-sheets")
def export_to_sheets(request: ExportToSheetsRequest, subsheet_name: Optional[str] = None):
    ...
    summary = sheets_service.update_marks(request.sheet_url, results_dicts, sheet_name=subsheet_name)
```

### 9.3 Remove SQLite Dependency
`database.py` (SQLite) becomes redundant once Supabase is the DB. The OCR endpoints should return results to the frontend, which then persists to Supabase. The SQLite DB can be phased out.

---

## 10. Implementation Phases

### Phase 1 — Foundation (Database + Auth)
- [ ] Create Supabase project, run all SQL schema migrations
- [ ] Install `@supabase/supabase-js` in frontend
- [ ] Create `src/services/supabaseClient.js`
- [ ] Create `src/context/AuthContext.jsx`
- [ ] Wire up `LoginRegister` page to Supabase Auth
- [ ] Add `.env` with Supabase credentials

### Phase 2 — My Courses Page
- [ ] Create `courseService.js`
- [ ] Replace mock data in `FacultyDashboard` with real Supabase queries
- [ ] "Create Course" modal with form + Supabase insert

### Phase 3 — Course Detail Page (Major Work)
- [ ] **Students Tab:** Implement "Import from Google Sheet" using `/api/sheets/preview` + Supabase upsert
- [ ] **Teaching Team Tab:** Query `course_tas`, add/remove TAs
- [ ] **Evaluations Tab:** List evaluations, "Create Evaluation" modal with duty assignment
- [ ] **Analytics Tab:** Query `submission_results`, compute metrics, render charts

### Phase 4 — Evaluate Page (New)
- [ ] Create `/evaluate/:evaluationId` route and page component
- [ ] Answer key management section (load from Drive / upload / manual)
- [ ] "Run OCR Pipeline" button → calls FastAPI → save results to Supabase
- [ ] Results table with inline edit
- [ ] Export to Google Sheet with subsheet targeting

### Phase 5 — Cleanup & Polish
- [ ] Remove `/sprint-planning` route and sidebar link
- [ ] Remove standalone `/team-management` route
- [ ] Update `AnalyticsDashboard` to be course-scoped or aggregate
- [ ] Backend: add `subsheet_name` param to `export-to-sheets`
- [ ] Add Row-Level Security (RLS) policies in Supabase
- [ ] Final design review for coherence on the new Evaluate page

---

## 11. Supabase Row-Level Security (RLS)

All tables should have RLS enabled to ensure data isolation:

- **courses:** Professors see only their own courses; TAs see courses they're enrolled in via `course_tas`
- **evaluations:** Same scoping as courses
- **submission_results:** Accessible to instructor and assigned TAs (`evaluation_duties`)
- **students / course_students:** Accessible to anyone on the course team

---

## 12. Key Design Decisions

| Decision | Rationale |
|---|---|
| Supabase for DB | Gives us auth + DB + realtime in one SDK; no need to build a custom auth system |
| FastAPI kept for OCR | The existing Python pipeline (Vertex AI OCR + scoring) is mature and should not be rewritten |
| Results flow: FastAPI → Frontend → Supabase | Frontend orchestrates the pipeline, keeping the Python backend stateless |
| Evaluation duty allocation folded into "Create Evaluation" | Simpler UX; fewer navigation steps for the faculty; removes the confusing standalone page |
| Team Management folded into Course Detail | Team is a course-scoped concept; makes no sense as a standalone page |
| Subsheet per evaluation | Allows one master Google Sheet per course with one tab per exam — very clean for faculty |
| No question-wise allocation | Removed as per user requirement; TAs are assigned at evaluation level, not question level |
