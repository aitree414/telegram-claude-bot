"""Accounting Web App - Flask Backend Server"""

import csv
import json
import os
import re
import secrets
import shutil
import base64
import urllib.request
from datetime import datetime, timedelta, timezone
from io import StringIO
from functools import wraps
from flask import Flask, jsonify, request, send_file, session
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

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

@app.route('/api/ocr', methods=['POST'])
@login_required
def api_ocr():
    """OCR invoice image using OpenAI Vision API."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Check file type
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
        return jsonify({'error': 'Only image files are supported'}), 400

    # Read and base64 encode
    image_data = base64.b64encode(f.read()).decode('utf-8')
    media_type = f'image/{ext}' if ext != 'jpg' else 'image/jpeg'

    openai_api_key = os.environ.get('OPENAI_API_KEY')
    if not openai_api_key:
        return jsonify({'error': 'OPENAI_API_KEY not configured'}), 500

    prompt = (
        "Extract invoice information from this image. Return ONLY valid JSON with these fields:\n"
        "- date: invoice date in YYYY-MM-DD format (or null if not found)\n"
        "- amount: total amount as number (or null)\n"
        "- currency: currency code like HKD, USD, TWD (or null)\n"
        "- vendor: supplier/vendor name (or null)\n"
        "- description: brief description of what was purchased (or null)\n"
        "Example: {\"date\": \"2026-04-01\", \"amount\": 1500.00, \"currency\": \"HKD\", "
        "\"vendor\": \"ABC Company\", \"description\": \"Office supplies\"}"
    )

    payload = json.dumps({
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_data}"}}
                ]
            }
        ],
        "max_tokens": 500,
    }).encode('utf-8')

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
        content = result['choices'][0]['message']['content']
        # Try to extract JSON from the response
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            return jsonify(parsed)
        return jsonify({'error': 'Could not parse OCR result', 'raw': content}), 500
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


if __name__ == '__main__':
    init_auth()
    # Ensure data files exist
    if not os.path.exists(SUPPLIERS_FILE):
        suppliers = extract_suppliers_from_csv()
        if suppliers:
            save_suppliers(suppliers)
    app.run(host='0.0.0.0', port=3001, debug=True)
