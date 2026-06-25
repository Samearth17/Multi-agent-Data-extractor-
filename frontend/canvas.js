const API = window.location.origin;
let agents = [];
let connections = [];
let selectedNodeId = null;
let panelAgentId = null;
let panelMessages = {};
let nodeFiles = {};
let canvasChartCounter = 0;

let viewX = 0, viewY = 0, viewScale = 1;
let isPanning = false, panStartX = 0, panStartY = 0;

let isDragging = false, dragNodeId = null, dragOffsetX = 0, dragOffsetY = 0;
let lastUploadedTable = null;
let lastUploadedAgent = null;

const viewport = document.getElementById('canvasViewport');
const world = document.getElementById('canvasWorld');
const wiresSvg = document.getElementById('canvasWires');
const agentPanel = document.getElementById('agentPanel');
const panelIcon = document.getElementById('agentPanelIcon');
const panelName = document.getElementById('agentPanelName');
const panelType = document.getElementById('agentPanelType');
const panelDesc = document.getElementById('agentPanelDesc');
const panelMsgs = document.getElementById('agentPanelMessages');
const panelInput = document.getElementById('agentPanelInput');
const panelSend = document.getElementById('agentPanelSend');
const panelClose = document.getElementById('agentPanelClose');
const navStatus = document.getElementById('navbarStatus');
const workflowModal = document.getElementById('workflowModal');
const workflowInput = document.getElementById('workflowInput');
const toastContainer = document.getElementById('toastContainer');

document.addEventListener('DOMContentLoaded', async () => {
    await loadAgents();
    setupCanvasControls();
    setupPanelControls();
    setupWorkflowControls();
    centerView();
});

async function loadAgents() {
    try {
        const res = await fetch(`${API}/api/agents`);
        const data = await res.json();
        agents = data.agents || [];
        connections = data.connections || [];
        renderNodes();
        renderWires();
    } catch (e) {
        showToast('Failed to load agents: ' + e.message, true);
    }
}


function renderNodes() {
    world.querySelectorAll('.agent-node').forEach(n => n.remove());

    for (const agent of agents) {
        const node = document.createElement('div');
        node.className = 'agent-node';
        node.id = `node-${agent.id}`;
        node.style.left = agent.position.x + 'px';
        node.style.top = agent.position.y + 'px';

        const iconBg = agent.color + '20';
        const acceptExts = (agent.accepts || []).join(',');
        const acceptLabel = agent.accept_label || 'files';
        const filesHtml = (nodeFiles[agent.id] || []).map(f =>
            `<div class="node-file-badge">
                📎 ${esc(f.filename)} <span>${f.row_count} rows</span>
                <button type="button" class="node-file-remove" onclick="removeNodeFile('${agent.id}', '${esc(f.table_name)}', event)">✕</button>
            </div>`
        ).join('');

        node.innerHTML = `
            <div class="node-port node-port-in"></div>
            <div class="node-header">
                <div class="node-icon" style="background:${iconBg};">${agent.icon}</div>
                <div class="node-title-area">
                    <div class="node-name">${agent.name}</div>
                    <div class="node-type">${agent.type}</div>
                </div>
            </div>
            <div class="node-body">
                <div class="node-desc">${agent.description}</div>
            </div>
            <div class="node-upload-zone" data-agent="${agent.id}" data-accepts="${acceptExts}">
                <div class="node-upload-icon">📁</div>
                <div class="node-upload-text">Drop ${acceptLabel} here</div>
                <input type="file" class="node-file-input" accept="${acceptExts}" style="display:none;">
            </div>
            <div class="node-files-list" id="files-${agent.id}">${filesHtml}</div>
            <div class="node-upload-progress hidden" id="progress-${agent.id}">
                <div class="node-progress-bar"></div>
                <div class="node-progress-text">Uploading...</div>
            </div>
            <div class="node-footer">
                <div class="node-status">
                    <div class="node-status-indicator"></div>
                    <span>Idle</span>
                </div>
                <button class="node-action-btn" data-agent="${agent.id}">Chat</button>
            </div>
            <div class="node-port node-port-out"></div>
        `;

        node.addEventListener('mousedown', (e) => onNodeMouseDown(e, agent.id));
        node.addEventListener('dblclick', (e) => {
            if (!e.target.closest('.node-upload-zone')) openPanel(agent.id);
        });
        node.querySelector('.node-action-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            openPanel(agent.id);
        });

        const uploadZone = node.querySelector('.node-upload-zone');
        const fileInput = node.querySelector('.node-file-input');

        uploadZone.addEventListener('click', (e) => {
            e.stopPropagation();
            fileInput.click();
        });

        fileInput.addEventListener('change', (e) => {
            e.stopPropagation();
            if (e.target.files[0]) handleNodeUpload(agent.id, e.target.files[0]);
            e.target.value = '';
        });

        uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            uploadZone.classList.add('dragover');
        });
        uploadZone.addEventListener('dragleave', (e) => {
            e.stopPropagation();
            uploadZone.classList.remove('dragover');
        });
        uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            uploadZone.classList.remove('dragover');
            const file = e.dataTransfer.files[0];
            if (file) handleNodeUpload(agent.id, file);
        });

        world.appendChild(node);
    }
}

async function handleNodeUpload(agentId, file) {
    const agent = agents.find(a => a.id === agentId);
    if (!agent) return;
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    const accepted = agent.accepts || [];
    if (accepted.length && !accepted.includes(ext)) {
        showToast(`${agent.name} only accepts: ${accepted.join(', ')}`, true);
        return;
    }

    const progressEl = document.getElementById(`progress-${agentId}`);
    if (progressEl) {
        progressEl.classList.remove('hidden');
        progressEl.querySelector('.node-progress-text').textContent = `Uploading ${file.name}...`;
        progressEl.querySelector('.node-progress-bar').style.width = '40%';
    }
    setNodeState(agentId, 'processing');
    setNavStatus('loading', `Uploading to ${agent.name}...`);

    const formData = new FormData();
    formData.append('file', file);

    try {
        if (progressEl) progressEl.querySelector('.node-progress-bar').style.width = '70%';

        const res = await fetch(`${API}/api/agent/upload?agent_id=${agentId}`, {
            method: 'POST',
            body: formData,
        });

        if (progressEl) progressEl.querySelector('.node-progress-bar').style.width = '100%';

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Upload failed');
        }

        const data = await res.json();

        // Deliverable 1: Auto-categorize / Auto-route
        let targetId = agentId;
        const recommended = data.recommended_agents || [];
        const currentMeta = agents.find(a => a.id === agentId) || {};
        
        let specialist = null;
        if ((currentMeta.type === 'orchestrator' || currentMeta.type === 'manager') && recommended.length > 0) {
            // Find the most specific recommended agent
            specialist = agents.find(a => recommended.includes(a.id) && a.type === 'specialist');
            if (specialist) {
                targetId = specialist.id;
                showToast(`Auto-categorized: ${file.name} → ${specialist.name}`);
            } else {
                showToast(`Debug: No specialist found. Recommended: ${recommended.join(',')}`);
            }
        } else {
            showToast(`Debug: Not orchestrator/manager OR empty recommended. Type: ${currentMeta.type}, Recommended: ${recommended.length}`);
        }

        if (!nodeFiles[targetId]) nodeFiles[targetId] = [];
        nodeFiles[targetId].push({
            filename: data.original_filename || file.name,
            table_name: data.table_name,
            row_count: data.row_count || 0,
        });
        
        lastUploadedTable = data.table_name;
        lastUploadedAgent = targetId;

        updateNodeFilesList(targetId);

        setTimeout(() => {
            if (progressEl) progressEl.classList.add('hidden');
        }, 800);

        // Deliverable 1: Visual Routing Animation
        if (targetId !== agentId) {
            // Animate from agentId down to targetId
            setNodeState(agentId, 'idle'); // clear the upload processing state
            await animateWorkflowStart(targetId);
            
            // Turn them green
            let currentId = targetId;
            while (currentId) {
                setNodeState(currentId, 'activated');
                const a = agents.find(ag => ag.id === currentId);
                currentId = a ? a.parent : null;
            }
        } else {
            setNodeState(agentId, 'activated');
        }
        
        setNavStatus('ready', 'Ready');
        showToast(`✓ ${file.name} → ${specialist ? specialist.name : agent.name} (${data.row_count} rows)`);

        if (!panelMessages[agentId]) panelMessages[agentId] = [];
        panelMessages[agentId].push({
            role: 'assistant',
            content: `File "${file.name}" uploaded successfully!\n\nTable: ${data.table_name}\nRows: ${data.row_count}\nColumns: ${(data.columns || []).join(', ')}\n\nYou can now ask me questions about this data.`,
        });
        if (panelAgentId === agentId) renderPanelMessages();

    } catch (err) {
        if (progressEl) progressEl.classList.add('hidden');
        setNodeState(agentId, 'idle');
        setNavStatus('error', 'Upload failed');
        showToast(`Upload error: ${err.message}`, true);
    }
}

function updateNodeFilesList(agentId) {
    const listEl = document.getElementById(`files-${agentId}`);
    if (!listEl) return;
    const files = nodeFiles[agentId] || [];
    listEl.innerHTML = files.map(f =>
        `<div class="node-file-badge">
            📎 ${esc(f.filename)} <span>${f.row_count} rows</span>
            <button type="button" class="node-file-remove" onclick="removeNodeFile('${agentId}', '${esc(f.table_name)}', event)">✕</button>
        </div>`
    ).join('');
}

async function removeNodeFile(agentId, tableName, event) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }

    setTimeout(async () => {
        if (!confirm(`Remove table "${tableName}"?`)) return;

        setNavStatus('loading', `Removing ${tableName}...`);
        try {
            const res = await fetch(`${API}/api/datasets/${encodeURIComponent(tableName)}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Delete failed');
            }

            if (nodeFiles[agentId]) {
                nodeFiles[agentId] = nodeFiles[agentId].filter(f => f.table_name !== tableName);
            }

            updateNodeFilesList(agentId);
            showToast(`✓ Table "${tableName}" removed.`);
            setNavStatus('ready', 'Ready');

            if (!nodeFiles[agentId]?.length) setNodeState(agentId, 'idle');

        } catch (err) {
            showToast(`Error: ${err.message}`, true);
            setNavStatus('error', 'Delete failed');
        }
    }, 10);
}

function renderWires() {
    wiresSvg.innerHTML = '';

    for (const conn of connections) {
        const fromEl = document.getElementById(`node-${conn.from}`);
        const toEl = document.getElementById(`node-${conn.to}`);
        if (!fromEl || !toEl) continue;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.classList.add('wire-path');
        path.id = `wire-${conn.from}-${conn.to}`;
        path.setAttribute('d', calcWirePath(fromEl, toEl));
        wiresSvg.appendChild(path);
    }
}

function calcWirePath(fromEl, toEl) {
    const fx = parseFloat(fromEl.style.left) + fromEl.offsetWidth / 2;
    const fy = parseFloat(fromEl.style.top) + fromEl.offsetHeight;
    const tx = parseFloat(toEl.style.left) + toEl.offsetWidth / 2;
    const ty = parseFloat(toEl.style.top);

    const midY = (fy + ty) / 2;
    const cp = Math.abs(ty - fy) * 0.5;

    return `M ${fx} ${fy} C ${fx} ${fy + cp}, ${tx} ${ty - cp}, ${tx} ${ty}`;
}

function setupCanvasControls() {
    viewport.addEventListener('mousedown', (e) => {
        if (e.target === viewport || e.target === world || e.target.tagName === 'svg') {
            isPanning = true;
            panStartX = e.clientX - viewX;
            panStartY = e.clientY - viewY;
            deselectAll();
        }
    });

    window.addEventListener('mousemove', (e) => {
        if (isPanning) {
            viewX = e.clientX - panStartX;
            viewY = e.clientY - panStartY;
            applyTransform();
        }
        if (isDragging && dragNodeId) {
            const node = document.getElementById(`node-${dragNodeId}`);
            if (node) {
                const x = (e.clientX - dragOffsetX - viewX) / viewScale;
                const y = (e.clientY - dragOffsetY - viewY) / viewScale;
                node.style.left = x + 'px';
                node.style.top = y + 'px';
                const agent = agents.find(a => a.id === dragNodeId);
                if (agent) { agent.position.x = x; agent.position.y = y; }
                renderWires();
            }
        }
    });

    window.addEventListener('mouseup', () => {
        isPanning = false;
        isDragging = false;
        dragNodeId = null;
    });

    viewport.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? -0.08 : 0.08;
        const newScale = Math.max(0.3, Math.min(2.5, viewScale + delta));

        const rect = viewport.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        viewX = mx - (mx - viewX) * (newScale / viewScale);
        viewY = my - (my - viewY) * (newScale / viewScale);
        viewScale = newScale;
        applyTransform();
    }, { passive: false });

    document.getElementById('zoomInBtn').addEventListener('click', () => {
        viewScale = Math.min(2.5, viewScale + 0.15);
        applyTransform();
    });
    document.getElementById('zoomOutBtn').addEventListener('click', () => {
        viewScale = Math.max(0.3, viewScale - 0.15);
        applyTransform();
    });
    document.getElementById('resetViewBtn').addEventListener('click', centerView);
}

function applyTransform() {
    world.style.transform = `translate(${viewX}px, ${viewY}px) scale(${viewScale})`;
}

function centerView() {
    if (!agents.length) return;
    const xs = agents.map(a => a.position.x);
    const ys = agents.map(a => a.position.y);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2 + 105;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2 + 80;

    viewScale = 0.9;
    viewX = (viewport.clientWidth / 2) - cx * viewScale;
    viewY = (viewport.clientHeight / 2) - cy * viewScale + 20;
    applyTransform();
}

function onNodeMouseDown(e, agentId) {
    if (e.target.closest('.node-action-btn')) return;
    e.stopPropagation();

    selectNode(agentId);

    isDragging = true;
    dragNodeId = agentId;
    const node = document.getElementById(`node-${agentId}`);
    const rect = node.getBoundingClientRect();
    dragOffsetX = e.clientX - rect.left;
    dragOffsetY = e.clientY - rect.top;
}

function selectNode(agentId) {
    deselectAll();
    selectedNodeId = agentId;
    const node = document.getElementById(`node-${agentId}`);
    if (node) node.classList.add('selected');
}

function deselectAll() {
    selectedNodeId = null;
    document.querySelectorAll('.agent-node.selected').forEach(n => n.classList.remove('selected'));
}

function setupPanelControls() {
    panelClose.addEventListener('click', closePanel);
    panelSend.addEventListener('click', sendPanelMessage);
    panelInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendPanelMessage();
        }
    });
    panelInput.addEventListener('input', () => {
        panelInput.style.height = 'auto';
        panelInput.style.height = Math.min(panelInput.scrollHeight, 100) + 'px';
    });
}

function openPanel(agentId) {
    const agent = agents.find(a => a.id === agentId);
    if (!agent) return;

    panelAgentId = agentId;
    selectNode(agentId);

    panelIcon.textContent = agent.icon;
    panelIcon.style.background = agent.color + '20';
    panelName.textContent = agent.name;
    panelType.textContent = agent.type;
    panelDesc.textContent = agent.description;

    renderPanelMessages();

    agentPanel.classList.remove('hidden');
    setTimeout(() => panelInput.focus(), 300);
}

function closePanel() {
    agentPanel.classList.add('hidden');
    panelAgentId = null;
}

function renderPanelMessages() {
    const msgs = panelMessages[panelAgentId] || [];
    if (!msgs.length) {
        panelMsgs.innerHTML = '<div class="agent-panel-empty">Double-click a node or type a question below to interact with this agent.</div>';
        return;
    }

    const pendingCharts = [];

    panelMsgs.innerHTML = msgs.map(m => {
        if (m.role === 'user') {
            return `<div class="panel-msg user">${esc(m.content)}</div>`;
        }
        let html = '';
        if (m.error) {
            html = `<div class="msg-error">${esc(m.content)}</div>`;
        } else {
            html = `<div class="msg-answer">${formatText(m.content)}</div>`;
            if (m.sql) {
                html += `<div class="msg-sql">${esc(m.sql)}</div>`;
            }
            if (m.data && m.columns && m.data.length) {
                html += renderPanelTable(m.columns, m.data);
                // Add chart if chart metadata is present
                if (m.chart_type && m.label_column && m.numeric_columns && m.numeric_columns.length) {
                    const cid = 'panel-chart-' + (++canvasChartCounter);
                    html += `<div class="panel-chart-container"><canvas id="${cid}" class="panel-chart-canvas"></canvas></div>`;
                    pendingCharts.push({ id: cid, data: m.data, chart_type: m.chart_type, label_column: m.label_column, numeric_columns: m.numeric_columns });
                }
            }
        }
        html += `<div class="msg-meta">`;
        if (m.elapsed) html += `<span>${m.elapsed}s</span>`;
        if (m.provider) html += `<span>${m.provider}</span>`;
        html += `</div>`;
        return `<div class="panel-msg assistant">${html}</div>`;
    }).join('');

    panelMsgs.scrollTop = panelMsgs.scrollHeight;

    // Render charts after DOM is updated
    if (pendingCharts.length) {
        setTimeout(() => {
            for (const c of pendingCharts) {
                renderPanelChart(c.id, c);
            }
        }, 150);
    }
}

function renderPanelTable(columns, data) {
    let html = '<div class="panel-table-wrap"><table><thead><tr>';
    for (const c of columns) html += `<th>${esc(c)}</th>`;
    html += '</tr></thead><tbody>';
    for (const row of data) {
        html += '<tr>';
        for (const c of columns) {
            const v = row[c];
            html += `<td>${v !== null && v !== undefined ? esc(String(v)) : '—'}</td>`;
        }
        html += '</tr>';
    }
    return html + '</tbody></table></div>';
}

async function sendPanelMessage() {
    const question = panelInput.value.trim();
    if (!question || !panelAgentId) return;

    if (!panelMessages[panelAgentId]) panelMessages[panelAgentId] = [];

    panelMessages[panelAgentId].push({ role: 'user', content: question });
    panelInput.value = '';
    panelInput.style.height = 'auto';
    renderPanelMessages();

    const loadingEl = document.createElement('div');
    loadingEl.className = 'panel-msg-loading';
    loadingEl.innerHTML = '<span></span><span></span><span></span>';
    panelMsgs.appendChild(loadingEl);
    panelMsgs.scrollTop = panelMsgs.scrollHeight;

    setNodeState(panelAgentId, 'processing');
    setNavStatus('loading', 'Processing...');

    try {
        const res = await fetch(`${API}/api/agent/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, agent_id: panelAgentId }),
        });
        const data = await res.json();
        loadingEl.remove();

        if (data.status === 'success') {
            const result = data.result || {};
            panelMessages[panelAgentId].push({
                role: 'assistant',
                content: result.answer || 'Done.',
                sql: data.sql || '',
                elapsed: data.elapsed,
                provider: data.provider,
                data: result.data,
                columns: result.columns,
                chart_type: result.chart_type,
                numeric_columns: result.numeric_columns,
                label_column: result.label_column,
            });
            setNodeState(panelAgentId, 'activated');
        } else {
            panelMessages[panelAgentId].push({
                role: 'assistant',
                content: data.result?.message || data.message || 'Agent failed.',
                error: true,
            });
            setNodeState(panelAgentId, 'idle');
        }

        renderPanelMessages();
        setNavStatus('ready', 'Ready');

    } catch (err) {
        loadingEl.remove();
        panelMessages[panelAgentId].push({
            role: 'assistant',
            content: 'Connection error: ' + err.message,
            error: true,
        });
        renderPanelMessages();
        setNodeState(panelAgentId, 'idle');
        setNavStatus('error', 'Error');
    }
}

function setupWorkflowControls() {
    document.getElementById('runWorkflowBtn').addEventListener('click', () => {
        workflowModal.classList.remove('hidden');
        setTimeout(() => workflowInput.focus(), 200);
    });
    document.getElementById('workflowCancel').addEventListener('click', () => {
        workflowModal.classList.add('hidden');
    });
    document.getElementById('workflowRun').addEventListener('click', runWorkflow);
    workflowInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            runWorkflow();
        }
    });
    
    const clearAllBtn = document.getElementById('clearAllBtn');
    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', clearAllData);
    }
}

async function clearAllData() {
    if (!confirm('Are you sure you want to clear ALL uploaded files and data? This cannot be undone.')) {
        return;
    }
    
    setNavStatus('loading', 'Clearing all data...');
    try {
        const res = await fetch(`${API}/api/datasets/clear-all`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to clear data');
        
        // Reset local state
        nodeFiles = {};
        panelMessages = {};
        document.querySelectorAll('.node-files-list').forEach(el => el.innerHTML = '');
        
        showToast('All data cleared successfully');
        setNavStatus('ready', 'Ready');
    } catch (err) {
        showToast(`Error clearing data: ${err.message}`, true);
        setNavStatus('error', 'Clear failed');
    }
}

async function runWorkflow() {
    const question = workflowInput.value.trim();
    if (!question) return;

    workflowModal.classList.add('hidden');
    setNavStatus('loading', 'Running workflow...');

    agents.forEach(a => setNodeState(a.id, 'idle'));
    clearAllWires();

    const allFilesCount = Object.values(nodeFiles).flat().length;
    await animateWorkflowStart(allFilesCount > 1 ? null : lastUploadedAgent);

    try {
        const payload = { question };
        
        // Check total file count across all agents
        const allFiles = Object.values(nodeFiles).flat();
        
        if (allFiles.length > 1) {
            // MULTI-FILE MODE: Run the whole workflow automatically
            // By sending nulls, the backend auto-detects every relevant agent type (PDF, Excel, etc.)
            payload.focus_agents = null;
            payload.focus_tables = null;
            console.log("Multi-file mode: Running auto-detected global workflow");
        } else {
            // SINGLE-FILE MODE: Stay focused on the specific agent for speed
            if (lastUploadedTable) {
                payload.focus_tables = [lastUploadedTable];
            }
            if (lastUploadedAgent) {
                payload.focus_agents = [lastUploadedAgent];
            }
            console.log("Single-file mode: Running focused agent", lastUploadedAgent);
        }

        const res = await fetch(`${API}/api/parallel-analysis`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (data.status === 'success') {
            const activated = data.activated_agents || [];
            agents.forEach(a => setNodeState(a.id, 'idle'));
            for (const id of activated) {
                setNodeState(id, 'activated');
            }
            activateWires(activated);

            const combinedResult = data.result || {};

            // Populate orchestrator with the full merged answer
            if (!panelMessages['data_extractor']) panelMessages['data_extractor'] = [];
            panelMessages['data_extractor'].push(
                { role: 'user', content: question },
                {
                    role: 'assistant',
                    content: combinedResult.answer || `Parallel execution complete (${data.parallel_count || 0} agents, ${data.workflow_elapsed || data.elapsed}s).`,
                    sql: data.sql || '',
                    elapsed: data.workflow_elapsed || data.elapsed,
                    provider: data.provider,
                    data: combinedResult.data,
                    columns: combinedResult.columns,
                    chart_type: combinedResult.chart_type,
                    numeric_columns: combinedResult.numeric_columns,
                    label_column: combinedResult.label_column,
                }
            );

            // Also populate specific sub-agent panels with their individual results
            if (data.results && data.results.length > 0) {
                for (const r of data.results) {
                    const agentId = r.agent_id;
                    if (!panelMessages[agentId]) panelMessages[agentId] = [];
                    
                    const subResult = r.result || {};
                    panelMessages[agentId].push(
                        { role: 'user', content: question },
                        {
                            role: 'assistant',
                            content: subResult.answer || subResult.message || 'Done.',
                            sql: r.sql || '',
                            elapsed: r.elapsed,
                            provider: r.provider,
                            data: subResult.data,
                            columns: subResult.columns,
                            chart_type: subResult.chart_type,
                            numeric_columns: subResult.numeric_columns,
                            label_column: subResult.label_column,
                        }
                    );
                    setNodeState(agentId, r.status === 'success' ? 'activated' : 'error');
                }
            }

            openPanel('data_extractor');
            showToast(`Parallel workflow complete in ${data.workflow_elapsed || data.elapsed}s`);
        } else {
            agents.forEach(a => setNodeState(a.id, 'idle'));
            showToast(data.result?.message || data.message || 'Workflow failed.', true);
        }

        setNavStatus('ready', 'Ready');

    } catch (err) {
        agents.forEach(a => setNodeState(a.id, 'idle'));
        showToast('Connection error: ' + err.message, true);
        setNavStatus('error', 'Error');
    }
}

async function animateWorkflowStart(focusAgentId) {
    if (!focusAgentId) {
        const order = ['data_extractor', 'structured_data', 'unstructured_data', 'csv_agent', 'xls_agent', 'pdf_agent', 'text_agent'];
        for (const id of order) {
            setNodeState(id, 'processing');
            await sleep(200);
        }
        return;
    }

    const activeIds = [];
    let currentId = focusAgentId;
    while (currentId) {
        activeIds.unshift(currentId);
        const agent = agents.find(a => a.id === currentId);
        currentId = agent ? agent.parent : null;
    }

    for (let i = 0; i < activeIds.length; i++) {
        const id = activeIds[i];
        setNodeState(id, 'processing');
        if (i > 0) {
            const wire = document.getElementById(`wire-${activeIds[i-1]}-${id}`);
            if (wire) wire.classList.add('active');
        }
        await sleep(200);
    }
}

function setNodeState(agentId, state) {
    const node = document.getElementById(`node-${agentId}`);
    if (!node) return;

    node.classList.remove('activated', 'processing');
    const indicator = node.querySelector('.node-status-indicator');
    const statusText = node.querySelector('.node-status span');

    if (state === 'activated') {
        node.classList.add('activated');
        if (indicator) { indicator.style.background = 'var(--success)'; indicator.style.boxShadow = '0 0 8px rgba(16,185,129,0.5)'; }
        if (statusText) statusText.textContent = 'Active';
    } else if (state === 'processing') {
        node.classList.add('processing');
        if (indicator) { indicator.style.background = 'var(--warning)'; indicator.style.boxShadow = '0 0 8px rgba(245,158,11,0.5)'; }
        if (statusText) statusText.textContent = 'Processing...';
    } else {
        if (indicator) { indicator.style.background = 'var(--text-muted)'; indicator.style.boxShadow = 'none'; }
        if (statusText) statusText.textContent = 'Idle';
    }
}

function clearAllWires() {
    wiresSvg.querySelectorAll('.wire-path').forEach(p => p.classList.remove('active'));
}

function activateWires(activatedIds) {
    for (const conn of connections) {
        const wire = document.getElementById(`wire-${conn.from}-${conn.to}`);
        if (wire && activatedIds.includes(conn.from) && activatedIds.includes(conn.to)) {
            wire.classList.add('active');
        }
    }
}

function setNavStatus(type, text) {
    const dot = navStatus.querySelector('.nav-status-dot');
    const label = navStatus.querySelector('.nav-status-text');
    dot.className = 'nav-status-dot';
    if (type === 'loading') dot.classList.add('loading');
    else if (type === 'error') dot.classList.add('error');
    label.textContent = text;
}

function showToast(msg, isError = false) {
    const t = document.createElement('div');
    t.className = 'canvas-toast';
    if (isError) t.style.cssText = 'background:rgba(239,68,68,0.12);border-color:rgba(239,68,68,0.3);color:#ef4444';
    t.textContent = msg;
    toastContainer.appendChild(t);
    setTimeout(() => t.remove(), 3200);
}

function esc(s) {
    const d = document.createElement('div');
    d.textContent = String(s ?? '');
    return d.innerHTML;
}

function formatText(text) {
    if (!text) return '';
    let html = esc(text);
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.3);padding:2px 5px;border-radius:3px;font-family:var(--font-mono);font-size:11px;">$1</code>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function renderPanelChart(chartId, chartInfo) {
    const canvas = document.getElementById(chartId);
    if (!canvas) return;

    const labels = chartInfo.data.map(r => String(r[chartInfo.label_column] || ''));
    const numCol = chartInfo.numeric_columns[0];
    const values = chartInfo.data.map(r => Number(r[numCol]) || 0);

    const palette = [
        'rgba(139,92,246,0.8)', 'rgba(168,85,247,0.8)', 'rgba(6,182,212,0.8)',
        'rgba(16,185,129,0.8)', 'rgba(245,158,11,0.8)', 'rgba(239,68,68,0.8)',
        'rgba(59,130,246,0.8)', 'rgba(236,72,153,0.8)',
    ];
    const bg = values.map((_, i) => palette[i % palette.length]);
    const ctype = chartInfo.data.length <= 6 ? 'doughnut' : (chartInfo.chart_type || 'bar');

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
                legend: {
                    display: ctype === 'doughnut',
                    position: 'bottom',
                    labels: { color: '#8888a0', font: { family: "'Inter',sans-serif", size: 11 }, padding: 12 }
                },
                tooltip: {
                    backgroundColor: 'rgba(10,10,15,0.92)',
                    titleColor: '#e8e8f0',
                    bodyColor: '#8888a0',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    padding: 10,
                    callbacks: {
                        label: ctx => {
                            const v = ctx.parsed.y ?? ctx.parsed;
                            return ` ${numCol}: ${typeof v === 'number' ? v.toLocaleString() : v}`;
                        }
                    }
                }
            },
            scales: ctype === 'doughnut' ? {} : {
                x: { ticks: { color: '#55556a', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.03)' } },
                y: { ticks: { color: '#55556a', font: { size: 10 }, callback: v => typeof v === 'number' ? v.toLocaleString() : v }, grid: { color: 'rgba(255,255,255,0.03)' } }
            }
        }
    });
}
