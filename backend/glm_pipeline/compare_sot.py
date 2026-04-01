"""
GLM Pipeline vs SOT Comparison Script
======================================
Downloads SOT from Google Sheets, runs GLM pipeline on images,
compares results using regex-normalised entry number matching.

Usage:
    cd backend
    python -m glm_pipeline.compare_sot [--limit N] [--start N]
"""

import os
import re
import json
import time
import logging
import sys
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Entry number normalisation (matches existing pipeline approach)
# ─────────────────────────────────────────────────────────────────────

def normalize_entry_number(raw: str) -> str:
    """
    Normalise entry number for matching:
    - Strip whitespace, dots, dashes
    - Uppercase
    - Remove common OCR artefacts
    - Keep only alphanumeric characters
    """
    if not raw:
        return ""
    s = str(raw).strip().upper()
    # Remove common separators and artefacts
    s = re.sub(r'[\s\-\.\_/\\]+', '', s)
    # Keep only alphanumeric
    s = re.sub(r'[^A-Z0-9]', '', s)
    return s


def entry_numbers_match(ocr_entry: str, sot_entry: str) -> bool:
    """
    Check if two entry numbers match after normalisation.
    Also tries substring matching for partial OCR reads.
    """
    norm_ocr = normalize_entry_number(ocr_entry)
    norm_sot = normalize_entry_number(sot_entry)

    if not norm_ocr or not norm_sot:
        return False

    # Exact match
    if norm_ocr == norm_sot:
        return True

    # OCR might miss/add characters — try if one contains the other
    if norm_ocr in norm_sot or norm_sot in norm_ocr:
        return True

    # Try matching the numeric suffix (last 3-4 digits)
    ocr_digits = re.findall(r'\d+', norm_ocr)
    sot_digits = re.findall(r'\d+', norm_sot)
    if ocr_digits and sot_digits:
        # Match the last numeric group (student number)
        if ocr_digits[-1] == sot_digits[-1] and len(ocr_digits[-1]) >= 3:
            return True

    return False


def normalize_answer(raw: str) -> str:
    """Normalise an answer for comparison."""
    if not raw:
        return ""
    s = str(raw).strip().upper()
    # Remove common artefacts
    s = s.replace(")", "").replace("(", "").replace(",", "").replace(" ", "")
    s = s.replace("OPTION", "").replace("ANS", "")
    # Sort MCQ letters alphabetically
    if s.isalpha() and len(s) <= 4:
        s = "".join(sorted(s))
    return s


# ─────────────────────────────────────────────────────────────────────
# Load SOT from Google Sheets
# ─────────────────────────────────────────────────────────────────────

def load_sot() -> List[Dict]:
    """Load SOT from Google Sheets and return list of dicts."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    sheets = build("sheets", "v4", credentials=creds)

    sheet_id = "1VPp461K6L2bg086zPlYYkdgGNaTW9CS6kQgplOi52OE"
    result = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range="A1:Z500"
    ).execute()

    rows = result.get("values", [])
    if not rows:
        return []

    headers = rows[0]
    sot = []
    for row in rows[1:]:
        # Pad row to header length
        padded = row + [""] * (len(headers) - len(row))
        entry = {}
        for i, h in enumerate(headers):
            entry[h.strip()] = padded[i].strip() if i < len(padded) else ""
        sot.append(entry)

    return sot


def sot_to_lookup(sot: List[Dict]) -> Dict[str, Dict]:
    """Create a lookup dict keyed by normalised entry number."""
    lookup = {}
    for entry in sot:
        raw_entry = entry.get("Entry Number", "")
        norm = normalize_entry_number(raw_entry)
        if norm:
            lookup[norm] = entry
    return lookup


# ─────────────────────────────────────────────────────────────────────
# Run comparison
# ─────────────────────────────────────────────────────────────────────

def run_comparison(limit: int = None, start: int = 0):
    from glm_pipeline.pipeline import GLMPipeline

    print("=" * 70)
    print("GLM Pipeline vs SOT Comparison")
    print("=" * 70)

    # Load SOT
    print("\nLoading SOT from Google Sheets...")
    sot = load_sot()
    sot_lookup = sot_to_lookup(sot)
    print(f"  SOT: {len(sot)} students, {len(sot_lookup)} unique entry numbers")

    # List images
    img_dir = "glm_test_data/images"
    all_images = sorted([
        f for f in os.listdir(img_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
        and not f.lower().endswith(".heic")
    ])
    print(f"  Images: {len(all_images)} total")

    images = all_images[start:]
    if limit:
        images = images[:limit]
    print(f"  Processing: {len(images)} images (start={start}, limit={limit})")

    # Initialise pipeline
    pipeline = GLMPipeline()

    # Results
    results = []
    entry_match_count = 0
    entry_total = 0
    q_correct = {str(i): 0 for i in range(1, 6)}
    q_total = {str(i): 0 for i in range(1, 6)}
    q_attempted = {str(i): 0 for i in range(1, 6)}
    errors = []

    for idx, fname in enumerate(images):
        img_path = os.path.join(img_dir, fname)
        print(f"\n{'─'*70}")
        print(f"[{idx+1}/{len(images)}] {fname}")

        # Small delay between images to avoid rate limits
        if idx > 0:
            time.sleep(2)

        t0 = time.time()
        try:
            result = pipeline.process(img_path)
            elapsed = time.time() - t0

            ocr_entry = result.entry_number
            ocr_name = result.name
            ocr_answers = result.answers

            # Find matching SOT entry
            norm_ocr = normalize_entry_number(ocr_entry)
            matched_sot = None
            matched_sot_key = None

            # Try exact match first
            if norm_ocr in sot_lookup:
                matched_sot = sot_lookup[norm_ocr]
                matched_sot_key = norm_ocr
            else:
                # Try fuzzy match
                for sot_key, sot_entry in sot_lookup.items():
                    if entry_numbers_match(ocr_entry, sot_entry.get("Entry Number", "")):
                        matched_sot = sot_entry
                        matched_sot_key = sot_key
                        break

            entry_total += 1
            if matched_sot:
                entry_match_count += 1
                sot_entry_num = matched_sot.get("Entry Number", "")
                sot_name = matched_sot.get("Name", "")

                print(f"  OCR:  entry='{ocr_entry}' name='{ocr_name}'")
                print(f"  SOT:  entry='{sot_entry_num}' name='{sot_name}'")
                print(f"  MATCH: entry number matched ({elapsed:.1f}s)")

                # Compare answers Q1-Q5
                for q in ["1", "2", "3", "4", "5"]:
                    sot_key = f"Q{q}"
                    sot_ans = normalize_answer(matched_sot.get(sot_key, ""))
                    ocr_ans = normalize_answer(ocr_answers.get(q, ""))

                    q_total[q] += 1

                    if sot_ans == "" and ocr_ans == "":
                        # Both blank — correct
                        q_correct[q] += 1
                        status = "BLANK"
                    elif sot_ans == "" and ocr_ans != "":
                        # SOT blank but OCR found something
                        status = f"FALSE_POS (OCR='{ocr_ans}')"
                    elif sot_ans != "" and ocr_ans == "":
                        # SOT has answer but OCR missed it
                        q_attempted[q] += 1
                        status = f"MISSED (SOT='{sot_ans}')"
                    elif sot_ans == ocr_ans:
                        q_correct[q] += 1
                        q_attempted[q] += 1
                        status = "CORRECT"
                    else:
                        q_attempted[q] += 1
                        status = f"WRONG (OCR='{ocr_ans}' SOT='{sot_ans}')"

                    print(f"    Q{q}: {status}")

                results.append({
                    "image": fname,
                    "ocr_entry": ocr_entry,
                    "sot_entry": sot_entry_num,
                    "entry_matched": True,
                    "ocr_answers": ocr_answers,
                    "time": round(elapsed, 1),
                })
            else:
                print(f"  OCR:  entry='{ocr_entry}' name='{ocr_name}'")
                print(f"  NO SOT MATCH found ({elapsed:.1f}s)")
                print(f"  Answers: {ocr_answers}")
                results.append({
                    "image": fname,
                    "ocr_entry": ocr_entry,
                    "entry_matched": False,
                    "ocr_answers": ocr_answers,
                    "time": round(elapsed, 1),
                })

        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ERROR: {e} ({elapsed:.1f}s)")
            errors.append({"image": fname, "error": str(e)})
            results.append({
                "image": fname,
                "error": str(e),
                "time": round(elapsed, 1),
            })

    # ── Summary ──
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Images processed: {len(images)}")
    print(f"Errors: {len(errors)}")
    print(f"\nEntry Number Matching:")
    print(f"  Matched: {entry_match_count}/{entry_total} ({entry_match_count/max(1,entry_total)*100:.1f}%)")
    print(f"\nPer-Question Accuracy (matched students only):")
    total_correct = 0
    total_q = 0
    for q in ["1", "2", "3", "4", "5"]:
        pct = q_correct[q] / max(1, q_total[q]) * 100
        print(f"  Q{q}: {q_correct[q]}/{q_total[q]} correct ({pct:.1f}%)")
        total_correct += q_correct[q]
        total_q += q_total[q]
    overall = total_correct / max(1, total_q) * 100
    print(f"\n  OVERALL: {total_correct}/{total_q} ({overall:.1f}%)")

    # Save results
    out_path = "glm_test_data/comparison_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "summary": {
                "images_processed": len(images),
                "errors": len(errors),
                "entry_match_rate": f"{entry_match_count}/{entry_total}",
                "overall_accuracy": f"{total_correct}/{total_q} ({overall:.1f}%)",
                "per_question": {
                    f"Q{q}": f"{q_correct[q]}/{q_total[q]}" for q in ["1","2","3","4","5"]
                },
            },
            "results": results,
            "errors": errors,
        }, f, indent=2)
    print(f"\nDetailed results saved to: {out_path}")


if __name__ == "__main__":
    limit = None
    start = 0
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--limit" and i + 2 <= len(sys.argv[1:]):
            limit = int(sys.argv[i + 2])
        if arg == "--start" and i + 2 <= len(sys.argv[1:]):
            start = int(sys.argv[i + 2])

    run_comparison(limit=limit, start=start)
