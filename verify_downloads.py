"""
verify_downloads.py - Tests the download API endpoints directly
"""
import requests, sys, os
from pathlib import Path

# We need to get a valid JWT token
# Try registering a test user (ignore if already exists)
base = "http://localhost:8000"

try:
    reg = requests.post(f"{base}/auth/register", json={
        "name": "Download Tester",
        "email": "dl_test_verify@test.com",
        "password": "Test@1234",
        "role": "credit_manager"
    }, timeout=10)
except Exception as e:
    print(f"Register request failed: {e}")
    sys.exit(1)

# Now login
login = requests.post(f"{base}/auth/login", json={
    "email": "dl_test_verify@test.com",
    "password": "Test@1234"
}, timeout=10)

if login.status_code != 200:
    print(f"Login failed: {login.text}")
    sys.exit(1)

token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print(f"Auth OK - token obtained")

# The case we want to test
case_id = "CASE_2026_B1C65E"

print(f"\nTesting PDF download for {case_id}...")
pdf_resp = requests.get(
    f"{base}/cases/{case_id}/cam/download?fmt=pdf",
    headers=headers,
    timeout=60,
    stream=True
)
print(f"  Status: {pdf_resp.status_code}")
print(f"  Content-Type: {pdf_resp.headers.get('content-type', 'N/A')}")
print(f"  Content-Disposition: {pdf_resp.headers.get('content-disposition', 'N/A')}")
if pdf_resp.ok:
    content = pdf_resp.content
    print(f"  Size: {len(content)} bytes")
    out = Path("backend/cam_output/test_download.pdf")
    out.write_bytes(content)
    print(f"  Saved to: {out}")
    print(f"  PDF DOWNLOAD: SUCCESS")
else:
    print(f"  Error: {pdf_resp.text[:500]}")
    print(f"  PDF DOWNLOAD: FAILED")

print(f"\nTesting DOCX download for {case_id}...")
docx_resp = requests.get(
    f"{base}/cases/{case_id}/cam/download?fmt=docx",
    headers=headers,
    timeout=60,
    stream=True
)
print(f"  Status: {docx_resp.status_code}")
print(f"  Content-Type: {docx_resp.headers.get('content-type', 'N/A')}")
print(f"  Content-Disposition: {docx_resp.headers.get('content-disposition', 'N/A')}")
if docx_resp.ok:
    content = docx_resp.content
    print(f"  Size: {len(content)} bytes")
    out = Path("backend/cam_output/test_download.docx")
    out.write_bytes(content)
    print(f"  Saved to: {out}")
    print(f"  DOCX DOWNLOAD: SUCCESS")
else:
    print(f"  Error: {docx_resp.text[:500]}")
    print(f"  DOCX DOWNLOAD: FAILED")

print()
if pdf_resp.ok and docx_resp.ok:
    print("OVERALL: ALL DOWNLOADS WORKING")
elif pdf_resp.ok:
    print("OVERALL: PDF OK, DOCX FAILED")
elif docx_resp.ok:
    print("OVERALL: PDF FAILED, DOCX OK")
else:
    print("OVERALL: BOTH DOWNLOADS FAILED")
