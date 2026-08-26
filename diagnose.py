"""Diagnostic: check what Render environment looks like."""
import os, sys, platform

print("=== DIAGNOSTIC ===")
print(f"Python: {sys.version}")
print(f"Platform: {platform.platform()}")
print(f"CWD: {os.getcwd()}")
print(f"sys.path[0]: {sys.path[0]}")

token = os.getenv("TELEGRAM_BOT_TOKEN", "MISSING")
db = os.getenv("DATABASE_URL", "MISSING")
print(f"TOKEN: {token[:15]}...{token[-10:]} (len={len(token)})")
print(f"DB: {db[:40]}...")

# Test imports
for mod in ["telegram", "sqlalchemy", "asyncpg", "openai", "torch", "httpx"]:
    try:
        __import__(mod)
        print(f"  {mod}: OK")
    except Exception as e:
        print(f"  {mod}: FAIL ({e})")

print("=== END ===")
