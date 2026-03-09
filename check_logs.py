import sqlite3

conn = sqlite3.connect('backend/data.db')
conn.row_factory = sqlite3.Row

# Latest case
case = conn.execute('SELECT id, company_name, status, cam_docx_path, cam_pdf_path FROM cases ORDER BY created_at DESC LIMIT 1').fetchone()
print(f"\n=== LATEST CASE ===")
print(f"  ID       : {case['id']}")
print(f"  Company  : {case['company_name']}")
print(f"  Status   : {case['status']}")
print(f"  DOCX path: {case['cam_docx_path']}")
print(f"  PDF  path: {case['cam_pdf_path']}")

# Pipeline logs for that case
print(f"\n=== PIPELINE LOGS ===")
logs = conn.execute(
    'SELECT stage, status, message, created_at FROM pipeline_logs WHERE case_id=? ORDER BY created_at ASC',
    (case['id'],)
).fetchall()
for log in logs:
    msg = log['message'] or ''
    print(f"  [{log['created_at']}] {log['stage']:20s} {log['status']:10s} | {msg[:300]}")

conn.close()
