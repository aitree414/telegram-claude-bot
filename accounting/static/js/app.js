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

function docStatusBadge(status) {
    const labels = { draft: '草稿', sent: '已發出', accepted: '已接受', rejected: '已拒絕', expired: '已過期', paid: '已收款', overdue: '逾期', cancelled: '已取消' };
    const colors = { draft: 'secondary', sent: 'primary', accepted: 'success', rejected: 'danger', expired: 'warning', paid: 'success', overdue: 'danger', cancelled: 'secondary' };
    return `<span class="badge bg-${colors[status] || 'secondary'}">${labels[status] || status}</span>`;
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
    } else if (route === 'quotations') {
        renderQuotationList();
    } else if (route.match(/^quotations\/([^/]+)\/(.+)/)) {
        const m = route.match(/^quotations\/([^/]+)\/(.+)/);
        renderQuotationDetail(m[1], m[2]);
    } else if (route.startsWith('quotations/')) {
        const code = route.replace('quotations/', '');
        renderProjectQuotations(code);
    } else if (route === 'invoices') {
        renderInvoiceList();
    } else if (route.match(/^invoices\/([^/]+)\/(.+)/)) {
        const m = route.match(/^invoices\/([^/]+)\/(.+)/);
        renderInvoiceDetail(m[1], m[2]);
    } else if (route.startsWith('invoices/')) {
        const code = route.replace('invoices/', '');
        renderProjectInvoices(code);
    } else if (route === 'claim') {
        renderClaimForm();
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
                <div class="mt-2 mt-md-0">
                    <button class="btn btn-outline-primary btn-sm me-1" onclick="openAddModal('${project.code}')">
                        <i class="bi bi-plus-lg me-1"></i>新增交易
                    </button>
                    <button class="btn btn-outline-success btn-sm me-1" onclick="openQuoteModal('${project.code}')">
                        <i class="bi bi-file-text me-1"></i>報價單
                    </button>
                    <a href="#/quotations/${project.code}" class="btn btn-outline-info btn-sm">
                        <i class="bi bi-list me-1"></i>查看報價
                    </a>
                </div>
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

// ════════════════════════════════════════════════════════════════════
//  QUOTATIONS & INVOICES
// ════════════════════════════════════════════════════════════════════

// ---- Helpers ----

function renderDocCard(doc, type) {
    const statusIcon = { draft: '📄', sent: '📨', accepted: '✅', rejected: '❌', expired: '⏰', paid: '💰', overdue: '⚠️', cancelled: '🚫' };
    const prefix = type === 'quotations' ? 'Q' : 'INV';
    const items = doc.items || [];
    const itemSummary = items.map(i => `${i.desc} x${i.qty}`).join(', ');
    const clientName = doc.client?.name || '—';
    return `
        <div class="col-12 col-md-6 col-lg-4">
            <div class="card project-card h-100" onclick="navigate('#/${type}/${doc.project_code}/${doc.id}')">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <h5>${doc.id}</h5>
                            <small class="opacity-75">${clientName}</small>
                        </div>
                        ${docStatusBadge(doc.status)}
                    </div>
                </div>
                <div class="card-body">
                    <div class="d-flex justify-content-between mb-2">
                        <span>總額</span>
                        <span class="fw-bold">${doc.currency || 'HKD'} ${fmtNum(doc.total)}</span>
                    </div>
                    <div class="d-flex justify-content-between mb-2">
                        <span>日期</span>
                        <span>${fmtDate(doc.date)}</span>
                    </div>
                    <div class="text-muted small">${doc.project_code}</div>
                    ${itemSummary ? `<div class="text-muted small mt-1">${itemSummary}</div>` : ''}
                </div>
            </div>
        </div>`;
}

function renderDocDetail(doc, type) {
    const statusIcon = { draft: '📄', sent: '📨', accepted: '✅', rejected: '❌', expired: '⏰', paid: '💰', overdue: '⚠️', cancelled: '🚫' };
    const items = doc.items || [];
    const client = doc.client || {};

    let html = `
        <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
            <div>
                <a href="#/${type}" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">${doc.id}</h4>
                ${docStatusBadge(doc.status)}
                <span class="badge bg-secondary ms-2">${doc.project_code}</span>
            </div>
            <div class="mt-2 mt-md-0">`;

    // Action buttons
    if (type === 'quotations') {
        if (doc.status === 'draft') {
            html += `
                <button class="btn btn-primary btn-sm me-1" onclick="updateDocStatus('${doc.project_code}','${doc.id}','quotations','sent')">
                    <i class="bi bi-send me-1"></i>標記已發出
                </button>
                <button class="btn btn-success btn-sm me-1" onclick="convertToInvoice('${doc.project_code}','${doc.id}')">
                    <i class="bi bi-receipt me-1"></i>轉發票
                </button>`;
        } else if (doc.status === 'sent') {
            html += `
                <button class="btn btn-success btn-sm me-1" onclick="updateDocStatus('${doc.project_code}','${doc.id}','quotations','accepted')">
                    <i class="bi bi-check-lg me-1"></i>接受
                </button>
                <button class="btn btn-danger btn-sm me-1" onclick="updateDocStatus('${doc.project_code}','${doc.id}','quotations','rejected')">
                    <i class="bi bi-x-lg me-1"></i>拒絕
                </button>
                <button class="btn btn-success btn-sm me-1" onclick="convertToInvoice('${doc.project_code}','${doc.id}')">
                    <i class="bi bi-receipt me-1"></i>轉發票
                </button>`;
        }
    } else {
        // Invoice actions
        if (doc.status === 'draft' || doc.status === 'sent') {
            html += `
                <button class="btn btn-success btn-sm me-1" onclick="markPaid('${doc.project_code}','${doc.id}')">
                    <i class="bi bi-cash me-1"></i>標記已收款
                </button>`;
        }
    }

    if (type === 'quotations') {
        html += `
                <button class="btn btn-danger btn-sm" onclick="deleteDoc('${doc.project_code}','${doc.id}','quotations')">
                    <i class="bi bi-trash me-1"></i>刪除
                </button>`;
    } else {
        html += `
                <button class="btn btn-danger btn-sm" onclick="deleteDoc('${doc.project_code}','${doc.id}','invoices')">
                    <i class="bi bi-trash me-1"></i>刪除
                </button>`;
    }

    html += `
            </div>
        </div>

        <div class="row g-3 mb-4">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h6 class="text-muted mb-2"><i class="bi bi-person me-1"></i>客戶資訊</h6>
                        <table class="table table-sm mb-0">
                            <tr><td class="text-muted">名稱</td><td class="fw-bold">${client.name || '-'}</td></tr>
                            <tr><td class="text-muted">聯絡人</td><td>${client.contact || '-'}</td></tr>
                            <tr><td class="text-muted">Email</td><td>${client.email || '-'}</td></tr>
                            <tr><td class="text-muted">電話</td><td>${client.phone || '-'}</td></tr>
                        </table>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h6 class="text-muted mb-2"><i class="bi bi-info-circle me-1"></i>文件資訊</h6>
                        <table class="table table-sm mb-0">
                            <tr><td class="text-muted">日期</td><td class="fw-bold">${fmtDate(doc.date)}</td></tr>
                            ${doc.valid_until ? `<tr><td class="text-muted">有效至</td><td>${fmtDate(doc.valid_until)}</td></tr>` : ''}
                            ${doc.due_date ? `<tr><td class="text-muted">到期日</td><td>${fmtDate(doc.due_date)}</td></tr>` : ''}
                            ${doc.paid_date ? `<tr><td class="text-muted">收款日期</td><td class="fw-bold text-success">${fmtDate(doc.paid_date)}</td></tr>` : ''}
                            ${doc.quotation_id ? `<tr><td class="text-muted">來源報價</td><td><a href="#/quotations/${doc.project_code}/${doc.quotation_id}">${doc.quotation_id}</a></td></tr>` : ''}
                            <tr><td class="text-muted">狀態</td><td>${docStatusBadge(doc.status)}</td></tr>
                            <tr><td class="text-muted">建立時間</td><td>${doc.created_at ? fmtDate(doc.created_at) : '-'}</td></tr>
                        </table>
                    </div>
                </div>
            </div>
        </div>`;

    // Items table
    html += `
        <div class="card mb-4">
            <div class="card-body p-0">
                <div class="table-container">
                    <table class="table table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>#</th>
                                <th>描述</th>
                                <th class="text-center">數量</th>
                                <th class="text-center">單位</th>
                                <th class="text-end">單價</th>
                                <th class="text-end">金額</th>
                            </tr>
                        </thead>
                        <tbody>`;

    for (let i = 0; i < items.length; i++) {
        const item = items[i];
        html += `
                            <tr>
                                <td>${i + 1}</td>
                                <td>${item.desc || '-'}</td>
                                <td class="text-center">${item.qty}</td>
                                <td class="text-center">${item.unit || '項'}</td>
                                <td class="text-end">${fmtNum(item.price)}</td>
                                <td class="text-end fw-bold">${fmtNum(item.amount)}</td>
                            </tr>`;
    }

    const subtotal = doc.subtotal || items.reduce((s, i) => s + (i.amount || 0), 0);
    const taxRate = doc.tax_rate || 0;
    const tax = doc.tax !== undefined ? doc.tax : (taxRate > 0 ? subtotal * taxRate / 100 : 0);

    html += `
                        </tbody>
                    </table>
                </div>
            </div>
            <div class="card-body border-top">
                <div class="row">
                    <div class="col-md-6 offset-md-6">
                        <table class="table table-sm mb-0">
                            <tr>
                                <td>小計</td>
                                <td class="text-end">${fmtNum(subtotal)}</td>
                            </tr>
                            <tr>
                                <td>稅率 (${taxRate}%)</td>
                                <td class="text-end">${fmtNum(tax)}</td>
                            </tr>
                            <tr class="fw-bold fs-5">
                                <td>總計</td>
                                <td class="text-end">${doc.currency || 'HKD'} ${fmtNum(doc.total)}</td>
                            </tr>
                        </table>
                    </div>
                </div>
            </div>
        </div>`;

    if (doc.notes) {
        html += `<div class="alert alert-info">${doc.notes}</div>`;
    }

    return html;
}

// ---- Quotation List (All Projects) ----

async function renderQuotationList() {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        // Fetch projects to get all codes, then fetch quotations for each
        const projects = await apiGet('/projects');
        let allQuotes = [];

        for (const p of projects) {
            try {
                const quotes = await apiGet(`/projects/${p.code}/quotations`);
                allQuotes = allQuotes.concat(quotes.map(q => ({ ...q, project_code: p.code })));
            } catch { /* no quotations for this project */ }
        }

        allQuotes.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));

        let html = `
            <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
                <div>
                    <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                        <i class="bi bi-arrow-left"></i>
                    </a>
                    <h4 class="d-inline"><i class="bi bi-file-text me-2 text-primary"></i>所有報價單</h4>
                </div>
            </div>`;

        if (allQuotes.length === 0) {
            html += `
                <div class="card">
                    <div class="card-body">
                        <div class="empty-state">
                            <i class="bi bi-file-text"></i>
                            <p>尚無報價單</p>
                        </div>
                    </div>
                </div>`;
        } else {
            // Group by project
            const byProject = {};
            for (const q of allQuotes) {
                const pc = q.project_code || 'unknown';
                if (!byProject[pc]) byProject[pc] = [];
                byProject[pc].push(q);
            }

            let totalValue = 0;
            let draftCount = 0;
            for (const q of allQuotes) {
                if (q.status === 'draft') draftCount++;
                totalValue += q.total || 0;
            }

            html += `
                <div class="row g-3 mb-4">
                    <div class="col-4">
                        <div class="stat-card stat-profit">
                            <div class="stat-label">總報價金額</div>
                            <div class="stat-value">${fmtNum(totalValue)}</div>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="stat-card stat-pending-income">
                            <div class="stat-label">總件數</div>
                            <div class="stat-value">${allQuotes.length}</div>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="stat-card" style="background:#e2e3e5;">
                            <div class="stat-label">草稿</div>
                            <div class="stat-value">${draftCount}</div>
                        </div>
                    </div>
                </div>`;

            for (const [pc, quotes] of Object.entries(byProject)) {
                html += `<h5 class="mb-3 mt-4">
                    <a href="#/quotations/${pc}" class="text-decoration-none">${pc}</a>
                    <span class="badge bg-secondary ms-2">${quotes.length}</span>
                </h5>
                <div class="row g-4">`;
                for (const q of quotes) {
                    html += renderDocCard(q, 'quotations');
                }
                html += '</div>';
            }
        }

        app.innerHTML = html;

    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">報價單</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderQuotationList()">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

// ---- Project Quotations ----

async function renderProjectQuotations(code) {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const quotes = await apiGet(`/projects/${code}/quotations`);

        let html = `
            <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
                <div>
                    <a href="#/quotations" class="btn btn-outline-secondary btn-sm me-2">
                        <i class="bi bi-arrow-left"></i>
                    </a>
                    <h4 class="d-inline">${code} 報價單</h4>
                </div>
                <button class="btn btn-success btn-sm mt-2 mt-md-0" onclick="openQuoteModal('${code}')">
                    <i class="bi bi-plus-lg me-1"></i>新增報價單
                </button>
            </div>`;

        if (!quotes || quotes.length === 0) {
            html += `
                <div class="card">
                    <div class="card-body">
                        <div class="empty-state">
                            <i class="bi bi-file-text"></i>
                            <p>尚無報價單</p>
                            <button class="btn btn-primary mt-2" onclick="openQuoteModal('${code}')">
                                <i class="bi bi-plus-lg me-1"></i>建立第一張報價單
                            </button>
                        </div>
                    </div>
                </div>`;
        } else {
            html += '<div class="row g-4">';
            for (const q of quotes) {
                html += renderDocCard({ ...q, project_code: code }, 'quotations');
            }
            html += '</div>';
        }

        app.innerHTML = html;

    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/quotations" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">報價單</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderProjectQuotations('${code}')">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

// ---- Quotation Detail ----

async function renderQuotationDetail(code, qid) {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const doc = await apiGet(`/projects/${code}/quotations/${qid}`);
        app.innerHTML = renderDocDetail({ ...doc, project_code: code }, 'quotations');
    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/quotations" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">報價單詳情</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderQuotationDetail('${code}','${qid}')">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

// ---- Invoice List (All Projects) ----

async function renderInvoiceList() {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const allInvoices = await apiGet('/invoices');
        allInvoices.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));

        let html = `
            <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
                <div>
                    <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                        <i class="bi bi-arrow-left"></i>
                    </a>
                    <h4 class="d-inline"><i class="bi bi-receipt me-2 text-primary"></i>所有發票</h4>
                </div>
            </div>`;

        if (allInvoices.length === 0) {
            html += `
                <div class="card">
                    <div class="card-body">
                        <div class="empty-state">
                            <i class="bi bi-receipt"></i>
                            <p>尚無發票</p>
                            <p class="text-muted small">可從報價單轉換為發票</p>
                        </div>
                    </div>
                </div>`;
        } else {
            const byProject = {};
            let totalOutstanding = 0;
            let totalPaid = 0;
            for (const inv of allInvoices) {
                const pc = inv.project_code || 'unknown';
                if (!byProject[pc]) byProject[pc] = [];
                byProject[pc].push(inv);
                if (inv.status === 'paid') totalPaid += inv.total || 0;
                else if (inv.status !== 'cancelled') totalOutstanding += inv.total || 0;
            }

            html += `
                <div class="row g-3 mb-4">
                    <div class="col-4">
                        <div class="stat-card stat-income">
                            <div class="stat-label">已收款</div>
                            <div class="stat-value text-success">${fmtNum(totalPaid)}</div>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="stat-card stat-pending-income">
                            <div class="stat-label">待收款</div>
                            <div class="stat-value">${fmtNum(totalOutstanding)}</div>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="stat-card" style="background:#e2e3e5;">
                            <div class="stat-label">總件數</div>
                            <div class="stat-value">${allInvoices.length}</div>
                        </div>
                    </div>
                </div>`;

            for (const [pc, invoices] of Object.entries(byProject)) {
                html += `<h5 class="mb-3 mt-4">
                    <a href="#/invoices/${pc}" class="text-decoration-none">${pc}</a>
                    <span class="badge bg-secondary ms-2">${invoices.length}</span>
                </h5>
                <div class="row g-4">`;
                for (const inv of invoices) {
                    html += renderDocCard(inv, 'invoices');
                }
                html += '</div>';
            }
        }

        app.innerHTML = html;

    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">發票</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderInvoiceList()">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

// ---- Project Invoices ----

async function renderProjectInvoices(code) {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const invoices = await apiGet(`/projects/${code}/invoices`);

        let html = `
            <div class="page-header d-flex justify-content-between align-items-center flex-wrap">
                <div>
                    <a href="#/invoices" class="btn btn-outline-secondary btn-sm me-2">
                        <i class="bi bi-arrow-left"></i>
                    </a>
                    <h4 class="d-inline">${code} 發票</h4>
                </div>
            </div>`;

        if (!invoices || invoices.length === 0) {
            html += `
                <div class="card">
                    <div class="card-body">
                        <div class="empty-state">
                            <i class="bi bi-receipt"></i>
                            <p>尚無發票</p>
                        </div>
                    </div>
                </div>`;
        } else {
            html += '<div class="row g-4">';
            for (const inv of invoices) {
                html += renderDocCard(inv, 'invoices');
            }
            html += '</div>';
        }

        app.innerHTML = html;

    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/invoices" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">發票</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderProjectInvoices('${code}')">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

// ---- Invoice Detail ----

async function renderInvoiceDetail(code, iid) {
    const app = $id('app');
    app.innerHTML = '<div class="loading-spinner"><div class="spinner-border text-primary" role="status"></div></div>';

    try {
        const doc = await apiGet(`/projects/${code}/invoices/${iid}`);
        app.innerHTML = renderDocDetail({ ...doc, project_code: code }, 'invoices');
    } catch (err) {
        app.innerHTML = `
            <div class="page-header">
                <a href="#/invoices" class="btn btn-outline-secondary btn-sm me-2">
                    <i class="bi bi-arrow-left"></i>
                </a>
                <h4 class="d-inline">發票詳情</h4>
            </div>
            <div class="empty-state">
                <i class="bi bi-exclamation-triangle-fill text-danger"></i>
                <p>載入失敗：${err.message}</p>
                <button class="btn btn-primary mt-2" onclick="renderInvoiceDetail('${code}','${iid}')">
                    <i class="bi bi-arrow-clockwise me-1"></i>重試
                </button>
            </div>`;
    }
}

// ---- Actions ----

// Quotation Modal
let quoteModalInstance = null;

function openQuoteModal(code) {
    $id('quoteModalTitle').textContent = `新增報價單 - ${code}`;
    $id('quoteProjectCode').value = code;
    $id('quoteClientName').value = '';
    $id('quoteContact').value = '';
    $id('quoteEmail').value = '';
    $id('quotePhone').value = '';
    $id('quoteCurrency').value = 'HKD';
    $id('quoteTaxRate').value = '0';
    $id('quoteValidUntil').value = '';

    // Reset items to one empty row
    $id('quoteItems').innerHTML = `
        <div class="row g-2 quote-item mb-2">
            <div class="col-4">
                <input type="text" class="form-control form-control-sm" placeholder="描述" name="itemDesc">
            </div>
            <div class="col-2">
                <input type="number" class="form-control form-control-sm" placeholder="數量" name="itemQty" value="1" min="1">
            </div>
            <div class="col-2">
                <input type="text" class="form-control form-control-sm" placeholder="單位" name="itemUnit" value="項">
            </div>
            <div class="col-3">
                <input type="number" step="0.01" class="form-control form-control-sm" placeholder="單價" name="itemPrice">
            </div>
            <div class="col-1">
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="this.closest('.quote-item').remove()"><i class="bi bi-x"></i></button>
            </div>
        </div>`;

    if (!quoteModalInstance) quoteModalInstance = new bootstrap.Modal($id('quoteModal'));
    quoteModalInstance.show();
}

function addQuoteItem() {
    const div = document.createElement('div');
    div.className = 'row g-2 quote-item mb-2';
    div.innerHTML = `
        <div class="col-4">
            <input type="text" class="form-control form-control-sm" placeholder="描述" name="itemDesc">
        </div>
        <div class="col-2">
            <input type="number" class="form-control form-control-sm" placeholder="數量" name="itemQty" value="1" min="1">
        </div>
        <div class="col-2">
            <input type="text" class="form-control form-control-sm" placeholder="單位" name="itemUnit" value="項">
        </div>
        <div class="col-3">
            <input type="number" step="0.01" class="form-control form-control-sm" placeholder="單價" name="itemPrice">
        </div>
        <div class="col-1">
            <button type="button" class="btn btn-sm btn-outline-danger" onclick="this.closest('.quote-item').remove()"><i class="bi bi-x"></i></button>
        </div>`;
    $id('quoteItems').appendChild(div);
}

async function saveQuotation() {
    const code = $id('quoteProjectCode').value;

    const client = {
        name: $id('quoteClientName').value,
        contact: $id('quoteContact').value,
        email: $id('quoteEmail').value,
        phone: $id('quotePhone').value,
    };

    const itemEls = $id('quoteItems').querySelectorAll('.quote-item');
    const items = [];
    for (const el of itemEls) {
        const desc = el.querySelector('[name="itemDesc"]').value;
        const qty = parseInt(el.querySelector('[name="itemQty"]').value) || 0;
        const unit = el.querySelector('[name="itemUnit"]').value || '項';
        const price = parseFloat(el.querySelector('[name="itemPrice"]').value) || 0;
        if (desc && qty > 0 && price > 0) {
            items.push({ desc, qty, unit, price, amount: qty * price });
        }
    }

    if (items.length === 0) {
        alert('請至少填寫一個有效的項目');
        return;
    }

    const payload = {
        client,
        items,
        currency: $id('quoteCurrency').value,
        tax_rate: parseFloat($id('quoteTaxRate').value) || 0,
        valid_until: $id('quoteValidUntil').value,
    };

    try {
        await apiPost(`/projects/${code}/quotations`, payload);
        quoteModalInstance.hide();
        // Refresh the current view
        navigate(window.location.hash);
    } catch (err) {
        alert('建立失敗：' + err.message);
    }
}

// Update document status (quotation or invoice)
async function updateDocStatus(code, id, type, status) {
    const payload = { status };
    if (status === 'paid') {
        payload.paid_date = new Date().toISOString().split('T')[0];
    }
    try {
        await apiPut(`/projects/${code}/${type}/${id}`, payload);
        navigate(window.location.hash);
    } catch (err) {
        alert('更新失敗：' + err.message);
    }
}

// Convert quotation to invoice
async function convertToInvoice(code, qid) {
    if (!confirm(`確定將 ${qid} 轉換為發票？`)) return;
    try {
        await apiPost(`/projects/${code}/quotations/${qid}/convert`, {});
        alert(`✅ 已轉換為發票`);
        navigate(window.location.hash);
    } catch (err) {
        alert('轉換失敗：' + err.message);
    }
}

// Mark invoice as paid
async function markPaid(code, iid) {
    const date = prompt('請輸入收款日期 (YYYY-MM-DD)：', new Date().toISOString().split('T')[0]);
    if (!date) return;
    try {
        await apiPut(`/projects/${code}/invoices/${iid}`, { status: 'paid', paid_date: date });
        navigate(window.location.hash);
    } catch (err) {
        alert('操作失敗：' + err.message);
    }
}

// Delete document
async function deleteDoc(code, id, type) {
    if (!confirm(`確定刪除 ${id}？此操作無法復原。`)) return;
    try {
        await apiDelete(`/projects/${code}/${type}/${id}`);
        navigate(`#/${type}`);
    } catch (err) {
        alert('刪除失敗：' + err.message);
    }
}

// ---- Transaction Modal Operations ----

// ---- Claim Form ----

function renderClaimForm() {
    const main = $id('mainContent');
    main.innerHTML = `
    <style>
      .claim-form { max-width: 900px; margin: 0 auto; }
      .claim-header { border-bottom: 3px solid #1a3a5c; padding-bottom: 16px; margin-bottom: 24px; }
      .claim-header h2 { font-weight: 700; color: #1a3a5c; letter-spacing: 0.03em; }
      .claim-section { border: 1px solid #dee2e6; border-radius: 12px; padding: 24px; margin-bottom: 24px; background: #fff; }
      .claim-section h5 { font-weight: 600; color: #1a3a5c; border-left: 4px solid #1a3a5c; padding-left: 12px; margin-bottom: 20px; }
      .claim-table { font-size: 0.9rem; }
      .claim-table th { background: #f0f4f8; font-weight: 600; }
      .claim-total { background: #f8fafc; font-weight: 700; font-size: 1.1rem; }
      .claim-total td { border-top: 2px solid #1a3a5c !important; }
      .receipt-preview { max-width: 120px; max-height: 120px; object-fit: cover; border-radius: 8px; border: 1px solid #dee2e6; }
      .print-layout { display: none; }
      @media print {
        .no-print { display: none !important; }
        .print-layout { display: block !important; }
        .claim-section { border: 1px solid #ccc !important; box-shadow: none !important; }
        body { background: white !important; }
      }
    </style>
    <div class="claim-form">
      <div class="d-flex justify-content-between align-items-start claim-header">
        <div>
          <span class="badge bg-secondary mb-2" style="letter-spacing:0.1em;">08/ CLAIM RECORD</span>
          <h2><i class="bi bi-file-earmark-text me-2"></i>Claim Form</h2>
        </div>
        <div class="no-print">
          <button class="btn btn-outline-secondary me-2" onclick="window.print()"><i class="bi bi-printer me-1"></i>列印</button>
          <button class="btn btn-primary" onclick="submitClaim()"><i class="bi bi-send me-1"></i>提交</button>
        </div>
      </div>

      <!-- Project Info -->
      <div class="claim-section">
        <h5>01/ Projects</h5>
        <div class="row g-3">
          <div class="col-md-6">
            <label class="form-label">Project Name</label>
            <select class="form-select" id="claimProject">
              <option value="">Select Project...</option>
            </select>
          </div>
          <div class="col-md-3">
            <label class="form-label">Claim Date</label>
            <input type="date" class="form-control" id="claimDate">
          </div>
          <div class="col-md-3">
            <label class="form-label">Claim Ref #</label>
            <input type="text" class="form-control" id="claimRef" placeholder="e.g. CLM-2026-001">
          </div>
        </div>
        <div class="row g-3 mt-2">
          <div class="col-md-6">
            <label class="form-label">Claimant Name</label>
            <input type="text" class="form-control" id="claimantName" placeholder="e.g. Peony">
          </div>
          <div class="col-md-3">
            <label class="form-label">Currency</label>
            <select class="form-select" id="claimCurrency">
              <option value="HKD" selected>HKD</option>
              <option value="USD">USD</option>
              <option value="CNY">CNY</option>
            </select>
          </div>
          <div class="col-md-3">
            <label class="form-label">Status</label>
            <select class="form-select" id="claimStatus">
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="paid">Paid</option>
            </select>
          </div>
        </div>
      </div>

      <!-- Line Items -->
      <div class="claim-section">
        <h5>02/ Items</h5>
        <div class="table-responsive">
          <table class="table claim-table" id="itemsTable">
            <thead>
              <tr>
                <th style="width:40px">#</th>
                <th>Description</th>
                <th style="width:120px">Category</th>
                <th style="width:80px">Qty</th>
                <th style="width:130px">Unit Price</th>
                <th style="width:130px">Amount</th>
                <th style="width:40px" class="no-print"></th>
              </tr>
            </thead>
            <tbody id="itemsBody">
            </tbody>
            <tfoot>
              <tr class="claim-total">
                <td colspan="5" class="text-end">Total</td>
                <td id="claimTotalAmount">0.00</td>
                <td></td>
              </tr>
            </tfoot>
          </table>
        </div>
        <button class="btn btn-sm btn-outline-primary no-print" onclick="addItem()"><i class="bi bi-plus-lg me-1"></i>Add Item</button>
      </div>

      <!-- Receipt Photos -->
      <div class="claim-section no-print">
        <h5>03/ Supporting Documents</h5>
        <p class="text-muted small">Upload receipt photos or scanned documents</p>
        <input type="file" class="form-control mb-3" id="receiptFiles" accept="image/*,application/pdf" multiple onchange="previewReceipts()">
        <div class="d-flex flex-wrap gap-2" id="receiptPreview"></div>
      </div>

      <!-- Notes -->
      <div class="claim-section no-print">
        <h5>04/ Notes</h5>
        <textarea class="form-control" id="claimNotes" rows="3" placeholder="Any additional notes..."></textarea>
      </div>
    </div>
    `;

    // Load projects into dropdown
    apiGet('/projects').then(projects => {
      const sel = $id('claimProject');
      projects.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.code;
        opt.textContent = p.name;
        sel.appendChild(opt);
      });
    }).catch(() => {});

    // Set default date
    $id('claimDate').valueAsDate = new Date();

    // Add first empty row
    addItem();
}

let itemCounter = 0;
function addItem() {
  itemCounter++;
  const tbody = $id('itemsBody');
  const row = document.createElement('tr');
  row.id = 'itemRow_' + itemCounter;
  row.innerHTML = \`
    <td class="text-muted">\${itemCounter}</td>
    <td><input type="text" class="form-control form-control-sm item-desc" placeholder="Description"></td>
    <td>
      <select class="form-select form-select-sm item-cat">
        <option value="">Select</option>
        <option value="transport">Transport</option>
        <option value="meals">Meals</option>
        <option value="materials">Materials</option>
        <option value="printing">Printing</option>
        <option value="venue">Venue</option>
        <option value="supplies">Supplies</option>
        <option value="other">Other</option>
      </select>
    </td>
    <td><input type="number" class="form-control form-control-sm item-qty" value="1" min="1" onchange="calcRow(this)" oninput="calcRow(this)"></td>
    <td><input type="number" class="form-control form-control-sm item-price" step="0.01" min="0" placeholder="0.00" onchange="calcRow(this)" oninput="calcRow(this)"></td>
    <td><input type="number" class="form-control form-control-sm item-amount" step="0.01" readonly style="background:#f8f9fa;font-weight:600;"></td>
    <td class="no-print"><button class="btn btn-sm btn-outline-danger" onclick="removeItem(this)"><i class="bi bi-x"></i></button></td>
  \`;
  tbody.appendChild(row);
  updateTotal();
}

function removeItem(btn) {
  btn.closest('tr').remove();
  updateTotal();
}

function calcRow(el) {
  const row = el.closest('tr');
  const qty = parseFloat(row.querySelector('.item-qty').value) || 0;
  const price = parseFloat(row.querySelector('.item-price').value) || 0;
  const amt = qty * price;
  row.querySelector('.item-amount').value = amt.toFixed(2);
  updateTotal();
}

function updateTotal() {
  let total = 0;
  document.querySelectorAll('.item-amount').forEach(el => {
    total += parseFloat(el.value) || 0;
  });
  $id('claimTotalAmount').textContent = total.toFixed(2);
}

function previewReceipts() {
  const files = $id('receiptFiles').files;
  const container = $id('receiptPreview');
  container.innerHTML = '';
  for (const f of files) {
    if (f.type.startsWith('image/')) {
      const reader = new FileReader();
      reader.onload = e => {
        const wrap = document.createElement('div');
        wrap.style.position = 'relative';
        wrap.innerHTML = \`<img src="\${e.target.result}" class="receipt-preview"><br><small class="text-muted">\${f.name}</small>\`;
        container.appendChild(wrap);
      };
      reader.readAsDataURL(f);
    } else {
      const wrap = document.createElement('div');
      wrap.innerHTML = \`<div class="p-3 border rounded text-center"><i class="bi bi-file-pdf fs-1 text-danger"></i><br><small>\${f.name}</small></div>\`;
      container.appendChild(wrap);
    }
  }
}

async function submitClaim() {
  const project = $id('claimProject').value;
  const date = $id('claimDate').value;
  const ref = $id('claimRef').value;
  const claimant = $id('claimantName').value;
  const currency = $id('claimCurrency').value;
  const status = $id('claimStatus').value;
  const notes = $id('claimNotes').value;

  if (!project || !claimant) {
    alert('Please select a project and enter claimant name.');
    return;
  }

  // Gather items
  const items = [];
  document.querySelectorAll('#itemsBody tr').forEach(row => {
    const desc = row.querySelector('.item-desc')?.value;
    const cat = row.querySelector('.item-cat')?.value;
    const qty = parseFloat(row.querySelector('.item-qty')?.value) || 0;
    const price = parseFloat(row.querySelector('.item-price')?.value) || 0;
    if (desc && desc.trim()) {
      items.push({ description: desc.trim(), category: cat, qty, unit_price: price, amount: qty * price });
    }
  });

  if (items.length === 0) {
    alert('Please add at least one item.');
    return;
  }

  const total = items.reduce((s, i) => s + i.amount, 0);

  // Build form data
  const formData = new FormData();
  formData.append('project', project);
  formData.append('date', date);
  formData.append('ref', ref);
  formData.append('claimant', claimant);
  formData.append('currency', currency);
  formData.append('status', status);
  formData.append('notes', notes);
  formData.append('items', JSON.stringify(items));
  formData.append('total', total.toFixed(2));

  // Attach receipt files
  const fileInput = $id('receiptFiles');
  for (const f of fileInput.files) {
    formData.append('receipts', f);
  }

  const btn = event.target;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Submitting...';

  try {
    const res = await fetch(API_BASE + '/claim/submit', {
      method: 'POST',
      credentials: 'include',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'HTTP ' + res.status }));
      throw new Error(err.error || 'Submission failed');
    }
    const result = await res.json();
    alert(\`✅ Claim submitted successfully!\nTotal: \${currency} \${total.toFixed(2)}\nTransactions created: \${result.transactions_created}\nPDF: \${result.pdf || 'Generated'}\`);
    navigate('#/project/' + encodeURIComponent(project));
  } catch (err) {
    alert('❌ Submission failed: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-send me-1"></i>Submit';
  }
}
// ---- End Claim Form ----

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

    if (!data['日期'] || !data['金額']) {
        alert('請填寫日期和金額');
        return;
    }

    try {
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
