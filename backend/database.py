import sqlite3
import json
from models import Student, Submission, EvaluationResult

class Database:
    def __init__(self, db_path="evaluation.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS students
                     (id TEXT PRIMARY KEY, name TEXT, roll_number TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS submissions
                     (id TEXT PRIMARY KEY, student_id TEXT, exam_id TEXT, file_id TEXT, status TEXT, 
                      extracted_data TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS results
                     (submission_id TEXT PRIMARY KEY, score REAL, feedback TEXT, details TEXT)''')
        conn.commit()
        conn.close()
        print(f"✅ Database initialized at {self.db_path} with tables: students, submissions, results")

    def add_student(self, student: Student):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO students VALUES (?, ?, ?)",
                  (student.id, student.name, student.roll_number))
        conn.commit()
        conn.close()

    def add_submission(self, submission: Submission, extracted_data: dict = None):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        data_json = json.dumps(extracted_data) if extracted_data else None
        c.execute("INSERT OR REPLACE INTO submissions VALUES (?, ?, ?, ?, ?, ?)",
                  (submission.id, submission.student_id, submission.exam_id, submission.file_id, submission.status, data_json))
        conn.commit()
        conn.close()

    def add_result(self, result: EvaluationResult, details: dict = None):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        details_json = json.dumps(details) if details else None
        c.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?, ?)",
                  (result.submission_id, result.score, result.feedback, details_json))
        conn.commit()
        conn.close()

    def get_all_results(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT r.*, s.student_id, s.exam_id 
            FROM results r
            JOIN submissions s ON r.submission_id = s.id
        """)
        rows = c.fetchall()
        results = [dict(row) for row in rows]
        conn.close()
        return results
    
    def get_submission(self, submission_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None
