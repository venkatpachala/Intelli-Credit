import sqlite3
conn = sqlite3.connect('backend/data.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT id, company_name, status, cam_pdf_path, cam_docx_path FROM cases WHERE cam_json IS NOT NULL ORDER BY created_at DESC').fetchall()
print('Case ID              | Status          | DOCX | PDF')
print('-'*70)
for r in rows:
    has_docx = 'YES' if r['cam_docx_path'] else 'NO'
    has_pdf  = 'YES' if r['cam_pdf_path']  else 'NO'
    cid = r['id']
    status = r['status']
    print(f'{cid:20} | {status:15} | {has_docx:4} | {has_pdf}')
conn.close()
