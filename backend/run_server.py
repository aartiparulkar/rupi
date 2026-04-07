#!/usr/bin/env python
"""
Startup script for Tax Agent API
Run from anywhere - automatically sets up the environment and initializes database
"""

import os
import sys

# Ensure we're in the backend directory
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

print(f"Working directory: {os.getcwd()}")

# Initialize database
print("Initializing database...")
try:
    from models.database import init_db
    init_db()
    print("✅ Database initialized")
except Exception as e:
    print(f"⚠️ Database initialization warning: {str(e)}")

# Start uvicorn
import uvicorn

if __name__ == "__main__":
    print("🚀 Starting Tax Agent API Server...")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )
