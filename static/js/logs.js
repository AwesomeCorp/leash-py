/* ==========================================================================
   Logs Page Logic - Detailed View with Incremental Updates
   ========================================================================== */

var lastLogTimestamp = null;
var lastLogCount = 0;

/* ---------- Chip Filter Definitions & State ---------- */
var chipDefinitions = {
    harness: ['claude', 'copilot'],
    hookType: ['PermissionRequest', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'UserPromptSubmit', 'Stop', 'TrayDecision'],
    toolName: ['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'WebFetch', 'WebSearch', 'Task'],
    category: ['safe', 'cautious', 'risky', 'dangerous'],
    decision: ['auto-approved', 'denied', 'logged', 'tray-approved', 'tray-denied', 'tray-ignored', 'tray-timeout']
};

var activeChipFilters = {};

function initChipFilters() {
    Object.keys(chipDefinitions).forEach(function(group) {
        var storageKey = 'cpa-logs-chips-' + group;
        var saved = null;
        try { saved = JSON.parse(localStorage.getItem(storageKey)); } catch {}
        if (Array.isArray(saved)) {
            activeChipFilters[group] = new Set(saved);
        } else {
            // Default: all selected
            activeChipFilters[group] = new Set(chipDefinitions[group]);
        }
        renderChipGroup(group);
    });
}

function renderChipGroup(group) {
    var container = document.getElementById('chipGroup-' + group);
    if (!container) return;
    var values = chipDefinitions[group];
    var active = activeChipFilters[group];

    var html = values.map(function(v) {
        var isActive = active.has(v);
        return '<span class="filter-chip ' + (isActive ? 'active' : '') + '" data-group="' + group + '" data-value="' + escapeHtml(v) + '" onclick="toggleChip(\'' + group + '\',\'' + escapeHtml(v) + '\')">' + escapeHtml(v) + '</span>';
    }).join('');

    var allActive = active.size === values.length;
    html += '<span class="filter-chip toggle-all ' + (allActive ? 'active' : '') + '" onclick="toggleAllChips(\'' + group + '\')">Toggle All</span>';

    container.innerHTML = html;
}

function toggleChip(group, value) {
    var active = activeChipFilters[group];
    if (active.has(value)) {
        active.delete(value);
    } else {
        active.add(value);
    }
    saveChipState(group);
    renderChipGroup(group);
    lastLogTimestamp = null;
    lastLogCount = 0;
    loadLogs(true);
}

function toggleAllChips(group) {
    var active = activeChipFilters[group];
    var all = chipDefinitions[group];
    if (active.size === all.length) {
        // All selected -> deselect all
        activeChipFilters[group] = new Set();
    } else {
        // Some/none selected -> select all
        activeChipFilters[group] = new Set(all);
    }
    saveChipState(group);
    renderChipGroup(group);
    lastLogTimestamp = null;
    lastLogCount = 0;
    loadLogs(true);
}

function saveChipState(group) {
    var storageKey = 'cpa-logs-chips-' + group;
    try { localStorage.setItem(storageKey, JSON.stringify(Array.from(activeChipFilters[group]))); } catch {}
}

function getChipFilterParam(group) {
    var active = activeChipFilters[group];
    var all = chipDefinitions[group];
    // All selected = no filter (show everything)
    if (!active || active.size === all.length) return '';
    // None selected = match nothing (hide all)
    if (active.size === 0) return '__none__';
    return Array.from(active).join(',');
}

/* ---------- Data Loading ---------- */

async function refreshData() {
    await loadLogs();
}

async function loadLogs(forceFullRender) {
    const container = document.getElementById('logEntries');
    if (!container) return;

    const decision = getChipFilterParam('decision');
    const category = getChipFilterParam('category');
    const hookType = getChipFilterParam('hookType');
    const toolName = getChipFilterParam('toolName');
    const harness = getChipFilterParam('harness');
    const sessionId = document.getElementById('filterSession')?.value || '';
    const limit = document.getElementById('filterLimit')?.value || '100';

    const params = new URLSearchParams();
    if (decision) params.set('decision', decision);
    if (category) params.set('category', category);
    if (hookType) params.set('hookType', hookType);
    if (toolName) params.set('toolName', toolName);
    if (harness) params.set('provider', harness);
    if (sessionId) params.set('sessionId', sessionId);
    params.set('limit', limit);

    try {
        const logs = await fetchApi(`/api/logs?${params}`);

        if (logs.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">\u{1F4CB}</div>
                    <h3>No logs found</h3>
                    <p>No permission events match the current filters. Try adjusting your filters or wait for new events.</p>
                </div>
            `;
            lastLogTimestamp = null;
            lastLogCount = 0;
            return;
        }

        // On first load or forced render, do a full render
        if (forceFullRender || lastLogTimestamp === null || lastLogCount === 0) {
            renderAllLogs(container, logs);
            lastLogTimestamp = logs[0].timestamp;
            lastLogCount = logs.length;
            document.getElementById('logCount').textContent = `${logs.length} entries`;
            autoScrollLogs();
            return;
        }

        // Incremental: find new entries (logs are newest-first, so new ones are at the start)
        var newLogs = [];
        for (var i = 0; i < logs.length; i++) {
            if (logs[i].timestamp === lastLogTimestamp) break;
            // Also stop if we've gone past a reasonable number of new entries
            if (i >= 50) break;
            newLogs.push(logs[i]);
        }

        if (newLogs.length > 0) {
            // Prepend new entries to the DOM
            var existingCount = container.querySelectorAll('.log-entry-detailed').length;
            for (var j = newLogs.length - 1; j >= 0; j--) {
                var idx = existingCount + (newLogs.length - 1 - j);
                var div = document.createElement('div');
                div.innerHTML = buildLogEntryHtml(newLogs[j], idx);
                var child = div.firstElementChild;
                if (child) {
                    container.insertBefore(child, container.firstChild);
                }
            }

            // Re-index all detail panels so toggles still work
            reindexLogEntries(container);

            lastLogTimestamp = logs[0].timestamp;
            lastLogCount = logs.length;
            document.getElementById('logCount').textContent = `${logs.length} entries`;
            autoScrollLogs();
        }
    } catch (error) {
        // Only show error on first load, not on incremental failures
        if (lastLogCount === 0) {
            container.innerHTML = `
                <div class="error-state">
                    <h3>Failed to load logs</h3>
                    <p>${escapeHtml(error.message)}</p>
                    <button class="btn" onclick="loadLogs(true)">Retry</button>
                </div>
            `;
        }
    }
}

/* ---------- Rendering ---------- */

function renderAllLogs(container, logs) {
    container.innerHTML = logs.map(function(log, i) {
        return buildLogEntryHtml(log, i);
    }).join('');
}

function buildLogEntryHtml(log, i) {
    const decisionClass = getDecisionClass(log.decision);
    const toolInputSummary = formatToolInput(log.toolInput);
    const requestPreview = getRequestPreview(log.toolInput);

    return `
        <div class="log-entry-detailed" role="row">
            <div class="log-header" onclick="toggleLogDetail(${i})">
                <span class="log-time" title="${formatTimestamp(log.timestamp)}">${new Date(log.timestamp).toLocaleTimeString(undefined, {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span>
                <span class="log-provider-badge ${log.provider === 'copilot' ? 'provider-copilot' : 'provider-claude'}" title="${log.provider === 'copilot' ? 'Copilot' : 'Claude'}">${log.provider === 'copilot' ? 'CP' : 'CL'}</span>
                <span class="log-type-badge">${escapeHtml(log.type || 'unknown')}</span>
                <span class="log-tool" title="${escapeHtml(log.toolName || '')}">${escapeHtml(log.toolName || 'N/A')}</span>
                <span class="log-request-preview" title="${escapeHtml(requestPreview)}">${escapeHtml(requestPreview)}</span>
                <span class="log-decision ${decisionClass}">${getDecisionLabel(log.decision)}</span>
                <span class="log-score" style="${getScoreColorStyle(log.safetyScore, log.threshold)}">${log.safetyScore != null ? log.safetyScore : '-'}</span>
                <span class="log-session" title="${escapeHtml(log.sessionId || '')}">${escapeHtml((log.sessionId || '').substring(0, 8))}...</span>
                <span class="log-expand">&#9660;</span>
            </div>
            <div class="log-detail" id="log-detail-${i}" style="display:none;">
                ${toolInputSummary ? `
                <div class="detail-section">
                    <div class="detail-label">Request Details</div>
                    <pre class="detail-content">${escapeHtml(toolInputSummary)}</pre>
                </div>` : ''}
                ${log.reasoning ? `
                <div class="detail-section">
                    <div class="detail-label">LLM Reasoning</div>
                    <div class="detail-content">${escapeHtml(log.reasoning)}</div>
                </div>` : ''}
                ${log.responseJson ? `
                <div class="detail-section">
                    <div class="detail-label">Response JSON (returned to ${log.provider === 'copilot' ? 'Copilot' : 'Claude'})</div>
                    <pre class="detail-content" style="font-size:0.85em;">${escapeHtml(log.responseJson)}</pre>
                </div>` : ''}
                <div class="detail-section detail-row">
                    ${log.threshold != null ? `<div><div class="detail-label">Threshold</div><span>${log.threshold}</span></div>` : ''}
                    ${log.safetyScore != null ? `<div><div class="detail-label">Score</div><span style="${getScoreColorStyle(log.safetyScore, log.threshold)}">${log.safetyScore}</span></div>` : ''}
                    ${log.decision ? `<div><div class="detail-label">Decision</div><span class="log-decision ${getDecisionClass(log.decision)}">${getDecisionLabel(log.decision)}</span></div>` : ''}
                    ${log.category ? `<div><div class="detail-label">Category</div><span class="category-badge category-${log.category}">${escapeHtml(log.category)}</span></div>` : ''}
                    ${log.elapsedMs != null ? `<div><div class="detail-label">Latency</div><span>${log.elapsedMs}ms</span></div>` : ''}
                    ${log.handlerName ? `<div><div class="detail-label">Handler</div><span class="handler-name">${escapeHtml(log.handlerName)}</span></div>` : ''}
                    ${log.promptTemplate ? `<div><div class="detail-label">Prompt Template</div><span class="prompt-template">${escapeHtml(log.promptTemplate)}</span></div>` : ''}
                </div>
                ${log.content ? `
                <div class="detail-section">
                    <div class="detail-label">Content</div>
                    <pre class="detail-content">${escapeHtml(log.content)}</pre>
                </div>` : ''}
                <div class="detail-section">
                    <div class="detail-label">Session</div>
                    <a href="/transcripts.html?session=${encodeURIComponent(log.sessionId)}" class="detail-link">${escapeHtml(log.sessionId)}</a>
                </div>
                <div class="detail-section detail-actions">
                    <button class="btn-replay" onclick="replayLogEntry(this)"
                        data-log='${escapeHtml(JSON.stringify({toolName: log.toolName, toolInput: log.toolInput, promptTemplate: log.promptTemplate, sessionId: log.sessionId, hookEventName: log.type, cwd: log.cwd}))}'
                    >Replay to LLM</button>
                    <span class="replay-status"></span>
                </div>
            </div>
        </div>
    `;
}

function reindexLogEntries(container) {
    var entries = container.querySelectorAll('.log-entry-detailed');
    entries.forEach(function(entry, idx) {
        var header = entry.querySelector('.log-header');
        var detail = entry.querySelector('.log-detail');
        if (header) header.setAttribute('onclick', 'toggleLogDetail(' + idx + ')');
        if (detail) detail.id = 'log-detail-' + idx;
    });
}

function toggleLogDetail(idx) {
    const detail = document.getElementById('log-detail-' + idx);
    if (!detail) return;
    const isHidden = detail.style.display === 'none';
    detail.style.display = isHidden ? '' : 'none';
    const header = detail.previousElementSibling;
    const arrow = header?.querySelector('.log-expand');
    if (arrow) arrow.innerHTML = isHidden ? '&#9650;' : '&#9660;';
}

function getRequestPreview(toolInput) {
    if (!toolInput) return '';
    try {
        if (toolInput.command) return toolInput.command.substring(0, 60) + (toolInput.command.length > 60 ? '...' : '');
        if (toolInput.file_path) return toolInput.file_path.substring(0, 60) + (toolInput.file_path.length > 60 ? '...' : '');
        if (toolInput.url) return toolInput.url.substring(0, 60) + (toolInput.url.length > 60 ? '...' : '');
        if (toolInput.prompt) return toolInput.prompt.substring(0, 60) + (toolInput.prompt.length > 60 ? '...' : '');
        if (toolInput.query) return toolInput.query.substring(0, 60) + (toolInput.query.length > 60 ? '...' : '');
        if (toolInput.pattern) return toolInput.pattern.substring(0, 60);
    } catch { }
    return '';
}

function formatToolInput(toolInput) {
    if (!toolInput) return null;
    try {
        if (typeof toolInput === 'string') return toolInput;
        const parts = [];
        if (toolInput.command) parts.push(`Command: ${toolInput.command}`);
        if (toolInput.description) parts.push(`Description: ${toolInput.description}`);
        if (toolInput.file_path) parts.push(`File: ${toolInput.file_path}`);
        if (toolInput.url) parts.push(`URL: ${toolInput.url}`);
        if (toolInput.prompt) parts.push(`Prompt: ${toolInput.prompt}`);
        if (toolInput.pattern) parts.push(`Pattern: ${toolInput.pattern}`);
        if (toolInput.query) parts.push(`Query: ${toolInput.query}`);
        if (toolInput.old_string) parts.push(`Old: ${toolInput.old_string.substring(0, 200)}${toolInput.old_string.length > 200 ? '...' : ''}`);
        if (toolInput.new_string) parts.push(`New: ${toolInput.new_string.substring(0, 200)}${toolInput.new_string.length > 200 ? '...' : ''}`);
        if (toolInput.content && !toolInput.command) {
            const preview = toolInput.content.substring(0, 300);
            parts.push(`Content: ${preview}${toolInput.content.length > 300 ? '...' : ''}`);
        }
        if (parts.length > 0) return parts.join('\n');
        return JSON.stringify(toolInput, null, 2);
    } catch {
        return JSON.stringify(toolInput);
    }
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function exportLogs(format) {
    window.location.href = `/api/logs/export/${format}`;
}

async function clearLogs() {
    if (!confirm('Clear all session logs? This cannot be undone.')) return;
    try {
        var resp = await fetch('/api/logs', { method: 'DELETE' });
        var data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed');
        Toast.show('Logs Cleared', data.message, 'success');
        lastLogTimestamp = null;
        lastLogCount = 0;
        loadLogs(true);
        loadSessionFilter();
    } catch (err) {
        Toast.show('Error', err.message, 'danger');
    }
}

var logsRefreshInterval = null;

function autoScrollLogs() {
    var chk = document.getElementById('chkAutoScrollLogs');
    if (!chk || !chk.checked) return;
    var container = document.getElementById('logEntries');
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
}

function startLogsAutoRefresh() {
    stopLogsAutoRefresh();
    logsRefreshInterval = setInterval(function() {
        loadLogs();
    }, 5000);
}

function stopLogsAutoRefresh() {
    if (logsRefreshInterval) {
        clearInterval(logsRefreshInterval);
        logsRefreshInterval = null;
    }
}

async function loadSessionFilter() {
    var select = document.getElementById('filterSession');
    if (!select) return;
    try {
        var sessions = await fetchApi('/api/dashboard/sessions');
        if (!sessions || sessions.length === 0) return;
        sessions.forEach(function(s) {
            if (!s.sessionId) return;
            var opt = document.createElement('option');
            opt.value = s.sessionId;
            opt.textContent = s.sessionId.substring(0, 12) + '...';
            opt.title = s.sessionId;
            select.appendChild(opt);
        });
        // Restore saved session filter after options are populated
        var savedSession = loadFilter('cpa-logs-filter-session', '');
        if (savedSession) select.value = savedSession;
    } catch { /* non-fatal */ }
}

/* ---------- Initialization ---------- */

document.addEventListener('DOMContentLoaded', async () => {
    // Initialize chip filters (restores from localStorage)
    initChipFilters();

    // Restore remaining dropdown filters
    var limitEl = document.getElementById('filterLimit');
    if (limitEl) {
        var savedLimit = loadFilter('cpa-logs-filter-limit', '');
        if (savedLimit) limitEl.value = savedLimit;
    }

    // Restore checkbox states
    var chkAutoScroll = document.getElementById('chkAutoScrollLogs');
    if (chkAutoScroll) chkAutoScroll.checked = loadFilter('cpa-logs-autoscroll', true);
    var chkAutoRefresh = document.getElementById('chkAutoRefreshLogs');
    if (chkAutoRefresh) chkAutoRefresh.checked = loadFilter('cpa-logs-autorefresh', true);

    // Await session filter population so its saved value is applied before first load
    await loadSessionFilter();
    loadLogs(true);

    // Dropdown filter changes
    document.getElementById('filterSession')?.addEventListener('change', function() { saveFilter('cpa-logs-filter-session', this.value); lastLogTimestamp = null; lastLogCount = 0; loadLogs(true); });
    document.getElementById('filterLimit')?.addEventListener('change', function() { saveFilter('cpa-logs-filter-limit', this.value); lastLogTimestamp = null; lastLogCount = 0; loadLogs(true); });

    if (chkAutoScroll) {
        chkAutoScroll.addEventListener('change', function() { saveFilter('cpa-logs-autoscroll', this.checked); });
    }

    if (chkAutoRefresh) {
        if (chkAutoRefresh.checked) startLogsAutoRefresh();
        chkAutoRefresh.addEventListener('change', function() {
            saveFilter('cpa-logs-autorefresh', this.checked);
            if (this.checked) startLogsAutoRefresh();
            else stopLogsAutoRefresh();
        });
    }
});

async function replayLogEntry(btn) {
    var logData;
    try {
        logData = JSON.parse(btn.dataset.log);
    } catch {
        Toast.show('Error', 'Failed to parse log data', 'danger');
        return;
    }

    var statusEl = btn.nextElementSibling;
    btn.disabled = true;
    btn.textContent = 'Sending...';
    if (statusEl) statusEl.textContent = '';

    // Open terminal panel to show subprocess output
    if (typeof TerminalPanel !== 'undefined') {
        TerminalPanel.open();
    }

    try {
        var response = await fetch('/api/debug/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                toolName: logData.toolName,
                toolInput: logData.toolInput,
                promptTemplate: logData.promptTemplate,
                sessionId: logData.sessionId,
                hookEventName: logData.hookEventName,
                cwd: logData.cwd
            })
        });
        var result = await response.json();

        if (result.success) {
            if (statusEl) {
                statusEl.innerHTML = `<span class="replay-result">Score: <strong>${result.safetyScore}</strong> | Category: <strong>${result.category}</strong> | ${result.elapsedMs}ms</span>`;
            }
            Toast.show('Replay Complete', `Score: ${result.safetyScore} (${result.category}) in ${result.elapsedMs}ms`, 'success');
        } else {
            if (statusEl) {
                statusEl.innerHTML = `<span class="replay-result replay-error">Error: ${escapeHtml(result.error || 'Unknown error')}</span>`;
            }
            Toast.show('Replay Failed', result.error || 'LLM query failed', 'danger');
        }
    } catch (err) {
        if (statusEl) {
            statusEl.innerHTML = `<span class="replay-result replay-error">Error: ${escapeHtml(err.message)}</span>`;
        }
        Toast.show('Replay Error', err.message, 'danger');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Replay to LLM';
    }
}
