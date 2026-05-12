#!/usr/bin/env python3
"""Compare two workbook copies (cell-wise or Quiz1 totals from Quiz1_Marks)."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd


def align_shapes(
    a: pd.DataFrame, b: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    max_r = max(a.shape[0], b.shape[0])
    max_c = max(a.shape[1], b.shape[1])
    aa = a.reindex(index=range(max_r), columns=range(max_c))
    bb = b.reindex(index=range(max_r), columns=range(max_c))
    return aa, bb


def cells_equal(x, y) -> bool:
    if pd.isna(x) and pd.isna(y):
        return True
    if pd.isna(x) or pd.isna(y):
        return False
    if isinstance(x, (float, int)) and isinstance(y, (float, int)):
        try:
            if float(x) == float(y):
                return True
        except (TypeError, ValueError):
            pass
    sx = x if isinstance(x, str) else str(x).strip()
    sy = y if isinstance(y, str) else str(y).strip()
    try:
        fx, fy = float(sx), float(sy)
        if fx == fy:
            return True
    except (ValueError, TypeError):
        pass
    return sx == sy


def compare_workbooks(path_a: Path, path_b: Path) -> dict:
    xl_a = pd.ExcelFile(path_a)
    xl_b = pd.ExcelFile(path_b)
    sheets_a = set(xl_a.sheet_names)
    sheets_b = set(xl_b.sheet_names)
    all_sheets = sorted(sheets_a | sheets_b)

    same_total = 0
    diff_total = 0
    per_sheet = []

    for name in all_sheets:
        if name not in sheets_a or name not in sheets_b:
            # Count entire missing sheet as all different vs empty notion — skip trivial; user has same sheets
            only = "missing in A" if name not in sheets_a else "missing in B"
            per_sheet.append((name, 0, 0, None, only))
            continue

        df_a = pd.read_excel(path_a, sheet_name=name, header=None)
        df_b = pd.read_excel(path_b, sheet_name=name, header=None)
        aa, bb = align_shapes(df_a, df_b)
        same = diff = 0
        for i in aa.index:
            for j in aa.columns:
                sx = aa.loc[i, j]
                dx = bb.loc[i, j]
                if cells_equal(sx, dx):
                    same += 1
                else:
                    diff += 1
        same_total += same
        diff_total += diff
        denom = same + diff
        pct = (100.0 * same / denom) if denom else 0.0
        per_sheet.append((name, same, diff, pct, ""))

    total = same_total + diff_total
    return {
        "same": same_total,
        "diff": diff_total,
        "total": total,
        "pct_same": 100.0 * same_total / total if total else 0.0,
        "pct_diff": 100.0 * diff_total / total if total else 0.0,
        "per_sheet": per_sheet,
    }


def normalize_entry(value) -> str | None:
    if pd.isna(value):
        return None
    t = "".join(str(value).split()).upper()
    return t if t else None


def extract_quiz1_total_marks(
    path: Path, *, sheet_name: str = "Quiz1_Marks", marks_column: str = "Marks"
) -> dict[str, float]:
    """Map normalized Entry Number -> Marks from first column key."""
    df = pd.read_excel(path, sheet_name=sheet_name, header=0)
    out: dict[str, float] = {}
    key_col = df.columns[0]
    for _, row in df.iterrows():
        e = normalize_entry(row[key_col])
        if not e:
            continue
        m = pd.to_numeric(row[marks_column], errors="coerce")
        if pd.isna(m):
            continue
        out[e] = float(m)
    return out


def diff_bucket(abs_diff: float) -> float:
    if abs_diff != abs_diff:  # NaN
        return float("nan")
    r = round(abs_diff)
    if abs(r - abs_diff) < 1e-9:
        return float(int(r))
    return float(abs_diff)


def compare_quiz_totals(path_a: Path, path_b: Path) -> dict:
    m_a = extract_quiz1_total_marks(path_a)
    m_b = extract_quiz1_total_marks(path_b)
    keys_a, keys_b = set(m_a), set(m_b)
    common = keys_a & keys_b
    only_a = keys_a - keys_b
    only_b = keys_b - keys_a

    hist: Counter[float] = Counter()
    for e in common:
        ad = abs(m_a[e] - m_b[e])
        hist[diff_bucket(ad)] += 1

    n = len(common)
    n_diff = n - hist.get(0.0, 0)
    return {
        "matched": n,
        "same_marks": int(hist.get(0.0, 0)),
        "different_marks": int(n_diff),
        "hist": dict(sorted(hist.items(), key=lambda x: (isinstance(x[0], float), x[0]))),
        "only_a": sorted(only_a),
        "only_b": sorted(only_b),
        "max_diff": max((abs(m_a[e] - m_b[e]) for e in common), default=0.0),
    }


def report_skipped_questions(path: Path) -> None:
    """No per-Q marks in Quiz1_Marks, or blank Q cells in studentResponse."""
    df = pd.read_excel(path, sheet_name="Quiz1_Marks", header=0)
    qcols = [
        c for c in df.columns if str(c).startswith("Q") and len(str(c)) <= 4
    ]
    has_entry = df["Entry Number"].notna()
    all_q_blank = df.loc[has_entry, qcols].isna().all(axis=1)
    n_no_graded_q = int(all_q_blank.sum())

    sr = pd.read_excel(path, sheet_name="studentResponse_Quiz1_Marks", header=0)
    rq = [c for c in sr.columns if str(c).startswith("Q")]
    sr_ok = sr["Entry Number"].notna()
    blank_mask = sr.loc[sr_ok, rq].isna()
    n_students_blank_resp = int(blank_mask.any(axis=1).sum())
    n_blank_cells = int(blank_mask.sum().sum())

    print(f"  ({path.name})")
    print(
        "    Quiz1_Marks: students with Entry Number but every Q1–Q20 mark "
        f"blank (no per-question score row): {n_no_graded_q}"
    )
    print(
        "    studentResponse_Quiz1_Marks: students with ≥1 blank Q "
        f"(unanswered / not parsed): {n_students_blank_resp}"
    )
    print(f"    └─ Blank question cells in those rows: {n_blank_cells}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("a", nargs="?", default="HS101.xlsx", type=Path)
    p.add_argument("b", nargs="?", default="HS101 (1).xlsx", type=Path)
    p.add_argument(
        "--quiz-totals",
        action="store_true",
        help="Compare Marks column on Quiz1_Marks (by normalized Entry Number).",
    )
    p.add_argument(
        "--skipped",
        action="store_true",
        help="Count students with skipped/missing questions (per file).",
    )
    args = p.parse_args()

    print("Files:", args.a.resolve(), "|", args.b.resolve())

    if args.skipped:
        print()
        print("Skipped / missing questions:")
        report_skipped_questions(args.a)
        report_skipped_questions(args.b)
        return

    if args.quiz_totals:
        r = compare_quiz_totals(args.a, args.b)
        print()
        print(
            'Sheet "Quiz1_Marks", column "Marks"; students matched by '
            "Entry Number (whitespace-normalized)."
        )
        print(f"  Students matched in both files: {r['matched']}")
        print(f"  Same total marks:      {r['same_marks']}")
        pct = (
            (100 * r["different_marks"] / r["matched"]) if r["matched"] else 0.0
        )
        print(
            f"  Different total marks:{r['different_marks']} ({pct:.2f}% of matched)"
        )
        print()
        print("  Difference (|Δ| marks): count")
        for k, v in r["hist"].items():
            kk = int(k) if k == int(k) else k
            print(f"    {kk}: {v}")
        if r["max_diff"]:
            print(f"  Max |Δ|: {r['max_diff']:g}")
        if r["only_a"]:
            print(f"  Entry numbers only in A: {len(r['only_a'])} — sample {r['only_a'][:5]}...")
        if r["only_b"]:
            print(f"  Entry numbers only in B: {len(r['only_b'])} — sample {r['only_b'][:5]}...")
        return

    r = compare_workbooks(args.a, args.b)

    print()
    print("Overall (aligned grid per sheet, pad missing rows/cols with NaN)")
    print(f"  Same cells:     {r['same']:,}")
    print(f"  Different cells:{r['diff']:,}")
    print(f"  Total cells:    {r['total']:,}")
    print(f"  Same:     {r['pct_same']:.2f}%")
    print(f"  Different:{r['pct_diff']:.2f}%")
    print()
    print("Per sheet:")
    for name, same, diff, pct, note in r["per_sheet"]:
        if note:
            print(f"  {name}: {note}")
        elif pct is None:
            print(f"  {name}: n/a")
        else:
            d = same + diff
            print(f"  {name}: same {same:,} / diff {diff:,} ({100*same/d:.2f}% same)")


if __name__ == "__main__":
    main()
