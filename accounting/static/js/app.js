/* Accounting System - Frontend SPA */

const API_BASE = '/api';
let currentRoute = '';
let deleteTarget = null;
let exchangeRates = null;

// ---- Utilities ----

function $id(id) { return document.getElementById(id); }

function fmtNum(n) {
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDate(dateStr) {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    return d.toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

function typeBadge(type) {
    const labels = { income: '收入', expense: '支出' };
    return `<span class="badge rounded-pill badge-${type}">${labels[type] || type}</span>`;
}

function statusBadge(status) {
    const labels = { paid: '已付款', pending: '待處理' };
    return `<span class="badge rounded-pill badge-${status}">${labels[status] || status}</span>`;
}

// ---- API Calls ----

async function apiGet(url) {
    const res = await fetch(API_BASE + url, { credentials: 'include' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function apiPost(url, data) {
    const res = await fetch(API_BASE + url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function apiPut(url, data) {
    const res = await fetch(API_BASE + url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function apiDelete(url) {
    const res = await fetch(API_BASE + url, { method: 'DELETE', credentials: 'include' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function apiPatch(url, data) {
    const res = await fetch(API_BASE + url, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

// ---- Auth ----

async function checkAuth() {
    try {
        const res = await fetch(API_BASE + '/me', { credentials: 'include' });
        const data = await res.json();
        return data.logged_in ? data : null;
    } catch {
        return null;
    }
}

function showLogin() {
    $id('loginPage').style.display = '';
    $id('app').style.display = 'none';
    $id('navUsername').textContent = '';
    $id('logoutBtn').classList.add('d-none');
    $id('loginUsername').focus();
}

function showApp(username) {
    $id('loginPage').style.display = 'none';
    $id('app').style.display = '';
    $id('navUsername').textContent = '👤 ' + username;
    $id('logoutBtn').classList.remove('d-none');
}

async function doLogin(event) {
    event.preventDefault();
    const username = $id('loginUsername').value.trim();
    const password = $id('loginPassword').value;
    const errorEl = $id('loginError');
    errorEl.classList.add('d-none');

    try {
        const res = await fetch(API_BASE + '/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ username, password }),
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || '登入失敗');
        }
        const data = await res.json();
        showApp(data.username);
        // Load exchange rates after login
        loadExchangeRates();
        navigate(window.location.hash || '#/');
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove('d-none');
    }
}

async function doLogout() {
    await fetch(API_BASE + '/logout', { method: 'POST', credentials: 'include' });
    showLogin();
    window.location.hash = '';
}

// ---- Exchange Rates ----

async function loadExchangeRates() {
    try {
        const rates = await apiGet('/rates');
        exchangeRates = rates;
    } catch {
        exchangeRates = { HKD: 1, USD: 7.82, TWD: 0.242, CNY: 1.08 };
    }
}

function toHKD(amount, currency) {
    if (!currency || currency === 'HKD' || !exchangeRates) return null;
    const rate = exchangeRates[currency];
    if (!rate) return null;
    return amount / rate;
}

function fmtAmountWithHKD(amount, currency, arrowClass) {
    const prefix = arrowClass === 'text-success' ? '+' : '-';
    let html = `<span class="fw-bold ${arrowClass}">${prefix}$${fmtNum(amount)}</span>`;
    if (currency && currency !== 'HKD') {
        const hkdEq = toHKD(amount, currency);
        if (hkdEq !== null) {
            html += `<br><small class="text-muted">≈ $${fmtNum(hkdEq)} HKD</small>`;
        }
    }
    return html;
}

// ---- Router ----

function navigate(hash) {
    const route = hash.replace(/^#\//, '') || 'dashboard';
    currentRoute = route;
    if (route === 'dashboard') {
        renderDashboard();
    } else if (route.startsWith('year/')) {
        const year = parseInt(route.replace('year/', ''), 10);
        renderYearPage(year);
    } else if (route.startsWith('project/')) {
        const code = route.replace('project/', '');
        renderProjectDetail(code);
    } else if (route === 'suppliers') {
        renderSupplierList();
    } else if (route.startsWith('supplier/')) {
        const name = decodeURIComponent(route.replace('supplier/', ''));
        renderSupplierDetail(name);
    } else if (route === 'backups') {
        renderBackups();
    } else {
        renderDashboard();
    }
}

window.addEventListener('hashchange', () => {
    checkAuth().then(user => {
        if (user) { navigate(window.location.hash); }
        else { showLogin(); }
    });
});

window.addEventListener('load', async () => {
    const user = await checkAuth();
    if (user) {
        showApp(user.username);
        await loadExchangeRates();
        navigate(window.location.hash || '#/');
    } else {
        showLogin();
    }
});

// ---- Dashboard (Year-based) ----

async function renderDashboard() {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const years = await apiGet('/years');

        if (!years || years.length === 0) {
            app.innerHTML = `
                <div class="page-header"><h4>儀表板</h4></div>
                <div class="empty-state">
                    <i class="bi bi-folder-open"></i>
                    <p>尚無專案資料</p>
                </div>`;
            return;
        }

        // Year tabs
        let html = `
            <div class="page-header">
                <h4><i class="bi bi-grid-fill me-2 text-primary"></i>專案儀表板</h4>
            </div>
            <div class="year-tabs mb-4">`;

        for (const y of years) {
            html += `<button class="year-tab" data-year="${y.year}" onclick="navigate('#/year/${y.year}')">
                <span class="year-tab-year">${y.year}</span>
                <span class="year-tab-count">${y.project_count} 個專案</span>
            </button>`;
        }

        html += '</div>';

        // Show latest year by default
        const latest = years[0];
        html += renderYearSummaryCard(latest);
        html += '<h5 class="mb-3 mt-4">專案列表</h5><div class="row g-4">';

        for (const p of latest.projects) {
            html += renderProjectCard(p);
        }

        html += '</div>';
        app.innerHTML = html;

    } catch (err) {
        if (err.message.includes('401')) {
            showLogin();
            return;
        }
        app.innerHTML = `
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderDashboard()">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

function renderYearSummaryCard(data) {
    const profitClass = data.profit >= 0 ? 'text-success' : 'text-danger';
    return `
        <div class="year-summary-card mb-4">
            <div class="row g-3">
                <div class="col-4">
                    <div class="summary-item summary-income">
                        <div class="summary-label">總收入</div>
                        <div class="summary-value">$${fmtNum(data.total_income)}</div>
                    </div>
                </div>
                <div class="col-4">
                    <div class="summary-item summary-expense">
                        <div class="summary-label">總支出</div>
                        <div class="summary-value">$${fmtNum(data.total_expense)}</div>
                    </div>
                </div>
                <div class="col-4">
                    <div class="summary-item summary-profit">
                        <div class="summary-label">總利潤</div>
                        <div class="summary-value ${profitClass}">$${fmtNum(data.profit)}</div>
                    </div>
                </div>
            </div>
        </div>`;
}

function renderProjectCard(p) {
    const profitClass = p.profit >= 0 ? 'text-success' : 'text-danger';
    return `
        <div class="col-12 col-md-6 col-lg-4">
            <div class="card project-card h-100" onclick="navigate('#/project/${p.code}')">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <h5>${p.name}</h5>
                            <small class="opacity-75">${p.code}</small>
                        </div>
                        <span class="badge bg-light text-dark">${p.transaction_count} 筆</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="d-flex justify-content-between mb-2">
                        <span>收入</span>
                        <span class="text-success fw-bold">+$${fmtNum(p.total_income)}</span>
                    </div>
                    <div class="d-flex justify-content-between mb-2">
                        <span>支出</span>
                        <span class="text-danger fw-bold">-$${fmtNum(p.total_expense)}</span>
                    </div>
                    <div class="d-flex justify-content-between pt-2 border-top">
                        <span class="fw-bold">利潤</span>
                        <span class="fw-bold ${profitClass}">$${fmtNum(p.profit)}</span>
                    </div>
                </div>
                <div class="card-footer bg-transparent border-top-0 text-end">
                    <span class="status-badge status-${p.status === 'active' ? 'active' : 'archived'}"></span>
                    <small class="text-muted">${p.status === 'active' ? '進行中' : '已歸檔'}</small>
                </div>
            </div>
        </div>`;
}

// ---- Year Page ----

async function renderYearPage(year) {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const data = await apiGet(`/years/${year}`);
        const years = await apiGet('/years');

        let html = `
            <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
                <div>
                    <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                        <i class="bi bi-arrow-left"></i>
                    </a>
                    <h4 class="d-inline">${year} 年度</h4>
                </div>
            </div>

            <div class="year-tabs mb-4">`;

        for (const y of years) {
            const active = y.year === year ? ' active' : '';
            html += `<button class="year-tab${active}" data-year="${y.year}" onclick="navigate('#/year/${y.year}')">
                <span class="year-tab-year">${y.year}</span>
                <span class="year-tab-count">${y.project_count} 個專案</span>
            </button>`;
        }

        html += '</div>';
        html += renderYearSummaryCard(data);
        html += '<h5 class="mb-3">專案列表</h5><div class="row g-4">';

        for (const p of data.projects) {
            html += renderProjectCard(p);
        }

        html += '</div>';
        app.innerHTML = html;

    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">${year} 年度</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderYearPage(${year})">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

// ---- Project Detail ----

async function renderProjectDetail(code) {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const project = await apiGet(`/projects/${code}`);

        // Stats row
        let html = `
            <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
                <div>
                    <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                        <i class="bi bi-arrow-left"></i>
                    </a>
                    <h4 class="d-inline">${project.name}</h4>
                    <span class="badge bg-secondary ms-2">${project.code}</span>
                    <span class="status-badge status-${project.status === 'active' ? 'active' : 'archived'} ms-2"></span>
                    <small class="text-muted">${project.status === 'active' ? '進行中' : '已歸檔'}</small>
                </div>
                <button class="btn btn-primary mt-2 mt-md-0" onclick="openAddModal('${project.code}')">
                    <i class="bi bi-plus-lg me-1"></i>新增交易
                </button>
            </div>

            <div class="row g-3 mb-4">
                <div class="col-6 col-md">
                    <div class="stat-card stat-income">
                        <div class="stat-icon"><i class="bi bi-cash-coin"></i></div>
                        <div class="stat-label">總收入</div>
                        <div class="stat-value">$${fmtNum(project.total_income)}</div>
                    </div>
                </div>
                <div class="col-6 col-md">
                    <div class="stat-card stat-expense">
                        <div class="stat-icon"><i class="bi bi-cart"></i></div>
                        <div class="stat-label">總支出</div>
                        <div class="stat-value">$${fmtNum(project.total_expense)}</div>
                    </div>
                </div>
                <div class="col-6 col-md">
                    <div class="stat-card stat-profit">
                        <div class="stat-icon"><i class="bi bi-graph-up-arrow"></i></div>
                        <div class="stat-label">利潤</div>
                        <div class="stat-value">$${fmtNum(project.profit)}</div>
                    </div>
                </div>
                <div class="col-6 col-md">
                    <div class="stat-card stat-pending-income">
                        <div class="stat-icon"><i class="bi bi-clock"></i></div>
                        <div class="stat-label">待收款</div>
                        <div class="stat-value">$${fmtNum(project.pending_income)}</div>
                    </div>
                </div>
                <div class="col-6 col-md">
                    <div class="stat-card stat-pending-expense">
                        <div class="stat-icon"><i class="bi bi-hourglass"></i></div>
                        <div class="stat-label">待付款</div>
                        <div class="stat-value">$${fmtNum(project.pending_expense)}</div>
                    </div>
                </div>
            </div>`;

        // Transactions table
        const txs = project.transactions || [];
        if (txs.length === 0) {
            html += `
                <div class="card">
                    <div class="card-body">
                        <div class="empty-state">
                            <i class="bi bi-receipt"></i>
                            <p>尚無交易記錄</p>
                            <button class="btn btn-primary" onclick="openAddModal('${project.code}')">
                                <i class="bi bi-plus-lg me-1"></i>新增第一筆交易
                            </button>
                        </div>
                    </div>
                </div>`;
        } else {
            html += `
                <div class="card">
                    <div class="card-body p-0">
                        <div class="table-container">
                            <table class="table table-hover mb-0">
                                <thead class="table-light">
                                    <tr>
                                        <th>日期</th>
                                        <th>類型</th>
                                        <th>分類</th>
                                        <th>供應商/客戶</th>
                                        <th>描述</th>
                                        <th class="text-end">金額</th>
                                        <th>貨幣</th>
                                        <th>狀態</th>
                                        <th>備註</th>
                                        <th class="text-center">操作</th>
                                    </tr>
                                </thead>
                                <tbody>`;

            for (const tx of txs) {
                const arrow = tx.類型 === 'income' ? 'text-success' : 'text-danger';
                const fileHtml = tx.檔案 ? `<a href="/api/projects/${project.code}/files/${tx.檔案}" target="_blank" title="${tx.檔案}"><i class="bi bi-paperclip text-muted"></i></a>` : '';

                html += `
                    <tr class="fade-in">
                        <td>${fmtDate(tx.日期)}</td>
                        <td>${typeBadge(tx.類型)}</td>
                        <td><span class="text-muted">${tx.分類 || '-'}</span></td>
                        <td>${tx['供應商/客戶'] ? `<a href="#/supplier/${encodeURIComponent(tx['供應商/客戶'])}" class="text-decoration-none">${tx['供應商/客戶']}</a>` : '-'}</td>
                        <td>${tx['項目描述'] || '-'}</td>
                        <td class="text-end">${fmtAmountWithHKD(tx.金額, tx.貨幣, arrow)}</td>
                        <td>${tx.貨幣 || 'HKD'}</td>
                        <td>${tx['付款狀態'] ? statusBadge(tx['付款狀態']) : '-'}</td>
                        <td>
                            ${tx.備註 ? `<span title="${tx.備註}">${tx.備註.length > 15 ? tx.備註.slice(0, 15) + '…' : tx.備註}</span>` : ''}
                            ${fileHtml}
                        </td>
                        <td class="text-center">
                            <button class="btn btn-sm btn-outline-primary btn-action me-1"
                                    onclick="openEditModal('${project.code}', ${tx._index})"
                                    title="編輯">
                                <i class="bi bi-pencil"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-danger btn-action"
                                    onclick="confirmDelete('${project.code}', ${tx._index})"
                                    title="刪除">
                                <i class="bi bi-trash"></i>
                            </button>
                        </td>
                    </tr>`;
            }

            html += `
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>`;
        }

        app.innerHTML = html;

    } catch (err) {
        if (err.message.includes('401')) {
            showLogin();
            return;
        }
        app.innerHTML = `
            <div class="page-header">
                <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">專案詳情</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderProjectDetail('${code}')">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

// ---- Supplier List ----

async function renderSupplierList() {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const suppliers = await apiGet('/suppliers');

        let html = `
            <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
                <div>
                    <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                        <i class="bi bi-arrow-left"></i>
                    </a>
                    <h4 class="d-inline"><i class="bi bi-building me-2 text-primary"></i>供應商/客戶</h4>
                </div>
                <button class="btn btn-outline-primary btn-sm mt-2 mt-md-0" onclick="refreshSuppliers()">
                    <i class="bi bi-arrow-clockwise me-1"></i>重新掃描
                </button>
            </div>`;

        if (!suppliers || suppliers.length === 0) {
            html += `
                <div class="card">
                    <div class="card-body">
                        <div class="empty-state">
                            <i class="bi bi-building"></i>
                            <p>尚無供應商資料</p>
                            <button class="btn btn-primary mt-2" onclick="refreshSuppliers()">
                                <i class="bi bi-arrow-clockwise me-1"></i>掃描 CSV
                            </button>
                        </div>
                    </div>
                </div>`;
        } else {
            html += `
                <div class="card">
                    <div class="card-body p-0">
                        <div class="table-container">
                            <table class="table table-hover mb-0">
                                <thead class="table-light">
                                    <tr>
                                        <th>名稱</th>
                                        <th class="text-center">交易數</th>
                                        <th class="text-center">跨專案數</th>
                                        <th>首次出現</th>
                                        <th>最近出現</th>
                                        <th>聯絡人</th>
                                    </tr>
                                </thead>
                                <tbody>`;

            for (const s of suppliers) {
                html += `
                    <tr class="fade-in" style="cursor:pointer" onclick="navigate('#/supplier/${encodeURIComponent(s.name)}')">
                        <td><strong>${s.name}</strong></td>
                        <td class="text-center">${s.transactions}</td>
                        <td class="text-center">${s.projects.length}</td>
                        <td>${s.first_seen || '-'}</td>
                        <td>${s.last_seen || '-'}</td>
                        <td>${s.contact || '-'}</td>
                    </tr>`;
            }

            html += `
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>`;
        }

        app.innerHTML = html;

    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">供應商/客戶</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderSupplierList()">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

async function refreshSuppliers() {
    const btn = event.target;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>掃描中...';
    try {
        await apiGet('/suppliers?rescan=1');
        renderSupplierList();
    } catch (err) {
        alert('掃描失敗：' + err.message);
        renderSupplierList();
    }
}

// ---- Supplier Detail ----

async function renderSupplierDetail(name) {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const data = await apiGet(`/suppliers/${encodeURIComponent(name)}`);

        let html = `
            <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
                <div>
                    <a href="#/suppliers" class="btn btn-outline-secondary btn-sm me-2">
                        <i class="bi bi-arrow-left"></i>
                    </a>
                    <h4 class="d-inline">${data.name}</h4>
                </div>
                <button class="btn btn-outline-primary btn-sm mt-2 mt-md-0" onclick="editSupplierInfo('${encodeURIComponent(data.name)}')">
                    <i class="bi bi-pencil me-1"></i>編輯資訊
                </button>
            </div>

            <div class="row g-3 mb-4">
                <div class="col-md-3">
                    <div class="stat-card stat-income">
                        <div class="stat-label">聯絡人</div>
                        <div class="fs-5 fw-bold">${data.contact || '-'}</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="stat-card stat-expense">
                        <div class="stat-label">電話</div>
                        <div class="fs-5 fw-bold">${data.phone || '-'}</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="stat-card stat-profit">
                        <div class="stat-label">Email</div>
                        <div class="fs-5 fw-bold" style="font-size:0.9rem !important">${data.email || '-'}</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="stat-card" style="background:#e2e3e5;">
                        <div class="stat-label">跨專案</div>
                        <div class="fs-5 fw-bold">${data.projects.length} 個</div>
                    </div>
                </div>
            </div>

            ${data.notes ? `<div class="alert alert-info mb-3">備註：${data.notes}</div>` : ''}

            <h5 class="mb-3">所有交易記錄（${data.transactions.length} 筆）</h5>`;

        if (data.transactions.length === 0) {
            html += `
                <div class="card">
                    <div class="card-body">
                        <div class="empty-state">
                            <i class="bi bi-receipt"></i>
                            <p>尚無交易記錄</p>
                        </div>
                    </div>
                </div>`;
        } else {
            html += `
                <div class="card">
                    <div class="card-body p-0">
                        <div class="table-container">
                            <table class="table table-hover mb-0">
                                <thead class="table-light">
                                    <tr>
                                        <th>日期</th>
                                        <th>專案</th>
                                        <th>類型</th>
                                        <th>分類</th>
                                        <th>描述</th>
                                        <th class="text-end">金額</th>
                                        <th>貨幣</th>
                                        <th>狀態</th>
                                    </tr>
                                </thead>
                                <tbody>`;

            for (const tx of data.transactions) {
                const arrow = tx.類型 === 'income' ? 'text-success' : 'text-danger';
                const prefix = tx.類型 === 'income' ? '+' : '-';
                html += `
                    <tr class="fade-in">
                        <td>${fmtDate(tx.日期)}</td>
                        <td><a href="#/project/${tx._project}" class="text-decoration-none">${tx._project}</a></td>
                        <td>${typeBadge(tx.類型)}</td>
                        <td>${tx.分類 || '-'}</td>
                        <td>${tx['項目描述'] || '-'}</td>
                        <td class="text-end fw-bold ${arrow}">${prefix}$${fmtNum(tx.金額)}</td>
                        <td>${tx.貨幣 || 'HKD'}</td>
                        <td>${tx['付款狀態'] ? statusBadge(tx['付款狀態']) : '-'}</td>
                    </tr>`;
            }

            html += `
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>`;
        }

        app.innerHTML = html;

    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/suppliers" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">供應商詳情</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderSupplierDetail('${encodeURIComponent(name)}')">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

function editSupplierInfo(encodedName) {
    const name = decodeURIComponent(encodedName);
    apiGet(`/suppliers/${encodedName}`).then(data => {
        $id('editSupplierName').value = name;
        $id('editSupplierContact').value = data.contact || '';
        $id('editSupplierPhone').value = data.phone || '';
        $id('editSupplierEmail').value = data.email || '';
        $id('editSupplierNotes').value = data.notes || '';
        new bootstrap.Modal($id('supplierModal')).show();
    }).catch(err => alert('載入失敗：' + err.message));
}

async function saveSupplierInfo() {
    const name = $id('editSupplierName').value;
    const data = {
        contact: $id('editSupplierContact').value,
        phone: $id('editSupplierPhone').value,
        email: $id('editSupplierEmail').value,
        notes: $id('editSupplierNotes').value,
    };
    try {
        await apiPatch(`/suppliers/${encodeURIComponent(name)}`, data);
        bootstrap.Modal.getInstance($id('supplierModal')).hide();
        renderSupplierDetail(name);
    } catch (err) {
        alert('儲存失敗：' + err.message);
    }
}

// ---- Backups Page ----

async function renderBackups() {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const backups = await apiGet('/backups');

        let html = `
            <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
                <div>
                    <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                        <i class="bi bi-arrow-left"></i>
                    </a>
                    <h4 class="d-inline"><i class="bi bi-cloud-arrow-down me-2 text-primary"></i>資料備份</h4>
                </div>
                <button class="btn btn-primary btn-sm mt-2 mt-md-0" onclick="triggerBackup()">
                    <i class="bi bi-cloud-arrow-up me-1"></i>立即備份
                </button>
            </div>`;

        if (!backups || backups.length === 0) {
            html += `
                <div class="card">
                    <div class="card-body">
                        <div class="empty-state">
                            <i class="bi bi-cloud-arrow-down"></i>
                            <p>尚無備份記錄</p>
                            <button class="btn btn-primary mt-2" onclick="triggerBackup()">
                                <i class="bi bi-cloud-arrow-up me-1"></i>建立首次備份
                            </button>
                        </div>
                    </div>
                </div>`;
        } else {
            html += `<div class="card"><div class="card-body p-0"><div class="table-container">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr><th>備份日期</th><th>檔案數</th></tr>
                    </thead>
                    <tbody>`;
            for (const b of backups) {
                html += `<tr><td><strong>${b.date}</strong></td><td>${b.files} 個檔案</td></tr>`;
            }
            html += `</tbody></table></div></div></div>`;
        }

        html += `<p class="text-muted mt-3 small"><i class="bi bi-info-circle me-1"></i>每日凌晨 3:00 自動備份，保留最近 30 天</p>`;
        app.innerHTML = html;

    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">資料備份</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderBackups()">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

async function triggerBackup() {
    const btn = event.target;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>備份中...';
    try {
        const result = await apiPost('/backup', {});
        alert('備份成功：' + result.backup_date);
        renderBackups();
    } catch (err) {
        alert('備份失敗：' + err.message);
        renderBackups();
    }
}

// ---- Modal Operations ----

let txModal = null;
let deleteModal = null;

document.addEventListener('DOMContentLoaded', function () {
    txModal = new bootstrap.Modal($id('txModal'));
    deleteModal = new bootstrap.Modal($id('deleteModal'));

    $id('txSaveBtn').addEventListener('click', saveTransaction);
    $id('deleteConfirmBtn').addEventListener('click', executeDelete);
    $id('supplierSaveBtn').addEventListener('click', saveSupplierInfo);
});

function openAddModal(code) {
    $id('txModalTitle').textContent = '新增交易';
    $id('txForm').reset();
    $id('editIndex').value = '';
    $id('projectCode').value = code;
    $id('txDate').value = new Date().toISOString().split('T')[0];
    $id('txFileName').value = '';
    $id('fileInfo').innerHTML = '';
    $id('txFile').value = '';
    $id('ocrStatus').innerHTML = '';
    txModal.show();
}

function openEditModal(code, index) {
    // We need to find the transaction data - fetch project detail
    apiGet(`/projects/${code}`).then(project => {
        const tx = project.transactions[index];
        if (!tx) return;

        $id('txModalTitle').textContent = '編輯交易';
        $id('editIndex').value = index;
        $id('projectCode').value = code;
        $id('txDate').value = tx.日期 || '';
        $id('txType').value = tx.類型 || 'expense';
        $id('txCategory').value = tx.分類 || 'invoice';
        $id('txVendor').value = tx['供應商/客戶'] || '';
        $id('txDescription').value = tx['項目描述'] || '';
        $id('txAmount').value = tx.金額 || '';
        $id('txCurrency').value = tx.貨幣 || 'HKD';
        $id('txStatus').value = tx['付款狀態'] || 'pending';
        $id('txNotes').value = tx.備註 || '';
        $id('txFileName').value = tx.檔案 || '';
        $id('txFile').value = '';
        $id('ocrStatus').innerHTML = '';
        if (tx.檔案) {
            $id('fileInfo').innerHTML = `<a href="/api/projects/${code}/files/${tx.檔案}" target="_blank">${tx.檔案}</a>`;
        } else {
            $id('fileInfo').innerHTML = '';
        }

        txModal.show();
    }).catch(err => alert('載入交易資料失敗：' + err.message));
}

function getFormData() {
    return {
        '日期': $id('txDate').value,
        '類型': $id('txType').value,
        '分類': $id('txCategory').value,
        '供應商/客戶': $id('txVendor').value,
        '項目描述': $id('txDescription').value,
        '金額': $id('txAmount').value,
        '貨幣': $id('txCurrency').value,
        '付款狀態': $id('txStatus').value,
        '備註': $id('txNotes').value,
        '檔案': $id('txFileName').value,
    };
}

async function apiUploadFile(code, file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(API_BASE + `/projects/${code}/upload`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
    });
    if (!res.ok) throw new Error(`Upload HTTP ${res.status}`);
    return res.json();
}

async function saveTransaction() {
    const code = $id('projectCode').value;
    const editIndex = $id('editIndex').value;
    const data = getFormData();

    // Validate
    if (!data['日期'] || !data['金額']) {
        alert('請填寫日期和金額');
        return;
    }

    try {
        // Upload file first if selected
        const fileInput = $id('txFile');
        if (fileInput.files && fileInput.files.length > 0) {
            const result = await apiUploadFile(code, fileInput.files[0]);
            data['檔案'] = result.filename;
            $id('txFileName').value = result.filename;
        }

        if (editIndex) {
            await apiPut(`/projects/${code}/transactions/${editIndex}`, data);
        } else {
            await apiPost(`/projects/${code}/transactions`, data);
        }
        txModal.hide();
        renderProjectDetail(code);
    } catch (err) {
        alert('儲存失敗：' + err.message);
    }
}

function confirmDelete(code, index) {
    deleteTarget = { code, index };
    deleteModal.show();
}

async function executeDelete() {
    if (!deleteTarget) return;
    const { code, index } = deleteTarget;
    try {
        await apiDelete(`/projects/${code}/transactions/${index}`);
        deleteModal.hide();
        deleteTarget = null;
        renderProjectDetail(code);
    } catch (err) {
        alert('刪除失敗：' + err.message);
    }
}

// ---- OCR ----

async function ocrInvoice() {
    const fileInput = $id('txFile');
    const ocrStatus = $id('ocrStatus');

    if (!fileInput.files || fileInput.files.length === 0) {
        alert('請先選擇發票圖片檔案');
        return;
    }

    const file = fileInput.files[0];
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)) {
        alert('OCR 僅支援圖片格式（JPG、PNG、GIF、WebP）');
        return;
    }

    ocrStatus.innerHTML = '<span class="text-primary"><span class="spinner-border spinner-border-sm me-1"></span>OCR 辨識中...</span>';

    try {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(API_BASE + '/ocr', {
            method: 'POST',
            credentials: 'include',
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'OCR 失敗');
        }
        const data = await res.json();

        // Auto-fill form fields
        if (data.date) $id('txDate').value = data.date;
        if (data.amount) $id('txAmount').value = data.amount;
        if (data.currency) $id('txCurrency').value = data.currency;
        if (data.vendor) $id('txVendor').value = data.vendor;
        if (data.description) $id('txDescription').value = data.description;

        ocrStatus.innerHTML = '<span class="text-success"><i class="bi bi-check-circle me-1"></i>OCR 完成</span>';
    } catch (err) {
        ocrStatus.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-circle me-1"></i>${err.message}</span>`;
    }
}
