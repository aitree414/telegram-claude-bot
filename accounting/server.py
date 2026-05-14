"""Accounting Web App - Flask Backend Server"""

import csv
import json
import os
import re
import secrets
import shutil
import tempfile
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO
from functools import wraps
from flask import Flask, jsonify, request, send_file, session
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import pytesseract
    from PIL import Image as PILImage
    import fitz  # PyMuPDF
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    PILImage = None

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = secrets.token_hex(32)
CORS(app, supports_credentials=True)

ACCOUNTING_DIR = '/Users/aitree414/Accounting'
PROJECTS_DIR = os.path.join(ACCOUNTING_DIR, 'projects')
AUTH_FILE = os.path.join(ACCOUNTING_DIR, '.accounting.auth')
SUPPLIERS_FILE = os.path.join(ACCOUNTING_DIR, 'suppliers.json')
RATES_FILE = os.path.join(ACCOUNTING_DIR, 'exchange_rates.json')
BACKUP_DIR = os.path.join(ACCOUNTING_DIR, 'backups')

TZ_HK = timezone(timedelta(hours=8))


def init_auth():
    """Create auth file if it doesn't exist."""
    if not os.path.exists(AUTH_FILE):
        users = {
            "tree": generate_password_hash("TreeWong1", method='pbkdf2:sha256'),
            "wyan": generate_password_hash("WyanYeung1", method='pbkdf2:sha256'),
        }
        with open(AUTH_FILE, 'w') as f:
            json.dump(users, f)


def load_users():
    """Load users from auth file."""
    if not os.path.exists(AUTH_FILE):
        init_auth()
    with open(AUTH_FILE, 'r') as f:
        return json.load(f)


def login_required(f):
    """Decorator to require login for API routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

CSV_HEADERS = ['日期', '類型', '分類', '供應商/客戶', '項目描述', '金額', '貨幣', '付款狀態', '備註', '檔案']


def parse_amount(val):
    """Parse amount string to float, return 0 on failure."""
    try:
        return float(val.replace(',', ''))
    except (ValueError, AttributeError):
        return 0.0


def format_amount(val, raw=None):
    """Format amount for CSV output, preserving original format when possible."""
    if raw is not None:
        return raw
    if isinstance(val, str):
        return val
    s = str(val)
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s if s != '-0' else '0'


def read_csv(filepath):
    """Read CSV file and return list of dicts with row indices."""
    rows = []
    if not os.path.exists(filepath):
        return rows
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            row['_index'] = idx
            row['_amount_raw'] = row.get('金額', '0')
            row['金額'] = round(parse_amount(row.get('金額', 0)), 2)
            rows.append(row)
    return rows


def write_csv(filepath, rows):
    """Write list of dicts back to CSV file."""
    with open(filepath, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            out = {h: row.get(h, '') for h in CSV_HEADERS}
            out['金額'] = format_amount(row.get('金額', 0), row.get('_amount_raw'))
            writer.writerow(out)


def write_project_json(project_dir, data):
    """Write dict to project.json."""
    path = os.path.join(project_dir, 'project.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def read_project_json(project_dir):
    """Read project.json and return dict."""
    path = os.path.join(project_dir, 'project.json')
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def compute_summary(transactions):
    """Compute financial summary from transaction list."""
    total_income = round(sum(t['金額'] for t in transactions if t.get('類型') == 'income'), 2)
    total_expense = round(sum(t['金額'] for t in transactions if t.get('類型') == 'expense'), 2)
    pending_income = round(sum(t['金額'] for t in transactions if t.get('類型') == 'income' and t.get('付款狀態') == 'pending'), 2)
    pending_expense = round(sum(t['金額'] for t in transactions if t.get('類型') == 'expense' and t.get('付款狀態') == 'pending'), 2)
    return {
        'total_income': total_income,
        'total_expense': total_expense,
        'profit': round(total_income - total_expense, 2),
        'pending_income': pending_income,
        'pending_expense': pending_expense,
        'transaction_count': len(transactions),
    }


def extract_year(info, code):
    """Extract year from project info, falling back to code."""
    for key in ('created', 'start_date'):
        val = info.get(key, '')
        if val:
            m = re.match(r'(\d{4})', str(val))
            if m:
                return int(m.group(1))
    m = re.search(r'(\d{4})', code)
    if m:
        return int(m.group(1))
    return datetime.now(TZ_HK).year


def get_projects_list():
    """Get list of all projects with basic info and summaries."""
    projects = []
    if not os.path.exists(PROJECTS_DIR):
        return projects
    for name in sorted(os.listdir(PROJECTS_DIR)):
        project_dir = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(project_dir):
            continue
        info = read_project_json(project_dir)
        code = info.get('code', name)
        year = extract_year(info, code)
        csv_path = os.path.join(project_dir, 'transactions.csv')
        transactions = read_csv(csv_path)
        summary = compute_summary(transactions)
        projects.append({
            'code': code,
            'name': info.get('name', name),
            'year': year,
            'status': info.get('status', 'unknown'),
            'created': info.get('created', ''),
            **summary,
        })
    return projects


def get_years_data():
    """Aggregate project data by year."""
    projects = get_projects_list()
    years = {}
    for p in projects:
        y = p['year']
        if y not in years:
            years[y] = {'year': y, 'projects': []}
        years[y]['projects'].append(p['code'])
    # Compute totals per year
    result = []
    for y in sorted(years.keys(), reverse=True):
        year_projects = [p for p in projects if p['year'] == y]
        result.append({
            'year': y,
            'total_income': round(sum(p['total_income'] for p in year_projects), 2),
            'total_expense': round(sum(p['total_expense'] for p in year_projects), 2),
            'profit': round(sum(p['profit'] for p in year_projects), 2),
            'project_count': len(year_projects),
            'projects': year_projects,
        })
    return result


# ---- Auth Routes ----

@app.route('/api/login', methods=['POST'])
def api_login():
    """Login with username and password."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    username = data.get('username', '')
    password = data.get('password', '')
    users = load_users()

    if username not in users:
        return jsonify({'error': 'Invalid credentials'}), 401

    if not check_password_hash(users[username], password):
        return jsonify({'error': 'Invalid credentials'}), 401

    session['username'] = username
    session.permanent = True
    return jsonify({'success': True, 'username': username})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    """Logout current user."""
    session.clear()
    return jsonify({'success': True})


@app.route('/api/me')
def api_me():
    """Check if user is logged in."""
    if 'username' in session:
        return jsonify({'logged_in': True, 'username': session['username']})
    return jsonify({'logged_in': False})


# ---- API Routes ----

@app.route('/')
def index():
    return app.send_static_file('index.html')


@app.route('/api/projects')
@login_required
def api_projects():
    """List all projects with summaries."""
    return jsonify(get_projects_list())


@app.route('/api/projects/<code>')
@login_required
def api_project_detail(code):
    """Get single project detail with all transactions."""
    project_dir = os.path.join(PROJECTS_DIR, code)
    if not os.path.isdir(project_dir):
        return jsonify({'error': 'Project not found'}), 404

    info = read_project_json(project_dir)
    csv_path = os.path.join(project_dir, 'transactions.csv')
    transactions = read_csv(csv_path)
    summary = compute_summary(transactions)

    return jsonify({
        'code': code,
        'name': info.get('name', code),
        'status': info.get('status', 'unknown'),
        'created': info.get('created', ''),
        'info': info,
        'transactions': transactions,
        **summary,
    })


@app.route('/api/projects/<code>', methods=['PATCH'])
@login_required
def api_update_project(code):
    """Update project info (e.g., status)."""
    project_dir = os.path.join(PROJECTS_DIR, code)
    if not os.path.isdir(project_dir):
        return jsonify({'error': 'Project not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    info = read_project_json(project_dir)
    info.update(data)
    write_project_json(project_dir, info)

    return jsonify({'success': True, 'project': info})


@app.route('/api/projects/<code>/upload', methods=['POST'])
@login_required
def api_upload_file(code):
    """Upload a file for a project."""
    project_dir = os.path.join(PROJECTS_DIR, code)
    if not os.path.isdir(project_dir):
        return jsonify({'error': 'Project not found'}), 404

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Validate extension
    allowed = {'pdf', 'doc', 'docx', 'xlsx', 'jpg', 'png', 'jpeg', 'csv'}
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed:
        return jsonify({'error': f'File type .{ext} not allowed'}), 400

    # Ensure files directory exists
    files_dir = os.path.join(project_dir, 'files')
    os.makedirs(files_dir, exist_ok=True)

    # Save file
    filepath = os.path.join(files_dir, f.filename)
    f.save(filepath)

    return jsonify({'filename': f.filename}), 201


@app.route('/api/projects/<code>/files/<filename>')
@login_required
def api_download_file(code, filename):
    """Download a file for a project."""
    project_dir = os.path.join(PROJECTS_DIR, code)
    filepath = os.path.join(project_dir, 'files', filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    return send_file(filepath)


@app.route('/api/projects/<code>/transactions', methods=['POST'])
@login_required
def api_add_transaction(code):
    """Add a new transaction to a project."""
    project_dir = os.path.join(PROJECTS_DIR, code)
    if not os.path.isdir(project_dir):
        return jsonify({'error': 'Project not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    csv_path = os.path.join(project_dir, 'transactions.csv')
    transactions = read_csv(csv_path)

    new_row = {h: '' for h in CSV_HEADERS}
    for h in CSV_HEADERS:
        val = data.get(h, data.get({
            '日期': 'date', '類型': 'type', '分類': 'category',
            '供應商/客戶': 'vendor', '項目描述': 'description',
            '金額': 'amount', '貨幣': 'currency', '付款狀態': 'status',
            '備註': 'notes', '檔案': 'file',
        }.get(h, ''), ''))
        if val is None:
            val = ''
        new_row[h] = str(val) if isinstance(val, str) else format_amount(val)

    new_row['_amount_raw'] = format_amount(
        round(parse_amount(new_row.get('金額', '0')), 2)
    )
    new_row['金額'] = round(parse_amount(new_row.get('金額', 0)), 2)

    transactions.append(new_row)
    write_csv(csv_path, transactions)

    return jsonify({'success': True, 'index': len(transactions) - 1}), 201


@app.route('/api/projects/<code>/transactions/<int:idx>', methods=['PUT'])
@login_required
def api_update_transaction(code, idx):
    """Update a transaction by index."""
    project_dir = os.path.join(PROJECTS_DIR, code)
    if not os.path.isdir(project_dir):
        return jsonify({'error': 'Project not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    csv_path = os.path.join(project_dir, 'transactions.csv')
    transactions = read_csv(csv_path)

    if idx < 0 or idx >= len(transactions):
        return jsonify({'error': 'Transaction index out of range'}), 404

    for h in CSV_HEADERS:
        if h in data:
            val = data[h]
            transactions[idx][h] = str(val) if isinstance(val, str) else format_amount(val)
            if h == '金額':
                raw = str(val) if isinstance(val, str) else format_amount(val)
                transactions[idx]['_amount_raw'] = format_amount(parse_amount(raw))

    write_csv(csv_path, transactions)
    return jsonify({'success': True})


@app.route('/api/projects/<code>/transactions/<int:idx>', methods=['DELETE'])
@login_required
def api_delete_transaction(code, idx):
    """Delete a transaction by index."""
    project_dir = os.path.join(PROJECTS_DIR, code)
    if not os.path.isdir(project_dir):
        return jsonify({'error': 'Project not found'}), 404

    csv_path = os.path.join(project_dir, 'transactions.csv')
    transactions = read_csv(csv_path)

    if idx < 0 or idx >= len(transactions):
        return jsonify({'error': 'Transaction index out of range'}), 404

    transactions.pop(idx)
    write_csv(csv_path, transactions)
    return jsonify({'success': True})


# ---- Years API ----

@app.route('/api/years')
@login_required
def api_years():
    """List all years with aggregated totals."""
    return jsonify(get_years_data())


@app.route('/api/years/<int:year>')
@login_required
def api_year_detail(year):
    """Get projects and totals for a specific year."""
    projects = get_projects_list()
    year_projects = [p for p in projects if p['year'] == year]
    if not year_projects:
        return jsonify({'error': 'Year not found'}), 404
    return jsonify({
        'year': year,
        'total_income': round(sum(p['total_income'] for p in year_projects), 2),
        'total_expense': round(sum(p['total_expense'] for p in year_projects), 2),
        'profit': round(sum(p['profit'] for p in year_projects), 2),
        'project_count': len(year_projects),
        'projects': year_projects,
    })


# ---- Supplier Management ----

def load_suppliers():
    """Load suppliers from suppliers.json."""
    if not os.path.exists(SUPPLIERS_FILE):
        return {}
    with open(SUPPLIERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_suppliers(data):
    """Save suppliers to suppliers.json."""
    with open(SUPPLIERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def extract_suppliers_from_csv():
    """Scan all project CSVs and return deduplicated supplier names."""
    suppliers = {}
    if not os.path.exists(PROJECTS_DIR):
        return suppliers
    for name in sorted(os.listdir(PROJECTS_DIR)):
        project_dir = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(project_dir):
            continue
        csv_path = os.path.join(project_dir, 'transactions.csv')
        transactions = read_csv(csv_path)
        for tx in transactions:
            vendor = tx.get('供應商/客戶', '').strip()
            if not vendor:
                continue
            if vendor not in suppliers:
                suppliers[vendor] = {'name': vendor, 'projects': set(), 'transactions': 0, 'first_seen': None, 'last_seen': None}
            suppliers[vendor]['projects'].add(name)
            suppliers[vendor]['transactions'] += 1
            tx_date = tx.get('日期', '')
            if tx_date:
                if not suppliers[vendor]['first_seen'] or tx_date < suppliers[vendor]['first_seen']:
                    suppliers[vendor]['first_seen'] = tx_date
                if not suppliers[vendor]['last_seen'] or tx_date > suppliers[vendor]['last_seen']:
                    suppliers[vendor]['last_seen'] = tx_date
    # Convert sets to lists for JSON serialization
    for s in suppliers.values():
        s['projects'] = sorted(s['projects'])
    return suppliers


@app.route('/api/suppliers')
@login_required
def api_suppliers():
    """List all suppliers. Use ?rescan=1 to rescan CSV files."""
    rescan = request.args.get('rescan', '0') == '1'
    if rescan:
        scanned = extract_suppliers_from_csv()
        saved = load_suppliers()
        for name, data in scanned.items():
            if name in saved:
                data.update({k: v for k, v in saved[name].items() if k in ('contact', 'phone', 'email', 'notes')})
        save_suppliers(scanned)
        return jsonify(sorted(scanned.values(), key=lambda x: x['name'].lower()))

    suppliers = load_suppliers()
    if not suppliers:
        # Auto-scan on first access
        suppliers = extract_suppliers_from_csv()
        save_suppliers(suppliers)
    return jsonify(sorted(suppliers.values(), key=lambda x: x['name'].lower()))


@app.route('/api/suppliers/<path:name>')
@login_required
def api_supplier_detail(name):
    """Get supplier detail with all cross-project transactions."""
    suppliers = load_suppliers()
    supplier = suppliers.get(name)
    if not supplier:
        return jsonify({'error': 'Supplier not found'}), 404

    # Collect all transactions across projects
    all_transactions = []
    if os.path.exists(PROJECTS_DIR):
        for proj_name in sorted(os.listdir(PROJECTS_DIR)):
            project_dir = os.path.join(PROJECTS_DIR, proj_name)
            if not os.path.isdir(project_dir):
                continue
            csv_path = os.path.join(project_dir, 'transactions.csv')
            transactions = read_csv(csv_path)
            for tx in transactions:
                if tx.get('供應商/客戶', '').strip() == name:
                    tx['_project'] = proj_name
                    all_transactions.append(tx)

    return jsonify({
        'name': name,
        'contact': supplier.get('contact', ''),
        'phone': supplier.get('phone', ''),
        'email': supplier.get('email', ''),
        'notes': supplier.get('notes', ''),
        'projects': supplier.get('projects', []),
        'transactions': all_transactions,
    })


@app.route('/api/suppliers/<path:name>', methods=['PATCH'])
@login_required
def api_update_supplier(name):
    """Update supplier contact info/notes."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    suppliers = load_suppliers()
    if name not in suppliers:
        return jsonify({'error': 'Supplier not found'}), 404

    for field in ('contact', 'phone', 'email', 'notes'):
        if field in data:
            suppliers[name][field] = data[field]

    save_suppliers(suppliers)
    return jsonify({'success': True, 'supplier': suppliers[name]})


# ---- Invoice OCR ----

def ocr_image(img: 'PILImage.Image') -> str:
    """Run Tesseract OCR on a PIL Image, returning extracted text."""
    # Use both English and Traditional Chinese
    custom_config = r'--oem 3 --psm 6'
    text = pytesseract.image_to_string(img, lang='eng+chi_tra', config=custom_config)
    return text.strip()


def parse_ocr_text(text: str) -> dict:
    """Parse OCR text to extract invoice fields."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    full_text = '\n'.join(lines)

    result = {'date': None, 'amount': None, 'currency': None, 'vendor': None, 'description': None}

    # Extract date - look for common date patterns
    date_patterns = [
        r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',      # 2026-04-13 or 2026/04/13
        r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})',      # 13-04-2026 or 04/13/2026
    ]
    for pattern in date_patterns:
        m = re.search(pattern, full_text)
        if m:
            raw = m.group(1)
            # Normalize to YYYY-MM-DD
            parts = re.split(r'[-/]', raw)
            if len(parts[0]) == 4:
                result['date'] = f'{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}'
            else:
                result['date'] = f'{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}'
            break

    # Extract currency
    currency_map = {'HKD': 'HKD', 'USD': 'USD', 'TWD': 'TWD', 'CNY': 'CNY', 'EUR': 'EUR',
                    'HK$': 'HKD', 'US$': 'USD', 'NT$': 'TWD', '¥': 'CNY', '€': 'EUR',
                    '港元': 'HKD', '港幣': 'HKD', '美元': 'USD', '台幣': 'TWD', '人民幣': 'CNY'}
    for sym, code in currency_map.items():
        if sym in full_text:
            result['currency'] = code
            break

    # Extract amount - look for currency amount patterns
    amount_patterns = [
        r'(?:總計|TOTAL|總額|合計|Amount Due|Grand Total)\s*:?\s*[$HKDTW EUR€¥]*\s*([\d,]+\.?\d*)',
        r'(?:HK\$|US\$|NT\$|¥|€)\s*([\d,]+\.\d{2})',
        r'(?:TOTAL|total)\s*[$HKDTW EUR€¥]*\s*([\d,]+\.\d{2})',
    ]
    for pattern in amount_patterns:
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            try:
                result['amount'] = float(m.group(1).replace(',', ''))
                break
            except ValueError:
                continue

    # If no structured amount found, find the largest number that looks like an amount
    if result['amount'] is None:
        amounts = re.findall(r'([\d,]+\.\d{2})', full_text)
        if amounts:
            nums = [float(a.replace(',', '')) for a in amounts]
            # Heuristic: pick the most common reasonable amount
            result['amount'] = max(nums)

    # Extract vendor - first line or after "發票" / "INVOICE"
    vendor_keywords = ['供應商', '客戶', '賣方', 'Company', 'Vendor', 'Bill To', 'Sold by']
    for kw in vendor_keywords:
        for i, line in enumerate(lines):
            if kw.lower() in line.lower() and i + 1 < len(lines):
                candidate = lines[i + 1].strip()
                if candidate and len(candidate) < 100:
                    result['vendor'] = candidate
                    break
        if result['vendor']:
            break

    # Fallback vendor: first non-empty, non-date line
    if not result['vendor'] and lines:
        for line in lines:
            # Skip lines that look like dates, numbers, or common headers
            if re.match(r'^[\d\s\-,./:()]+$', line):
                continue
            if re.match(r'^(TOTAL|INVOICE|發票|日期|Date|Page|Tel|Fax|www)', line, re.IGNORECASE):
                continue
            if len(line) > 3:
                result['vendor'] = line
                break

    # Try to extract description
    desc_keywords = ['項目', '描述', 'Description', 'Item', 'Product', 'Service']
    for kw in desc_keywords:
        for i, line in enumerate(lines):
            if kw.lower() in line.lower() and i + 1 < len(lines):
                result['description'] = lines[i + 1].strip()
                break
        if result['description']:
            break

    if not result['description'] and len(lines) > 2:
        # Use middle lines as description
        for line in lines[1:-1]:
            if len(line) > 5 and not re.match(r'^[\d\s\-.,()]+$', line):
                result['description'] = line
                break

    return result


@app.route('/api/ocr', methods=['POST'])
@login_required
def api_ocr():
    """OCR invoice image/PDF using Tesseract."""
    if not OCR_AVAILABLE:
        return jsonify({'error': 'OCR dependencies not installed (pip install PyMuPDF pytesseract Pillow)'}), 500

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''

    try:
        images = []
        if ext == 'pdf':
            # PDF processing with PyMuPDF
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                f.save(tmp.name)
                try:
                    doc = fitz.open(tmp.name)
                    from io import BytesIO
                    for page_num in range(len(doc)):
                        page = doc[page_num]
                        # Render at 300 DPI
                        mat = fitz.Matrix(300/72, 300/72)
                        pix = page.get_pixmap(matrix=mat)
                        img_data = pix.tobytes('png')
                        img = PILImage.open(BytesIO(img_data))
                        images.append(img)
                    doc.close()
                finally:
                    os.unlink(tmp.name)
        elif ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif'):
            img = PILImage.open(f)
            images.append(img)
        else:
            return jsonify({'error': f'Unsupported file type: .{ext}'}), 400

        # OCR each image and combine results
        all_text = []
        for img in images:
            text = ocr_image(img)
            if text:
                all_text.append(text)

        combined = '\n'.join(all_text)
        result = parse_ocr_text(combined)

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': f'OCR failed: {str(e)}'}), 500


# ---- Exchange Rates ----

def get_hkd_rates():
    """Get HKD exchange rates with caching (1 hour TTL)."""
    now = datetime.now(TZ_HK).timestamp()

    # Check cache
    if os.path.exists(RATES_FILE):
        try:
            with open(RATES_FILE, 'r') as f:
                cached = json.load(f)
            if cached.get('_timestamp', 0) > now - 3600:
                return {k: v for k, v in cached.items() if not k.startswith('_')}
        except (json.JSONDecodeError, IOError):
            pass

    # Fetch from frankfurter.app
    try:
        url = "https://api.frankfurter.app/latest?from=HKD"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        rates = data.get('rates', {})

        # Add HKD self-rate and common currencies if missing
        rates['HKD'] = 1.0

        # Cache
        cached = {'_timestamp': now, **rates}
        with open(RATES_FILE, 'w') as f:
            json.dump(cached, f, indent=2)

        return rates
    except Exception:
        # Return fallback rates based on common approximate values
        fallback = {
            'HKD': 1.0,
            'USD': 7.82,
            'TWD': 0.242,
            'CNY': 1.08,
        }
        # Try to use expired cache if available
        if os.path.exists(RATES_FILE):
            try:
                with open(RATES_FILE, 'r') as f:
                    cached = json.load(f)
                cached_rates = {k: v for k, v in cached.items() if not k.startswith('_')}
                if cached_rates:
                    return cached_rates
            except (json.JSONDecodeError, IOError):
                pass
        return fallback


@app.route('/api/rates')
@login_required
def api_rates():
    """Return HKD exchange rates map."""
    return jsonify(get_hkd_rates())


# ---- Backup ----

def run_backup():
    """Create a timestamped backup of all accounting data."""
    now = datetime.now(TZ_HK)
    date_str = now.strftime('%Y-%m-%d')
    backup_path = os.path.join(BACKUP_DIR, date_str)
    os.makedirs(backup_path, exist_ok=True)

    # Copy auth file
    if os.path.exists(AUTH_FILE):
        shutil.copy2(AUTH_FILE, os.path.join(backup_path, '.accounting.auth'))

    # Copy data files
    for fname in ('suppliers.json', 'exchange_rates.json'):
        fpath = os.path.join(ACCOUNTING_DIR, fname)
        if os.path.exists(fpath):
            shutil.copy2(fpath, os.path.join(backup_path, fname))

    # Copy project directories
    if os.path.exists(PROJECTS_DIR):
        for proj_name in os.listdir(PROJECTS_DIR):
            proj_dir = os.path.join(PROJECTS_DIR, proj_name)
            if not os.path.isdir(proj_dir):
                continue
            proj_backup = os.path.join(backup_path, proj_name)
            os.makedirs(proj_backup, exist_ok=True)
            for fname in ('transactions.csv', 'project.json'):
                src = os.path.join(proj_dir, fname)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(proj_backup, fname))

    # Clean old backups (keep 30 days)
    cutoff = now - timedelta(days=30)
    if os.path.exists(BACKUP_DIR):
        for d in os.listdir(BACKUP_DIR):
            dpath = os.path.join(BACKUP_DIR, d)
            if not os.path.isdir(dpath):
                continue
            try:
                d_date = datetime.strptime(d, '%Y-%m-%d').replace(tzinfo=TZ_HK)
                if d_date < cutoff:
                    shutil.rmtree(dpath)
            except ValueError:
                continue

    return date_str


@app.route('/api/backup', methods=['POST'])
@login_required
def api_trigger_backup():
    """Manually trigger a backup."""
    try:
        date_str = run_backup()
        return jsonify({'success': True, 'backup_date': date_str})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/backups')
@login_required
def api_list_backups():
    """List available backups."""
    backups = []
    if os.path.exists(BACKUP_DIR):
        for d in sorted(os.listdir(BACKUP_DIR), reverse=True):
            dpath = os.path.join(BACKUP_DIR, d)
            if os.path.isdir(dpath):
                # Count files
                file_count = sum(len(files) for _, _, files in os.walk(dpath))
                backups.append({
                    'date': d,
                    'files': file_count,
                })
    return jsonify(backups)


# ---- Quotation & Invoice Management ----

COUNTERS_FILE = os.path.join(ACCOUNTING_DIR, '.counters.json')


def _load_counters():
    if not os.path.exists(COUNTERS_FILE):
        return {'quotation_next': 1, 'invoice_next': 1}
    with open(COUNTERS_FILE) as f:
        return json.load(f)


def _save_counters(counters):
    with open(COUNTERS_FILE, 'w') as f:
        json.dump(counters, f)


def _next_id(prefix):
    """Generate next ID: Q-2026-0001 or INV-2026-0001"""
    counters = _load_counters()
    key = f'{prefix.lower()}_next'
    n = counters.get(key, 1)
    counters[key] = n + 1
    _save_counters(counters)
    year = datetime.now(TZ_HK).year
    return f'{prefix}-{year}-{n:04d}'


def _load_quotations(code):
    path = os.path.join(PROJECTS_DIR, code, 'quotations.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _save_quotations(code, data):
    path = os.path.join(PROJECTS_DIR, code, 'quotations.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_invoices(code):
    path = os.path.join(PROJECTS_DIR, code, 'invoices.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _save_invoices(code, data):
    path = os.path.join(PROJECTS_DIR, code, 'invoices.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _now_iso():
    return datetime.now(TZ_HK).isoformat()


def _make_doc(client, items, currency):
    subtotal = sum(item.get('amount', item.get('qty', 0) * item.get('price', 0)) for item in items)
    tax_rate = 0
    tax = 0
    total = subtotal + tax
    return {
        'client': {
            'name': client.get('name', ''),
            'contact': client.get('contact', ''),
            'email': client.get('email', ''),
            'phone': client.get('phone', ''),
        },
        'items': [
            {'desc': i.get('desc', ''), 'qty': int(i.get('qty', 1)),
             'unit': i.get('unit', '項'), 'price': float(i.get('price', 0)),
             'amount': float(i.get('amount', int(i.get('qty', 1)) * float(i.get('price', 0))))}
            for i in items
        ],
        'subtotal': round(subtotal, 2),
        'tax_rate': tax_rate,
        'tax': round(tax, 2),
        'total': round(total, 2),
        'currency': currency or 'HKD',
        'notes': '',
    }


# ---- Quotation Routes ----

@app.route('/api/projects/<code>/quotations')
@login_required
def api_list_quotations(code):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    return jsonify(_load_quotations(code))


@app.route('/api/projects/<code>/quotations/<qid>')
@login_required
def api_get_quotation(code, qid):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    quotes = _load_quotations(code)
    q = next((q for q in quotes if q['id'] == qid), None)
    if not q:
        return jsonify({'error': 'Quotation not found'}), 404
    return jsonify(q)


@app.route('/api/projects/<code>/quotations', methods=['POST'])
@login_required
def api_create_quotation(code):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    items = data.get('items', [])
    if not items:
        return jsonify({'error': 'At least one item required'}), 400

    doc = _make_doc(data.get('client', {}), items, data.get('currency'))
    qid = _next_id('Q')
    quote = {
        'id': qid,
        'project_code': code,
        'date': data.get('date', _now_iso()[:10]),
        'valid_until': data.get('valid_until', ''),
        'status': 'draft',
        **doc,
        'created_at': _now_iso(),
        'updated_at': _now_iso(),
    }
    quotes = _load_quotations(code)
    quotes.append(quote)
    _save_quotations(code, quotes)
    return jsonify(quote), 201


@app.route('/api/projects/<code>/quotations/<qid>', methods=['PUT'])
@login_required
def api_update_quotation(code, qid):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    quotes = _load_quotations(code)
    idx = next((i for i, q in enumerate(quotes) if q['id'] == qid), None)
    if idx is None:
        return jsonify({'error': 'Quotation not found'}), 404

    for field in ('status', 'valid_until', 'notes', 'date'):
        if field in data:
            quotes[idx][field] = data[field]
    if 'client' in data:
        quotes[idx]['client'].update(data['client'])
    if 'items' in data:
        items = data['items']
        quotes[idx]['items'] = [
            {'desc': i.get('desc', ''), 'qty': int(i.get('qty', 1)),
             'unit': i.get('unit', '項'), 'price': float(i.get('price', 0)),
             'amount': float(i.get('amount', int(i.get('qty', 1)) * float(i.get('price', 0))))}
            for i in items
        ]
        subtotal = sum(i['amount'] for i in quotes[idx]['items'])
        quotes[idx]['subtotal'] = round(subtotal, 2)
        quotes[idx]['total'] = round(subtotal + quotes[idx]['tax'], 2)
    quotes[idx]['updated_at'] = _now_iso()
    _save_quotations(code, quotes)
    return jsonify(quotes[idx])


@app.route('/api/projects/<code>/quotations/<qid>', methods=['DELETE'])
@login_required
def api_delete_quotation(code, qid):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    quotes = _load_quotations(code)
    new = [q for q in quotes if q['id'] != qid]
    if len(new) == len(quotes):
        return jsonify({'error': 'Quotation not found'}), 404
    _save_quotations(code, new)
    return jsonify({'success': True})


@app.route('/api/projects/<code>/quotations/<qid>/convert', methods=['POST'])
@login_required
def api_convert_to_invoice(code, qid):
    """Convert a quotation to an invoice."""
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    quotes = _load_quotations(code)
    q = next((q for q in quotes if q['id'] == qid), None)
    if not q:
        return jsonify({'error': 'Quotation not found'}), 404

    inv_id = _next_id('INV')
    invoice = {
        'id': inv_id,
        'project_code': code,
        'quotation_id': qid,
        'date': _now_iso()[:10],
        'due_date': '',
        'paid_date': None,
        'status': 'draft',
        'client': dict(q['client']),
        'items': [dict(i) for i in q['items']],
        'subtotal': q['subtotal'],
        'tax_rate': q['tax_rate'],
        'tax': q['tax'],
        'total': q['total'],
        'currency': q['currency'],
        'notes': q.get('notes', ''),
        'created_at': _now_iso(),
        'updated_at': _now_iso(),
    }

    invoices = _load_invoices(code)
    invoices.append(invoice)
    _save_invoices(code, invoices)

    # Mark quotation as accepted
    q['status'] = 'accepted'
    q['updated_at'] = _now_iso()
    _save_quotations(code, quotes)

    return jsonify(invoice), 201


# ---- Invoice Routes ----

@app.route('/api/invoices')
@login_required
def api_all_invoices():
    """List all invoices across all projects."""
    all_inv = []
    if not os.path.exists(PROJECTS_DIR):
        return jsonify([])
    for name in sorted(os.listdir(PROJECTS_DIR)):
        if not os.path.isdir(os.path.join(PROJECTS_DIR, name)):
            continue
        for inv in _load_invoices(name):
            inv['_project'] = name
            all_inv.append(inv)
    return jsonify(all_inv)


@app.route('/api/projects/<code>/invoices')
@login_required
def api_list_invoices(code):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    return jsonify(_load_invoices(code))


@app.route('/api/projects/<code>/invoices/<iid>')
@login_required
def api_get_invoice(code, iid):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    invoices = _load_invoices(code)
    inv = next((i for i in invoices if i['id'] == iid), None)
    if not inv:
        return jsonify({'error': 'Invoice not found'}), 404
    return jsonify(inv)


@app.route('/api/projects/<code>/invoices', methods=['POST'])
@login_required
def api_create_invoice(code):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    items = data.get('items', [])
    if not items:
        return jsonify({'error': 'At least one item required'}), 400

    doc = _make_doc(data.get('client', {}), items, data.get('currency'))
    inv_id = _next_id('INV')
    invoice = {
        'id': inv_id,
        'project_code': code,
        'quotation_id': data.get('quotation_id', None),
        'date': data.get('date', _now_iso()[:10]),
        'due_date': data.get('due_date', ''),
        'paid_date': None,
        'status': 'draft',
        **doc,
        'created_at': _now_iso(),
        'updated_at': _now_iso(),
    }
    invoices = _load_invoices(code)
    invoices.append(invoice)
    _save_invoices(code, invoices)
    return jsonify(invoice), 201


@app.route('/api/projects/<code>/invoices/<iid>', methods=['PUT'])
@login_required
def api_update_invoice(code, iid):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    invoices = _load_invoices(code)
    idx = next((i for i, inv in enumerate(invoices) if inv['id'] == iid), None)
    if idx is None:
        return jsonify({'error': 'Invoice not found'}), 404

    for field in ('status', 'due_date', 'paid_date', 'notes', 'date'):
        if field in data:
            invoices[idx][field] = data[field]
    if 'client' in data:
        invoices[idx]['client'].update(data['client'])
    if 'items' in data:
        items = data['items']
        invoices[idx]['items'] = [
            {'desc': i.get('desc', ''), 'qty': int(i.get('qty', 1)),
             'unit': i.get('unit', '項'), 'price': float(i.get('price', 0)),
             'amount': float(i.get('amount', int(i.get('qty', 1)) * float(i.get('price', 0))))}
            for i in items
        ]
        subtotal = sum(i['amount'] for i in invoices[idx]['items'])
        invoices[idx]['subtotal'] = round(subtotal, 2)
        invoices[idx]['total'] = round(subtotal + invoices[idx]['tax'], 2)
    invoices[idx]['updated_at'] = _now_iso()
    _save_invoices(code, invoices)
    return jsonify(invoices[idx])


@app.route('/api/projects/<code>/invoices/<iid>', methods=['DELETE'])
@login_required
def api_delete_invoice(code, iid):
    if not os.path.isdir(os.path.join(PROJECTS_DIR, code)):
        return jsonify({'error': 'Project not found'}), 404
    invoices = _load_invoices(code)
    new = [i for i in invoices if i['id'] != iid]
    if len(new) == len(invoices):
        return jsonify({'error': 'Invoice not found'}), 404
    _save_invoices(code, new)
    return jsonify({'success': True})


# ---- Claim Form ----

def generate_claim_pdf(data: dict, output_path: str, receipt_paths: list = None) -> str:
    """Generate a claim form PDF using ReportLab. Returns the output path."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (Paragraph, Spacer, Table, TableStyle,
                                    Image as RLImage, SimpleDocTemplate)

    def _footer(c, d):
        c.saveState()
        c.setFont('Helvetica', 8)
        c.setFillColor(colors.grey)
        c.drawString(20 * mm, 10 * mm,
                     f'Generated by Accounting System - {datetime.now(TZ_HK).strftime("%Y-%m-%d %H:%M")}')
        c.drawRightString(A4[0] - 20 * mm, 10 * mm,
                          f'Page {c.getPageNumber()}')
        c.restoreState()

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    style_h1 = ParagraphStyle('H1', fontSize=20, fontName='Helvetica-Bold',
                              textColor=colors.HexColor('#1a3a5c'), spaceAfter=6)
    style_badge = ParagraphStyle('Badge', fontSize=9, fontName='Helvetica-Bold',
                                 textColor=colors.white, backColor=colors.HexColor('#6c757d'),
                                 spaceAfter=4, alignment=0)
    style_section = ParagraphStyle('Section', fontSize=13, fontName='Helvetica-Bold',
                                   textColor=colors.HexColor('#1a3a5c'),
                                   leftIndent=10, spaceAfter=10, spaceBefore=16)
    style_label = ParagraphStyle('Label', fontSize=8, fontName='Helvetica',
                                 textColor=colors.grey, spaceAfter=1)
    style_value = ParagraphStyle('Value', fontSize=10, fontName='Helvetica-Bold', spaceAfter=6)
    style_note = ParagraphStyle('Note', fontSize=10, fontName='Helvetica',
                                textColor=colors.HexColor('#555555'), spaceAfter=6)

    elements = []

    # Header
    elements.append(Paragraph('08/ CLAIM RECORD', style_badge))
    elements.append(Paragraph('Claim Form', style_h1))
    line_table = Table([['', '']], colWidths=[doc.width, 0])
    line_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 2, colors.HexColor('#1a3a5c')),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 6 * mm))

    # Section 01: Projects
    elements.append(Paragraph('01/ Projects', style_section))
    info_data = [
        [Paragraph('Project', style_label), Paragraph(data.get('project', ''), style_value),
         Paragraph('Date', style_label), Paragraph(data.get('date', ''), style_value)],
        [Paragraph('Ref #', style_label), Paragraph(data.get('ref', ''), style_value),
         Paragraph('Claimant', style_label), Paragraph(data.get('claimant', ''), style_value)],
        [Paragraph('Currency', style_label), Paragraph(data.get('currency', 'HKD'), style_value),
         Paragraph('Status', style_label), Paragraph(data.get('status', 'pending'), style_value)],
    ]
    info_table = Table(info_data, colWidths=[doc.width * 0.12, doc.width * 0.38,
                                              doc.width * 0.12, doc.width * 0.38])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 4 * mm))

    # Section 02: Items
    elements.append(Paragraph('02/ Items', style_section))

    items = data.get('items', [])
    table_data = [['#', 'Description', 'Category', 'Qty', 'Unit Price', 'Amount']]
    for i, item in enumerate(items, 1):
        table_data.append([
            str(i), item.get('description', ''), item.get('category', ''),
            str(item.get('qty', 1)),
            f"{item.get('unit_price', 0):.2f}",
            f"{item.get('amount', 0):.2f}",
        ])

    currency = data.get('currency', 'HKD')
    total = data.get('total', sum(it.get('amount', 0) for it in items))
    table_data.append(['', '', '', '', f'Total ({currency})', f'{total:.2f}'])

    col_widths = [doc.width * 0.06, doc.width * 0.30, doc.width * 0.16,
                  doc.width * 0.10, doc.width * 0.18, doc.width * 0.20]
    item_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    item_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f4f8')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (3, 1), (5, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#cccccc')),
        ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#1a3a5c')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]
    item_table.setStyle(TableStyle(item_style))
    elements.append(item_table)
    elements.append(Spacer(1, 4 * mm))

    # Section 03: Receipts
    if receipt_paths:
        elements.append(Paragraph('03/ Receipts', style_section))
        for rp in receipt_paths:
            if os.path.exists(rp) and os.path.getsize(rp) > 0:
                try:
                    from PIL import Image as PILImage
                    img = PILImage.open(rp)
                    max_w = doc.width * 0.45
                    iw, ih = img.size
                    ratio = min(max_w / iw, 120 / ih)
                    elements.append(RLImage(rp, width=iw * ratio, height=ih * ratio))
                    elements.append(Spacer(1, 4 * mm))
                except Exception:
                    pass

    # Section 04: Notes
    notes = data.get('notes', '').strip()
    if notes:
        elements.append(Paragraph('04/ Notes', style_section))
        elements.append(Paragraph(notes, style_note))

    try:
        doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
        return output_path
    except Exception as e:
        print(f"ReportLab PDF error: {e}")
        with open(output_path, 'w') as f:
            f.write('PDF generation failed')
        return output_path


@app.route('/api/claim/submit', methods=['POST'])
@login_required
def api_claim_submit():
    """Submit a claim form with receipts, create transactions, and generate PDF."""
    try:
        project_code = request.form.get('project', '').strip()
        if not project_code:
            return jsonify({'error': 'Project code is required'}), 400

        project_dir = os.path.join(PROJECTS_DIR, project_code)
        if not os.path.isdir(project_dir):
            return jsonify({'error': f'Project "{project_code}" not found'}), 404

        # Parse items
        items_raw = request.form.get('items', '[]')
        try:
            items = json.loads(items_raw)
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid items JSON'}), 400

        if not items or not isinstance(items, list):
            return jsonify({'error': 'At least one item is required'}), 400

        date = request.form.get('date', datetime.now(TZ_HK).strftime('%Y-%m-%d'))
        ref = request.form.get('ref', '').strip()
        claimant = request.form.get('claimant', '').strip()
        currency = request.form.get('currency', 'HKD')
        status = request.form.get('status', 'pending')
        notes = request.form.get('notes', '').strip()
        total = request.form.get('total', '0')

        ref_label = ref if ref else f'CLM-{project_code}-{datetime.now(TZ_HK).strftime("%Y%m%d")}'

        # Save receipt files
        files_dir = os.path.join(project_dir, 'files')
        os.makedirs(files_dir, exist_ok=True)

        receipt_files = request.files.getlist('receipts')
        saved_receipts = []
        for f in receipt_files:
            if f and f.filename:
                safe_name = f"claim_{ref_label}_{f.filename}"
                filepath = os.path.join(files_dir, safe_name)
                f.save(filepath)
                saved_receipts.append(filepath)

        # Create transactions in CSV
        csv_path = os.path.join(project_dir, 'transactions.csv')
        transactions = read_csv(csv_path)

        # Map claim categories to accounting categories
        cat_map = {
            'transport': 'transport', 'meals': 'meals', 'materials': 'materials',
            'printing': 'printing', 'venue': 'venue', 'supplies': 'supplies',
            'other': 'other',
        }

        tx_count = 0
        for item in items:
            desc = item.get('description', '').strip()
            if not desc:
                continue

            amount = item.get('amount', item.get('qty', 0) * item.get('unit_price', 0))
            category = cat_map.get(item.get('category', ''), item.get('category', 'claim'))

            new_tx = {h: '' for h in CSV_HEADERS}
            new_tx['日期'] = date
            new_tx['類型'] = 'expense'
            new_tx['分類'] = category
            new_tx['供應商/客戶'] = claimant
            new_tx['項目描述'] = f'[{ref_label}] {desc}'
            new_tx['金額'] = str(round(float(amount), 2))
            new_tx['貨幣'] = currency
            new_tx['付款狀態'] = 'paid' if status == 'paid' else 'pending'
            new_tx['備註'] = notes
            new_tx['_amount_raw'] = str(round(float(amount), 2))
            transactions.append(new_tx)
            tx_count += 1

        # Add one total transaction if no items were added individually
        if tx_count == 0 and items:
            new_tx = {h: '' for h in CSV_HEADERS}
            new_tx['日期'] = date
            new_tx['類型'] = 'expense'
            new_tx['分類'] = 'claim'
            new_tx['供應商/客戶'] = claimant
            new_tx['項目描述'] = f'[{ref_label}] Claim total'
            new_tx['金額'] = str(round(float(total), 2))
            new_tx['貨幣'] = currency
            new_tx['付款狀態'] = 'paid' if status == 'paid' else 'pending'
            new_tx['備註'] = notes
            new_tx['_amount_raw'] = str(round(float(total), 2))
            transactions.append(new_tx)
            tx_count = 1

        write_csv(csv_path, transactions)

        # Generate PDF
        claim_data = {
            'project': project_code,
            'date': date,
            'ref': ref_label,
            'claimant': claimant,
            'currency': currency,
            'status': status,
            'notes': notes,
            'total': float(total),
            'items': items,
        }

        claims_dir = os.path.join(project_dir, 'claims')
        os.makedirs(claims_dir, exist_ok=True)

        pdf_filename = f'claim_{ref_label}_{datetime.now(TZ_HK).strftime("%Y%m%d_%H%M%S")}.pdf'
        pdf_path = os.path.join(claims_dir, pdf_filename)

        try:
            result_path = generate_claim_pdf(claim_data, pdf_path, saved_receipts)
            pdf_name = os.path.basename(result_path)
        except Exception as e:
            print(f"PDF generation warning: {e}")
            pdf_name = None

        return jsonify({
            'success': True,
            'transactions_created': tx_count,
            'pdf': pdf_name,
            'claim_ref': ref_label,
        }), 201

    except Exception as e:
        return jsonify({'error': f'Claim submission failed: {str(e)}'}), 500


if __name__ == '__main__':
    init_auth()
    # Ensure data files exist
    if not os.path.exists(SUPPLIERS_FILE):
        suppliers = extract_suppliers_from_csv()
        if suppliers:
            save_suppliers(suppliers)
    app.run(host='0.0.0.0', port=3001, debug=False)
