# C Code Evaluator

This module is responsible for the automated evaluation of handwritten C programming assignments. It utilizes Optical Character Recognition (OCR) to extract source code from images of student submissions, and then compiles and evaluates the extracted code against a predefined set of test cases to determine the final score.

## 🚀 Features

- **OCR Extraction**: Extracts C source code directly from uploaded images.
- **Automated Compilation**: Automatically compiles the extracted C code in a secure and isolated manner.
- **Test Case Evaluation**: Runs the compiled executable against multiple custom test cases (`stdin`/`stdout`).
- **Detailed Feedback**: Provides detailed logs, including compilation errors, execution errors, and diffs for failing test cases.
- **Leetcode Mode**: Specifically parses problem structures similar to competitive programming platforms, executing logic using sample JSON configurations.

## 📁 Files Overview

- **`evaluate_c_from_image.py`**: The primary script for handling the end-to-end pipeline of image OCR extraction -> C Code generation -> Compilation -> Test Case Evaluation.
- **`leetcode_mode.py`**: Handles parsing and evaluating algorithm problems specifically formatted like Leetcode problems.
- **`generate_error_images_nanobanana.py`**: A utility script for generating error visualizer images (for instance, showing specifically where output diverged from the expected).
- **Test case samples**: `.json` and `.txt` files containing sample input/output test data.

## 🛠️ Usage

This module is intended to be invoked by the main `backend` processing pipelines.

```bash
# Example invocation (ensure you are within the main Python environment)
python evaluate_c_from_image.py --image <path_to_image> --testcases <path_to_testcases_json>
```

> **Note**: This module requires standard GCC compilation tools installed on the host environment to compile C files successfully.
