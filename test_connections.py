"""Test Google Sheets + OpenAI connection."""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

print("=== Connection Test ===")
print(f"SERVICE_ACCOUNT_JSON: {'SET' if SERVICE_ACCOUNT_JSON else 'MISSING'}")
print(f"SHEET_ID: {SHEET_ID[:30]}..." if SHEET_ID else "SHEET_ID: MISSING")
print(f"OPENAI_KEY: {'SET' if OPENAI_KEY else 'MISSING'}")
print()

# Test 1: Google Sheets
if SERVICE_ACCOUNT_JSON and SHEET_ID:
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(
            json.loads(SERVICE_ACCOUNT_JSON), scopes=scopes
        )
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID)
        print(f"Google Sheets: CONNECTED")
        print(f"  Sheet title: {sheet.title}")
        print(f"  Worksheets: {[ws.title for ws in sheet.worksheets()]}")

        # Try reading first cell of first sheet
        ws = sheet.sheet1
        try:
            val = ws.acell("A1").value
            print(f"  A1 value: {val}")
        except Exception as e:
            print(f"  A1 read: {e}")
    except Exception as e:
        print(f"Google Sheets: FAILED - {e}")
else:
    print("Google Sheets: SKIPPED (missing env vars)")

print()

# Test 2: OpenAI
if OPENAI_KEY:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_KEY)
        # Quick model list call to verify key works
        models = client.models.list()
        print(f"OpenAI: CONNECTED ({len(list(models))} models available)")
    except Exception as e:
        print(f"OpenAI: FAILED - {e}")
else:
    print("OpenAI: SKIPPED (missing key)")

print()
print("=== Done ===")
