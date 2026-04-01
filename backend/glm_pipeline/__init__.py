"""
GLM-Enhanced OCR Pipeline
=========================
A separate, self-contained pipeline that adds a Grounding Language Model (GLM)
bounding-box detection step BEFORE OCR.

Flow:
  Full Image  -->  GLM (detect bounding boxes per question + header)
              -->  Crop Service (crop each region)
              -->  OCR Service (focused extraction per crop)
              -->  Merge into standard {entry_number, name, answers} format
              -->  (existing) EvaluationService.match_and_score()

This folder is COMPLETELY INDEPENDENT of the existing OCR pipeline.
It copies what it needs and does not import from ../services/ at runtime,
so the original pipeline is never affected.
"""

__version__ = "0.1.0"
