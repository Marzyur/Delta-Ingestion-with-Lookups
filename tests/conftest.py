import os
import sys
from dotenv import load_dotenv
load_dotenv()
# Ensure project root is importable during tests
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Provide a default DATABASE_URL for import-time settings in tests
os.environ.setdefault(
    "DATABASE_URL",
    'postgresql+asyncpg://neondb_owner:npg_HtAvDb9PLW5r@ep-misty-sound-airy8nhs-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require'

)
