import os
import sys
import json
from backend.services.ocr_service import OCRService

# Since backend uses relative imports to other services, let's run it from inside backend folder.
# We will cd into backend first.
