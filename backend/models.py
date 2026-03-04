from enum import Enum
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# ── Authentication Models ──

class UserRole(str, Enum):
    TA = "ta"
    STUDENT = "student"


class User(BaseModel):
    id: str
    email: str
    password: str
    role: UserRole
    roll_number: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    role: UserRole
    roll_number: Optional[str] = None




# ── Existing Models ──

class Student(BaseModel):
    id: str
    name: str
    roll_number: str


class Submission(BaseModel):
    id: str
    student_id: str
    exam_id: str
    file_id: str  # Google Drive File ID
    status: str


class EvaluationResult(BaseModel):
    submission_id: str
    score: float
    feedback: str


# ── Answer Key Models ──

class AnswerKeyEntry(BaseModel):
    correct_option: str
    marks: float = 1.0


class AnswerKey(BaseModel):
    total_questions: int
    answers: Dict[int, AnswerKeyEntry]  # {1: AnswerKeyEntry(...), ...}
    negative_marking: float = 0.0  # marks deducted per wrong answer
    metadata: Dict = {}  # source file, timestamp, etc.


# ── Student Result Models ──

class QuestionResult(BaseModel):
    question_number: int
    marked: Optional[str] = None
    correct: str
    result: str  # "correct", "incorrect", "unattempted", "multiple"
    score: float


class StudentResult(BaseModel):
    entry_number: str
    name: str
    total_score: float
    max_score: float
    correct_count: int
    incorrect_count: int
    unattempted_count: int
    negative_deduction: float = 0.0
    details: List[QuestionResult] = []
    comments: str = ""


# ── API Request/Response Models ──

class ProcessFolderRequest(BaseModel):
    folder_url: str


class ExportToSheetsRequest(BaseModel):
    sheet_url: str


class FullPipelineRequest(BaseModel):
    drive_folder_url: str
    sheets_url: str


class PipelineSummary(BaseModel):
    total_students_processed: int
    answer_key_source: str
    results: List[StudentResult] = []
    errors: List[Dict] = []


class SheetUpdateSummary(BaseModel):
    updated: int
    not_found: List[str] = []
    name_mismatches: List[Dict] = []
    errors: List[str] = []
