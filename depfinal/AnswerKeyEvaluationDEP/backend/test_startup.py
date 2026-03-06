import sys
import os

# Add the current directory to sys.path if needed
sys.path.append(os.path.abspath("."))

print("Testing imports...")
try:
    from fastapi import FastAPI
    print("✅ fastapi imported")
    from api import endpoints
    print("✅ api.endpoints imported")
    from database import Database
    print("✅ database.Database imported")
    from models import User, UserRole
    print("✅ models.User imported")
    
    print("Attempting to initialize FastAPI app...")
    from main import app
    print("✅ FastAPI app initialized successfully")
except Exception as e:
    print(f"❌ Error during import: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("All imports successful!")
