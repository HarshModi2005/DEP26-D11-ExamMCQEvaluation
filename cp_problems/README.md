# Competitive Programming Problems (cp_problems)

This directory contains test environments, sample problems, and expected testcases used primarily by the `c_code_evaluator` module to validate the logic for parsing and grading algorithm problems.

## 📁 Structure

Each subdirectory within this folder represents a single problem or assignment.

For example, `prefix_sum_range`:
- Contains the problem description (`PROBLEM.md`).
- Contains known correct solutions (`solution_correct.c`, `solution_correct_fastio.c`).
- Contains known incorrect or buggy solutions to test the evaluator's error reporting (`wrong_inclusive_exclusive.c`, `wrong_int_overflow.c`, etc.).
- Includes inputs/outputs testcases (`testcases.json`, `testcases.txt`).
- A JSON mapping file mapping image test cases to source data (`image_to_source_mapping.json`).

These subdirectories help verify that our automated grading scripts are functioning correctly by simulating various real-world student code submissions (both passing and failing).
