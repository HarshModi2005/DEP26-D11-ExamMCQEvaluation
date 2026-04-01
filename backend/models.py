from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# NOTE: Authentication is handled entirely by Supabase on the frontend.
# No backend auth models needed.


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
    question_type: str  # "SMCQ", "MMCQ", "NCQ"
    correct_answer: str  # "A", "AC", "BCD", "2.5", "7.0", etc.
    positive_marks: float = 1.0
    negative_marks: float = 0.0
    
    # Legacy compatibility
    @property
    def correct_option(self) -> str:
        """Legacy compatibility property"""
        return self.correct_answer
    
    @property
    def marks(self) -> float:
        """Legacy compatibility property"""
        return self.positive_marks


class AnswerKey(BaseModel):
    total_questions: int
    answers: Dict[int, AnswerKeyEntry]  # {1: AnswerKeyEntry(...), ...}
    negative_marking: float = 0.0  # Default negative marking (can be overridden per question)
    metadata: Dict = {}  # source file, timestamp, etc.
    
    def get_question_types_summary(self) -> Dict[str, int]:
        """Get count of each question type"""
        types = {}
        for entry in self.answers.values():
            q_type = entry.question_type
            types[q_type] = types.get(q_type, 0) + 1
        return types


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
    evaluation_id: Optional[str] = None
    master_sheet_url: Optional[str] = None


class ExportToSheetsRequest(BaseModel):
    sheet_url: str
    results: Optional[List[Dict]] = None
    answer_key: Optional[Dict] = None


class SyncSheetRequest(BaseModel):
    sheet_url: str
    sheet_tab_name: str


class FullPipelineRequest(BaseModel):
    drive_folder_url: str
    sheets_url: str


class PipelineSummary(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    total_students_processed: int
    answer_key_source: str
    results: List[Any] = []
    errors: List[Dict] = []
    processing_stats: Dict = {}


class SheetUpdateSummary(BaseModel):
    updated: int
    not_found: List[str] = []
    name_mismatches: List[Dict] = []
    errors: List[str] = []
