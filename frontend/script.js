const API_BASE = window.location.origin;

const chatArea = document.getElementById('chatArea');
const messagesEl = document.getElementById('messages');
const queryInput = document.getElementById('queryInput');
const sendBtn = document.getElementById('sendBtn');
const welcomeEl = document.getElementById('welcomeContainer');
const sampleQueriesEl = document.getElementById('sampleQueries');
const uploadCta = document.getElementById('uploadCta');
const uploadCtaBtn = document.getElementById('uploadCtaBtn');
const sidebar = document.getElementById('sidebar');
const menuBtn = document.getElementById('menuBtn');
const sidebarClose = document.getElementById('sidebarClose');
const datasetsListEl = document.getElementById('datasetsList');
const topStatus = document.getElementById('topStatus');
const providerBadge = document.getElementById('providerBadge');
const providerBadgeText = document.getElementById('providerBadgeText');
const changeKeyBtn = document.getElementById('changeKeyBtn');

const uploadZone = document.getElementById('uploadZone');
const csvFileInput = document.getElementById('csvFileInput');
const attachBtn = document.getElementById('attachBtn');
const uploadProgress = document.getElementById('uploadProgress');
const uploadProgressBar = document.getElementById('uploadProgressBar');
const uploadProgressText = document.getElementById('uploadProgressText');

const setupModal = document.getElementById('setupModal');
const providerTabs = document.getElementById('providerTabs');
const providerInfo = document.getElementById('providerInfo');
const apiKeyInput = document.getElementById('apiKeyInput');
const toggleVisBtn = document.getElementById('toggleVisibility');
const modalError = document.getElementById('modalError');
const modalSubmit = document.getElementById('modalSubmit');
const modalSubmitText = document.getElementById('modalSubmitText');
const modalSpinner = document.getElementById('modalSpinner');

let isProcessing = false;
let chartCounter = 0;
let selectedProvider = 'google';
let hasDatasets = false;

const PROVIDER_INFO = {
    google: { label: 'Google Gemini', text: 'Get a free key at <a href="https://aistudio.google.com/apikey" target="_blank">aistudio.google.com/apikey</a>' },
    groq: { label: 'Groq', text: 'Get a free key at <a href="https://console.groq.com/keys" target="_blank">console.groq.com/keys</a>' },
    nvidia: { label: 'NVIDIA', text: 'Get an API key at <a href="https://build.nvidia.com" target="_blank">build.nvidia.com</a>' },
};

document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    await checkSetup();
    await loadDatasets();
});
async function checkSetup() {
    try {
        const res = await fetch(`${API_BASE}/api/setup`);
        const data = await res.json();
        if (data.providers?.any_configured) {
            hideModal();
            const active = ['google', 'groq'].find(p => data.providers[p]);
            if (active) {
                providerBadgeText.textContent = `✓ ${PROVIDER_INFO[active]?.label || active} connected`;
                providerBadge.style.display = 'flex';
            }
        } else {
            showModal();
        }
    } catch { showModal(); }
}

async function loadDatasets() {
    try {
        const res = await fetch(`${API_BASE}/api/datasets`);
        const data = await res.json();
        renderDatasets(data.datasets || []);
    } catch {
        datasetsListEl.innerHTML = `<div class="datasets-empty">Could not load datasets.</div>`;
    }
}

function renderDatasets(datasets) {
    hasDatasets = datasets.length > 0;

    if (hasDatasets) {
        uploadCta?.classList.add('hidden');
        sampleQueriesEl?.classList.remove('hidden');
        queryInput.placeholder = "Ask anything about your data...";
    } else {
        uploadCta?.classList.remove('hidden');
        sampleQueriesEl?.classList.add('hidden');
        queryInput.placeholder = "Upload a file first, then ask questions...";
    }

    if (!datasets.length) {
        datasetsListEl.innerHTML = `
            <div class="datasets-empty">
                No datasets yet.<br>Upload a file above to get started.
            </div>`;
        return;
    }

    datasetsListEl.innerHTML = datasets.map(d => `
        <div class="dataset-card">
            <div class="dataset-card-header" onclick="toggleSchema('${esc(d.table_name)}')">
                <div class="dataset-name"> ${esc(d.table_name)}</div>
                <div class="dataset-chevron" id="chevron-${esc(d.table_name)}">▼</div>
            </div>
            <div class="dataset-meta">
                <span class="dataset-tag">${d.column_count} columns</span>
                <button type="button" class="dataset-delete-mini" onclick="deleteDataset('${esc(d.table_name)}', event)" title="Remove dataset">✕</button>
            </div>
            
            <div id="schema-${esc(d.table_name)}" class="dataset-schema-dropdown hidden">
                <div class="schema-scroll-area">
                    <div class="schema-title">Columns & Types</div>
                    <div class="schema-list">
                        ${Object.entries(d.columns).map(([col, type]) => `
                            <div class="schema-item">
                                <span class="schema-col">${esc(col)}</span>
                                <span class="schema-type">${esc(type.toLowerCase())}</span>
                            </div>
                        `).join('')}
                    </div>
                    ${d.sample_row ? `
                        <div class="schema-title" style="margin-top:12px;">Sample Data</div>
                        <div class="schema-sample">${esc(JSON.stringify(d.sample_row, null, 2))}</div>
                    ` : ''}
                </div>
            </div>
        </div>
    `).join('');
}

function toggleSchema(tableName) {
    const el = document.getElementById(`schema-${tableName}`);
    const chev = document.getElementById(`chevron-${tableName}`);
    if (el) {
        el.classList.toggle('hidden');
        chev.style.transform = el.classList.contains('hidden') ? 'rotate(0deg)' : 'rotate(180deg)';
    }
}

async function deleteDataset(tableName, e) {
    if (e) {
        e.stopPropagation();
        e.preventDefault();
    }

    setTimeout(async () => {
        if (!confirm(`Remove dataset "${tableName}"?`)) return;
        
        try {
            const res = await fetch(`${API_BASE}/api/datasets/${encodeURIComponent(tableName)}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Delete failed');
            }
            showToast(`Dataset "${tableName}" removed.`);
            await loadDatasets();
        } catch (err) { 
            showToast(`Failed to remove dataset: ${err.message}`, true); 
        }
    }, 10);
}

async function uploadFile(file) {
    const SUPPORTED = ['.csv', '.xlsx', '.xls', '.pdf', '.txt', '.log', '.md'];
    if (!file || !SUPPORTED.some(ext => file.name.toLowerCase().endsWith(ext))) {
        showToast(`Please upload a supported file: ${SUPPORTED.join(', ')}`, true);
        return;
    }

    uploadProgress.classList.remove('hidden');
    uploadProgress.innerHTML = `
        <div class="upload-progress-bar-track"><div class="upload-progress-bar" id="uploadProgressBar" style="width:30%"></div></div>
        <div class="upload-progress-text">Uploading ${file.name}...</div>`;

    const formData = new FormData();
    formData.append('file', file);

    try {
        document.getElementById('uploadProgressBar').style.width = '60%';
        const res = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData,
        });
        document.getElementById('uploadProgressBar').style.width = '100%';

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Upload failed');
        }

        const data = await res.json();
        uploadProgress.classList.add('hidden');
        showToast(`✓ "${data.original_filename}" uploaded!`);
        await loadDatasets();

        welcomeEl.classList.add('hidden');

    } catch (err) {
        uploadProgress.classList.add('hidden');
        showToast(`Upload error: ${err.message}`, true);
    }
}

function showModal() { setupModal.classList.remove('hidden'); setTimeout(() => apiKeyInput.focus(), 300); }
function hideModal() { setupModal.classList.add('hidden'); }

providerTabs.addEventListener('click', e => {
    const tab = e.target.closest('.provider-tab');
    if (!tab) return;
    selectedProvider = tab.dataset.provider;
    document.querySelectorAll('.provider-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    providerInfo.innerHTML = PROVIDER_INFO[selectedProvider]?.text || '';
    apiKeyInput.value = '';
    modalError.textContent = '';
});

toggleVisBtn.addEventListener('click', () => {
    const isPw = apiKeyInput.type === 'password';
    apiKeyInput.type = isPw ? 'text' : 'password';
    toggleVisBtn.textContent = isPw ? 'hide' : 'see';
});

apiKeyInput.addEventListener('keydown', e => { if (e.key === 'Enter') handleModalSubmit(); });
modalSubmit.addEventListener('click', handleModalSubmit);
changeKeyBtn?.addEventListener('click', () => { apiKeyInput.value = ''; showModal(); });

async function handleModalSubmit() {
    const key = apiKeyInput.value.trim();
    if (!key) { modalError.textContent = 'Please paste an API key.'; return; }
    modalSubmit.disabled = true;
    modalSubmitText.textContent = 'Connecting...';
    modalSpinner.classList.remove('hidden');
    modalError.textContent = '';
    try {
        const res = await fetch(`${API_BASE}/api/set-key`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: selectedProvider, api_key: key }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to save key');
        hideModal();
        providerBadgeText.textContent = `✓ ${PROVIDER_INFO[selectedProvider]?.label || selectedProvider} connected`;
        providerBadge.style.display = 'flex';
        setStatus('ready', 'Ready');
    } catch (err) {
        modalError.textContent = `Error: ${err.message}`;
    } finally {
        modalSubmit.disabled = false;
        modalSubmitText.textContent = 'Connect & Start';
        modalSpinner.classList.add('hidden');
    }
}

function setupEventListeners() {
    sendBtn.addEventListener('click', handleSend);
    queryInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
    });
    queryInput.addEventListener('input', () => {
        queryInput.style.height = 'auto';
        queryInput.style.height = Math.min(queryInput.scrollHeight, 120) + 'px';
    });

    // Sample chips
    sampleQueriesEl?.addEventListener('click', e => {
        const chip = e.target.closest('.sample-chip');
        if (chip) { queryInput.value = chip.dataset.query; handleSend(); }
    });

    menuBtn?.addEventListener('click', () => { sidebar.classList.toggle('collapsed'); sidebar.classList.toggle('open'); });
    sidebarClose?.addEventListener('click', () => { sidebar.classList.add('collapsed'); sidebar.classList.remove('open'); });

    // FIX: guard uploadZone and attachBtn with optional chaining so a missing
    // element does not throw and abort the rest of setupEventListeners().
    uploadZone?.addEventListener('click', () => csvFileInput?.click());
    attachBtn?.addEventListener('click', () => csvFileInput?.click());
    uploadCtaBtn?.addEventListener('click', () => {
        sidebar.classList.remove('collapsed');
        sidebar.classList.add('open');
        csvFileInput?.click();
    });

    csvFileInput?.addEventListener('change', e => {
        if (e.target.files[0]) uploadFile(e.target.files[0]);
        e.target.value = '';
    });
    uploadZone?.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('dragover'); });
    uploadZone?.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
    uploadZone?.addEventListener('drop', e => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) uploadFile(file);
    });

    document.body.addEventListener('dragover', e => e.preventDefault());
    document.body.addEventListener('drop', e => {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        const SUPPORTED = ['.csv', '.xlsx', '.xls', '.pdf', '.txt', '.log', '.md'];
        if (file && SUPPORTED.some(ext => file.name.toLowerCase().endsWith(ext))) uploadFile(file);
    });
}

async function handleSend() {
    const question = queryInput.value.trim();
    if (!question || isProcessing) return;

    isProcessing = true;
    sendBtn.disabled = true;
    setStatus('loading', 'Thinking...');
    welcomeEl.classList.add('hidden');

    addUserMessage(question);
    queryInput.value = '';
    queryInput.style.height = 'auto';

    const loadingId = addLoadingMessage();

    try {
        const res = await fetch(`${API_BASE}/api/query`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question }),
        });
        removeMessage(loadingId);

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Server error' }));
            addErrorMessage(err.detail || 'Request failed');
            setStatus('error', 'Error');
            return;
        }

        const data = await res.json();
        if (data.status === 'no_api_key') { showModal(); setStatus('ready', 'Ready'); return; }
        addAssistantResponse(data);
        setStatus('ready', 'Ready');

    } catch (err) {
        removeMessage(loadingId);
        addErrorMessage(`Connection error: ${err.message}`);
        setStatus('error', 'Offline');
    } finally {
        isProcessing = false;
        sendBtn.disabled = false;
        queryInput.focus();
    }
}

function setStatus(type, text) {
    const dot = topStatus.querySelector('.status-dot');
    const label = topStatus.querySelector('.status-text');
    dot.className = 'status-dot' + (type === 'loading' ? ' loading' : type === 'error' ? ' error' : '');
    label.textContent = text;
}

function addUserMessage(text) {
    const id = 'msg-' + Date.now();
    const div = document.createElement('div');
    div.id = id; div.className = 'message user';
    div.innerHTML = `
        <div class="message-avatar">👤</div>
        <div class="message-content">
            <div class="message-bubble">${esc(text)}</div>
            <div class="message-meta"><span>${timestamp()}</span></div>
        </div>`;
    messagesEl.appendChild(div); scrollBottom(); return id;
}

function addLoadingMessage() {
    const id = 'loading-' + Date.now();
    const div = document.createElement('div');
    div.id = id; div.className = 'message assistant';
    div.innerHTML = `
        <div class="message-content">
            <div class="message-bubble">
                <div class="loading-dots"><span></span><span></span><span></span></div>
                <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">DeepAgent is analyzing your data...</div>
            </div>
        </div>`;
    messagesEl.appendChild(div); scrollBottom(); return id;
}

function removeMessage(id) { document.getElementById(id)?.remove(); }

function addErrorMessage(msg) {
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `
        <div class="message-content">
            <div class="message-bubble"><div class="error-badge">${esc(msg)}</div></div>
            <div class="message-meta"><span>${timestamp()}</span></div>
        </div>`;
    messagesEl.appendChild(div); scrollBottom();
}

function addAssistantResponse(data) {
    const div = document.createElement('div');
    div.className = 'message assistant';
    let html = '';
    const result = data.result || {};

    if (data.sql) {
        html += `<div class="sql-block">
            <div class="sql-header">
                <span>Generated SQL</span>
                <button class="sql-copy-btn" onclick="copySQL(this)">Copy</button>
            </div>
            <div class="sql-code">${highlightSQL(data.sql)}</div>
        </div>`;
    }

    if (data.status === 'success') {
        html += `<div class="result-section">`;
        
        // Parallel Results Breakdown
        if (data.results && data.results.length > 1) {
            html += `<div class="parallel-summary">
                <div class="msg-badge-parallel">⚡ PARALLEL EXECUTION</div>
                <div class="parallel-header">Multi-Agent Consensus</div>
                <div class="parallel-meta">Processed ${data.parallel_count || data.results.length} tasks in ${data.workflow_elapsed || data.elapsed}s</div>
            </div>
            <div class="parallel-agent-results">`;
            
            data.results.forEach(r => {
                const isErr = r.status === 'error';
                const res = r.result || {};
                html += `
                <div class="agent-result-card ${isErr ? 'error' : 'success'}">
                    <div class="agent-result-header">
                        <span class="agent-name">${esc(r.agent_name || r.agent_id)}</span>
                        <span class="agent-time">${r.elapsed}s</span>
                    </div>
                    <div class="agent-result-body">
                        ${isErr ? `<div class="error-text">${esc(res.message)}</div>` : 
                          res.answer ? formatAnswer(res.answer) : 'Data retrieved successfully.'}
                    </div>
                </div>`;
            });
            html += `</div><div style="margin-top:20px; border-top:1px solid var(--border); padding-top:16px;"></div>`;
        }

        html += `<div class="result-stats">
            <div class="result-stat">Total: <span class="stat-value">${data.workflow_elapsed || data.elapsed}s</span></div>
            ${data.provider ? `<div class="result-stat">LLM: <span class="stat-value">${data.provider}</span></div>` : ''}
            ${result.row_count ? `<div class="result-stat">Data: <span class="stat-value">${result.row_count} rows</span></div>` : ''}
            <div class="result-stat" style="color:var(--success)"><span class="stat-value">✓ Combined Success</span></div>
        </div>`;

        if (result.data?.length && result.columns?.length) {
            html += renderTable(result.columns, result.data);
            if (result.chart_type && result.label_column && result.numeric_columns?.length) {
                const cid = 'chart-' + (++chartCounter);
                html += `<div class="chart-container"><canvas id="${cid}" class="chart-canvas"></canvas></div>`;
                setTimeout(() => renderChart(cid, result), 120);
            }
        }

        if (result.answer) html += `<div class="agent-answer">${formatAnswer(result.answer)}</div>`;
        html += '</div>';

    } else if (data.status === 'no_data') {
        html += `<div class="error-badge" style="display:block;padding:12px 16px;">
            📁 ${esc(result.message || 'No data uploaded yet.')}</div>`;
    } else {
        html += `<div class="error-badge">${esc(result.message || data.message || 'Query failed.')}</div>`;
    }

    div.innerHTML = `
        <div class="message-content">
            <div class="message-bubble">${html || 'No response.'}</div>
            <div class="message-meta"><span>${timestamp()}</span></div>
        </div>`;
    messagesEl.appendChild(div); scrollBottom();
}

function renderTable(columns, data) {
    if (!columns || !columns.length || !data || !data.length) return '';
    let html = '<div class="result-table-wrapper"><table class="result-table"><thead><tr>';
    for (const col of columns) html += `<th>${esc(col)}</th>`;
    html += '</tr></thead><tbody>';
    for (const row of data) {
        html += '<tr>';
        for (const col of columns) {
            const v = row[col];
            html += `<td>${v !== null && v !== undefined ? esc(String(v)) : '—'}</td>`;
        }
        html += '</tr>';
    }
    return html + '</tbody></table></div>';
}

function renderChart(chartId, result) {
    const canvas = document.getElementById(chartId);
    if (!canvas) return;
    if (!result.data || !result.label_column || !result.numeric_columns || !result.numeric_columns.length) return;

    const labels = result.data.map(r => String(r[result.label_column]));
    const numCol = result.numeric_columns[0];
    const values = result.data.map(r => Number(r[numCol]) || 0);

    // FIX: was ['purple', ...] — 'purple' is a CSS keyword with no '0.8' to
    // replace, so bg.map(c => c.replace('0.8', '1')) left it as 'purple' for
    // borderColor and caused Chart.js to silently fail on datasets index 0.
    // All entries are now consistent rgba() strings.
    const palette = [
        'rgba(168,85,247,0.8)',
        'rgba(6,182,212,0.8)',
        'rgba(16,185,129,0.8)',
        'rgba(245,158,11,0.8)',
        'rgba(239,68,68,0.8)',
        'rgba(59,130,246,0.8)',
    ];
    const bg = values.map((_, i) => palette[i % palette.length]);
    const ctype = result.data.length <= 6 ? 'doughnut' : (result.chart_type || 'bar');

    new Chart(canvas, {
        type: ctype,
        data: {
            labels,
            datasets: [{
                label: numCol,
                data: values,
                backgroundColor: bg,
                borderColor: bg.map(c => c.replace('0.8', '1')),
                borderWidth: 1,
                tension: 0.4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { display: ctype === 'doughnut', position: 'bottom', labels: { color: '#8888a0', font: { family: "'Inter',sans-serif", size: 11 }, padding: 16 } },
                tooltip: {
                    backgroundColor: 'rgba(10,10,15,0.92)', titleColor: '#e8e8f0', bodyColor: '#8888a0',
                    borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1, cornerRadius: 8, padding: 12,
                    callbacks: { label: ctx => { const v = ctx.parsed.y ?? ctx.parsed; return ` ${numCol}: ${typeof v === 'number' ? v.toLocaleString() : v}`; } }
                }
            },
            scales: ctype === 'doughnut' ? {} : {
                x: { ticks: { color: '#55556a', font: { size: 11 } }, grid: { color: 'rgba(255,255,255,0.03)' } },
                y: { ticks: { color: '#55556a', font: { size: 11 }, callback: v => typeof v === 'number' ? v.toLocaleString() : v }, grid: { color: 'rgba(255,255,255,0.03)' } }
            }
        }
    });
}

function formatAnswer(text) {
    if (!text) return '';
    let finalContent = '';

    if (Array.isArray(text)) {
        finalContent = text.map(block => {
            if (typeof block === 'string') return block;
            if (block && block.type === 'text') return block.text || '';
            return JSON.stringify(block);
        }).join('\n');
    } else if (typeof text === 'object' && text !== null) {
        finalContent = text.text || JSON.stringify(text);
    } else {
        finalContent = String(text ?? '');
    }

    let html = esc(finalContent);
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.3);padding:2px 6px;border-radius:4px;font-family:var(--font-mono);font-size:12px;">$1</code>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

function highlightSQL(sql) {
    const KW = ['SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'GROUP BY', 'ORDER BY', 'HAVING',
        'LIMIT', 'OFFSET', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN', 'ON', 'AS',
        'DISTINCT', 'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DESC', 'ASC', 'BETWEEN', 'LIKE',
        'IN', 'NOT', 'NULL', 'IS', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'UNION', 'ALL',
        'ROUND', 'COALESCE', 'IFNULL'];
    let out = esc(sql);
    for (const kw of KW) {
        out = out.replace(new RegExp(`\\b(${kw})\\b`, 'gi'), `<span style="color:#818cf8;font-weight:500">$1</span>`);
    }
    out = out.replace(/'([^']*)'/g, `<span style="color:#34d399">'$1'</span>`);
    out = out.replace(/\b(\d+(?:\.\d+)?)\b/g, `<span style="color:#fbbf24">$1</span>`);
    return out;
}

function showToast(msg, isError = false) {
    const t = document.createElement('div');
    t.className = 'upload-toast';
    if (isError) t.style.cssText = 'background:rgba(239,68,68,0.12);border-color:rgba(239,68,68,0.3);color:#ef4444';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3200);
}

function esc(s) { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; }
function scrollBottom() { requestAnimationFrame(() => { chatArea.scrollTop = chatArea.scrollHeight; }); }
function timestamp() { return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
function copySQL(btn) {
    const code = btn.closest('.sql-block').querySelector('.sql-code');
    navigator.clipboard.writeText(code.textContent || '').then(() => {
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
    });
}
