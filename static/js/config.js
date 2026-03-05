/* ==========================================================================
   Config Page Logic
   ========================================================================== */

let currentConfig = null;
let isDirty = false;

/* Hook handlers local state - edited independently from the config form fields */
let hookHandlersDirty = false;
let promptTemplateNames = [];

const HOOK_EVENT_TYPES = [
    'PreToolUse',
    'PostToolUse',
    'PostToolUseFailure',
    'UserPromptSubmit',
    'Stop'
];

const HANDLER_MODES = [
    { value: 'llm-analysis', label: 'LLM Analysis' },
    { value: 'log-only', label: 'Log Only' },
    { value: 'context-injection', label: 'Context Injection' },
    { value: 'custom-logic', label: 'Custom Logic' }
];

const HOOK_EVENT_DESCRIPTIONS = {
    'PreToolUse': 'Pre-execution safety gate. Can allow, deny, or ask the user.',
    'PostToolUse': 'Post-execution validation. Can inject additional context.',
    'PostToolUseFailure': 'Handles tool execution failures. Typically log-only.',
    'UserPromptSubmit': 'Fires when a user submits a prompt. Typically log-only.',
    'Stop': 'Fires when a Claude session ends. Used for session cleanup.'
};

// Which harnesses support each hook event
const HOOK_EVENT_HARNESSES = {
    'PreToolUse': ['claude', 'copilot'],
    'PostToolUse': ['claude', 'copilot'],
    'PostToolUseFailure': ['claude'],
    'UserPromptSubmit': ['claude'],
    'PermissionRequest': ['claude'],
    'Stop': ['claude'],
};

function getHarnessIcons(eventType) {
    const harnesses = HOOK_EVENT_HARNESSES[eventType] || ['claude'];
    return harnesses.map(function(h) {
        if (h === 'claude') return '<span class="badge-claude" style="font-size:0.6em;" title="Claude Code">CL</span>';
        if (h === 'copilot') return '<span class="badge-copilot" style="font-size:0.6em;" title="Copilot CLI">CP</span>';
        return '<span style="font-size:0.6em;">' + h + '</span>';
    }).join(' ');
}

const MODE_BADGE_COLORS = {
    'llm-analysis': 'var(--color-info)',
    'log-only': 'var(--text-faint)',
    'context-injection': 'var(--color-warning)',
    'custom-logic': 'var(--color-success)'
};

async function refreshData() {
    await loadConfig();
}

async function loadConfig() {
    const container = document.getElementById('configContent');
    if (!container) return;

    try {
        currentConfig = await fetchApi('/api/config');
        renderConfig(currentConfig);
        isDirty = false;
        updateSaveButton();
        // Also render hook handlers
        await loadPromptTemplates();
        renderHookHandlers();
        hookHandlersDirty = false;
        updateHookHandlersSaveButton();
    } catch (error) {
        container.innerHTML = `
            <div class="error-state">
                <h3>Failed to load configuration</h3>
                <p>${escapeHtml(error.message)}</p>
                <button class="btn" onclick="loadConfig()">Retry</button>
            </div>
        `;
    }
}

async function loadPromptTemplates() {
    try {
        const templates = await fetchApi('/api/prompts');
        if (templates && typeof templates === 'object') {
            promptTemplateNames = Object.keys(templates);
        } else {
            promptTemplateNames = [];
        }
    } catch (e) {
        promptTemplateNames = [];
    }
}

function renderConfig(config) {
    const container = document.getElementById('configContent');
    if (!container) return;

    container.innerHTML = `
        <div class="config-section">
            <h3>Server</h3>
            <div class="config-field">
                <label class="config-label" for="cfg-host">
                    Host
                    <small>The hostname the server listens on</small>
                </label>
                <input id="cfg-host" class="config-input" type="text"
                    value="${escapeAttr(config.server?.host || 'localhost')}"
                    data-path="server.host" aria-label="Server host">
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-port">
                    Port
                    <small>TCP port for the HTTP API</small>
                </label>
                <input id="cfg-port" class="config-input" type="number"
                    value="${config.server?.port || 5050}" min="1024" max="65535"
                    data-path="server.port" aria-label="Server port">
            </div>
        </div>

        <div class="config-section">
            <h3>LLM Provider</h3>
            <div class="config-field">
                <label class="config-label" for="cfg-provider">
                    Provider
                    <small>LLM backend used for analysis</small>
                </label>
                <select id="cfg-provider" class="config-input"
                    data-path="llm.provider" aria-label="LLM provider"
                    onchange="updateProviderFields()">
                    <option value="anthropic-api" ${(config.llm?.provider || 'anthropic-api') === 'anthropic-api' ? 'selected' : ''}>Anthropic API (Direct)</option>
                    <option value="claude-cli" ${config.llm?.provider === 'claude-cli' ? 'selected' : ''}>Claude Code CLI (One-shot)</option>
                    <option value="claude-persistent" ${config.llm?.provider === 'claude-persistent' ? 'selected' : ''}>Claude Code CLI (Persistent)</option>
                    <option value="copilot-cli" ${config.llm?.provider === 'copilot-cli' ? 'selected' : ''}>GitHub Copilot CLI</option>
                    <option value="generic-rest" ${config.llm?.provider === 'generic-rest' ? 'selected' : ''}>Generic REST API</option>
                </select>
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-model">
                    Model
                    <small>Model identifier for the LLM</small>
                </label>
                <input id="cfg-model" class="config-input" type="text"
                    value="${escapeAttr(config.llm?.model || 'sonnet')}"
                    data-path="llm.model" aria-label="LLM model">
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-timeout">
                    Timeout (ms)
                    <small>Maximum wait time for LLM responses</small>
                </label>
                <input id="cfg-timeout" class="config-input" type="number"
                    value="${config.llm?.timeout || 30000}" min="1000" max="300000"
                    data-path="llm.timeout" aria-label="LLM timeout">
            </div>

            <!-- Anthropic API fields -->
            <div id="provider-anthropic-api" class="provider-fields">
                <div class="config-field">
                    <label class="config-label" for="cfg-apikey">
                        API Key
                        <small>Anthropic API key (falls back to ~/.claude/config.json)</small>
                    </label>
                    <input id="cfg-apikey" class="config-input" type="password"
                        value="${escapeAttr(config.llm?.apiKey || '')}"
                        placeholder="(uses Claude config key)"
                        data-path="llm.apiKey" aria-label="API key"
                        autocomplete="off">
                </div>
                <div class="config-field">
                    <label class="config-label" for="cfg-apibaseurl">
                        API Base URL
                        <small>Override for proxies or compatible APIs</small>
                    </label>
                    <input id="cfg-apibaseurl" class="config-input" type="text"
                        value="${escapeAttr(config.llm?.apiBaseUrl || '')}"
                        placeholder="https://api.anthropic.com"
                        data-path="llm.apiBaseUrl" aria-label="API base URL">
                </div>
            </div>

            <!-- CLI provider fields -->
            <div id="provider-cli" class="provider-fields">
                <div class="config-field">
                    <label class="config-label" for="cfg-command">
                        CLI Command
                        <small>Executable name (e.g. "claude", "copilot", "gh")</small>
                    </label>
                    <input id="cfg-command" class="config-input" type="text"
                        value="${escapeAttr(config.llm?.command || '')}"
                        placeholder="auto-detect"
                        data-path="llm.command" aria-label="CLI command">
                </div>
            </div>

            <!-- Generic REST fields -->
            <div id="provider-generic-rest" class="provider-fields">
                <div class="config-field">
                    <label class="config-label" for="cfg-rest-url">
                        REST URL
                        <small>Endpoint URL (e.g. https://api.openai.com/v1/chat/completions)</small>
                    </label>
                    <input id="cfg-rest-url" class="config-input" type="text"
                        value="${escapeAttr(config.llm?.genericRest?.url || '')}"
                        placeholder="https://api.openai.com/v1/chat/completions"
                        data-path="llm.genericRest.url" aria-label="REST URL"
                        style="width: 350px;">
                </div>
                <div class="config-field">
                    <label class="config-label" for="cfg-rest-headers">
                        Headers (JSON)
                        <small>e.g. {"Authorization": "Bearer sk-..."}</small>
                    </label>
                    <textarea id="cfg-rest-headers" class="config-input" rows="3"
                        placeholder='{"Authorization": "Bearer sk-..."}'
                        data-path="llm.genericRest.headers" aria-label="REST headers"
                        style="width: 350px; font-family: var(--font-mono); font-size: 12px;">${escapeHtml(JSON.stringify(config.llm?.genericRest?.headers || {}, null, 2))}</textarea>
                </div>
                <div class="config-field">
                    <label class="config-label" for="cfg-rest-body">
                        Body Template
                        <small>JSON with {PROMPT} placeholder</small>
                    </label>
                    <textarea id="cfg-rest-body" class="config-input" rows="5"
                        placeholder='{"model":"gpt-4","messages":[{"role":"user","content":"{PROMPT}"}]}'
                        data-path="llm.genericRest.bodyTemplate" aria-label="REST body template"
                        style="width: 350px; font-family: var(--font-mono); font-size: 12px;">${escapeHtml(config.llm?.genericRest?.bodyTemplate || '')}</textarea>
                </div>
                <div class="config-field">
                    <label class="config-label" for="cfg-rest-path">
                        Response Path
                        <small>Dot-notation to extract text (e.g. choices[0].message.content)</small>
                    </label>
                    <input id="cfg-rest-path" class="config-input" type="text"
                        value="${escapeAttr(config.llm?.genericRest?.responsePath || '')}"
                        placeholder="choices[0].message.content"
                        data-path="llm.genericRest.responsePath" aria-label="Response path">
                </div>
            </div>

            <div class="config-field" style="margin-top: 16px; border-top: 1px solid var(--border-color); padding-top: 16px;">
                <label class="config-label" for="cfg-system-prompt">
                    System Prompt
                    <small>System prompt sent to the LLM for safety analysis</small>
                </label>
                <textarea id="cfg-system-prompt" class="config-input" rows="4"
                    data-path="llm.systemPrompt" aria-label="System prompt"
                    style="width: 350px; font-family: var(--font-mono); font-size: 12px;">${escapeHtml(config.llm?.systemPrompt || '')}</textarea>
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-prompt-prefix">
                    Prompt Prefix
                    <small>Text prepended before each hook analysis prompt</small>
                </label>
                <textarea id="cfg-prompt-prefix" class="config-input" rows="2"
                    data-path="llm.promptPrefix" aria-label="Prompt prefix"
                    style="width: 350px; font-family: var(--font-mono); font-size: 12px;">${escapeHtml(config.llm?.promptPrefix || '')}</textarea>
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-prompt-suffix">
                    Prompt Suffix
                    <small>Text appended after each hook analysis prompt</small>
                </label>
                <textarea id="cfg-prompt-suffix" class="config-input" rows="2"
                    data-path="llm.promptSuffix" aria-label="Prompt suffix"
                    style="width: 350px; font-family: var(--font-mono); font-size: 12px;">${escapeHtml(config.llm?.promptSuffix || '')}</textarea>
            </div>
        </div>

        <div class="config-section">
            <h3>Enforcement</h3>
            <div class="config-field">
                <label class="config-label" for="cfg-enforcement-mode">
                    Enforcement Mode
                    <small>How the service handles hook events</small>
                </label>
                <select id="cfg-enforcement-mode" class="config-input"
                    data-path="enforcementMode" aria-label="Enforcement mode">
                    <option value="observe" ${(config.enforcementMode || 'observe') === 'observe' ? 'selected' : ''}>Observe (log only, no decisions)</option>
                    <option value="approve-only" ${config.enforcementMode === 'approve-only' ? 'selected' : ''}>Approve-Only (auto-approve safe, never deny)</option>
                    <option value="enforce" ${config.enforcementMode === 'enforce' ? 'selected' : ''}>Enforce (approve or deny based on analysis)</option>
                </select>
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-analyze-observe">
                    Analyze in Observe Mode
                    <small>Run LLM analysis even in observe mode (shows scores in logs)</small>
                </label>
                <select id="cfg-analyze-observe" class="config-input"
                    data-path="analyzeInObserveMode" data-type="bool" aria-label="Analyze in observe mode">
                    <option value="true" ${config.analyzeInObserveMode !== false ? 'selected' : ''}>Yes</option>
                    <option value="false" ${config.analyzeInObserveMode === false ? 'selected' : ''}>No</option>
                </select>
            </div>
        </div>

        <div class="config-section">
            <h3>Copilot Integration</h3>
            <div class="config-field">
                <label class="config-label" for="cfg-copilot-enabled">
                    Copilot Enabled
                    <small>Enable hook processing for GitHub Copilot CLI events</small>
                </label>
                <select id="cfg-copilot-enabled" class="config-input"
                    data-path="copilot.enabled" data-type="bool" aria-label="Copilot enabled">
                    <option value="true" ${config.copilot?.enabled !== false ? 'selected' : ''}>Enabled</option>
                    <option value="false" ${config.copilot?.enabled === false ? 'selected' : ''}>Disabled</option>
                </select>
            </div>
        </div>

        <div class="config-section">
            <h3>Security</h3>
            <div class="config-field">
                <label class="config-label" for="cfg-security-apikey">
                    API Key
                    <small>Require X-Api-Key header for all API requests (leave empty to disable)</small>
                </label>
                <input id="cfg-security-apikey" class="config-input" type="password"
                    value="${escapeAttr(config.security?.apiKey || '')}"
                    placeholder="(no API key required)"
                    data-path="security.apiKey" aria-label="Security API key"
                    autocomplete="off">
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-security-ratelimit">
                    Rate Limit (req/min)
                    <small>Maximum requests per minute per IP</small>
                </label>
                <input id="cfg-security-ratelimit" class="config-input" type="number"
                    value="${config.security?.rateLimitPerMinute || 600}" min="10" max="10000"
                    data-path="security.rateLimitPerMinute" aria-label="Rate limit per minute">
            </div>
        </div>

        <div class="config-section">
            <h3>Profiles</h3>
            <div class="config-field">
                <label class="config-label" for="cfg-active-profile">
                    Active Profile
                    <small>Permission profile controlling safety thresholds</small>
                </label>
                <input id="cfg-active-profile" class="config-input" type="text"
                    value="${escapeAttr(config.profiles?.activeProfile || 'moderate')}"
                    data-path="profiles.activeProfile" aria-label="Active profile">
            </div>
        </div>

        <div class="config-section">
            <h3>Session</h3>
            <div class="config-field">
                <label class="config-label" for="cfg-maxhistory">
                    Max History Per Session
                    <small>Number of events to retain per session</small>
                </label>
                <input id="cfg-maxhistory" class="config-input" type="number"
                    value="${config.session?.maxHistoryPerSession || 50}" min="1" max="1000"
                    data-path="session.maxHistoryPerSession" aria-label="Max history per session">
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-storagedir">
                    Storage Directory
                    <small>File path for session storage</small>
                </label>
                <input id="cfg-storagedir" class="config-input" type="text"
                    value="${escapeAttr(config.session?.storageDir || '')}"
                    data-path="session.storageDir" aria-label="Storage directory"
                    style="width: 300px;">
            </div>
        </div>

        <div class="config-section">
            <h3>System Tray &amp; Notifications</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
                Native OS notifications. Approved actions are always silent. Score &le; 0 shows an informational denial alert (no buttons).
                Uncertain scores (0 &lt; score &lt; threshold) show interactive Approve/Deny toast. Enforce mode never shows tray.
            </p>
            <div class="config-field">
                <label class="config-label" for="cfg-tray-enabled">
                    Tray Icon
                    <small>Master switch for the system tray icon</small>
                </label>
                <select id="cfg-tray-enabled" class="config-input"
                    data-path="tray.enabled" data-type="bool" aria-label="Tray enabled">
                    <option value="true" ${config.tray?.enabled !== false ? 'selected' : ''}>Enabled</option>
                    <option value="false" ${config.tray?.enabled === false ? 'selected' : ''}>Disabled</option>
                </select>
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-tray-showInObserve">
                    Notifications in Observe Mode
                    <small>Show tray alerts in observe mode (only when LLM analysis is enabled)</small>
                </label>
                <select id="cfg-tray-showInObserve" class="config-input"
                    data-path="tray.showInObserve" data-type="bool" aria-label="Show in observe">
                    <option value="false" ${config.tray?.showInObserve !== true ? 'selected' : ''}>Off</option>
                    <option value="true" ${config.tray?.showInObserve === true ? 'selected' : ''}>On</option>
                </select>
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-tray-showInApproveOnly">
                    Notifications in Approve-Only Mode
                    <small>Show interactive approve/deny toasts for uncertain scores</small>
                </label>
                <select id="cfg-tray-showInApproveOnly" class="config-input"
                    data-path="tray.showInApproveOnly" data-type="bool" aria-label="Show in approve-only">
                    <option value="true" ${config.tray?.showInApproveOnly !== false ? 'selected' : ''}>On</option>
                    <option value="false" ${config.tray?.showInApproveOnly === false ? 'selected' : ''}>Off</option>
                </select>
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-tray-interactiveTimeout">
                    Interactive Timeout (seconds)
                    <small>How long to wait for user response before falling through</small>
                </label>
                <input id="cfg-tray-interactiveTimeout" class="config-input" type="number"
                    value="${config.tray?.interactiveTimeoutSeconds || 10}" min="5" max="30"
                    data-path="tray.interactiveTimeoutSeconds" aria-label="Interactive timeout">
            </div>
            <div class="config-field">
                <label class="config-label" for="cfg-tray-sound">
                    Notification Sound
                    <small>Play a sound when tray notifications appear</small>
                </label>
                <select id="cfg-tray-sound" class="config-input"
                    data-path="tray.sound" data-type="bool" aria-label="Notification sound">
                    <option value="false" ${config.tray?.sound !== true ? 'selected' : ''}>Off</option>
                    <option value="true" ${config.tray?.sound === true ? 'selected' : ''}>On</option>
                </select>
            </div>
        </div>

        <div class="config-section">
            <h3>Triggers (Webhooks)</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
                Fire HTTP webhooks on hook events. Configure trigger rules in the JSON config file.
            </p>
            <div class="config-field">
                <label class="config-label" for="cfg-triggers-enabled">
                    Triggers Enabled
                    <small>Master switch for webhook triggers</small>
                </label>
                <select id="cfg-triggers-enabled" class="config-input"
                    data-path="triggers.enabled" data-type="bool" aria-label="Triggers enabled">
                    <option value="true" ${config.triggers?.enabled ? 'selected' : ''}>Enabled</option>
                    <option value="false" ${!config.triggers?.enabled ? 'selected' : ''}>Disabled</option>
                </select>
            </div>
        </div>

        <div class="config-actions">
            <button class="btn" onclick="loadConfig()">Reset</button>
            <button class="btn btn-primary" id="saveConfigBtn" onclick="saveConfig()" disabled>Save Changes</button>
        </div>
    `;

    // Add change listeners (use both 'input' and 'change' for <select> compatibility)
    container.querySelectorAll('.config-input').forEach(input => {
        const eventType = input.tagName === 'SELECT' ? 'change' : 'input';
        input.addEventListener(eventType, () => {
            isDirty = true;
            updateSaveButton();
        });
    });

    // Show/hide provider-specific fields
    updateProviderFields();
}

function updateProviderFields() {
    const provider = document.getElementById('cfg-provider')?.value || 'anthropic-api';

    const apiFields = document.getElementById('provider-anthropic-api');
    const cliFields = document.getElementById('provider-cli');
    const restFields = document.getElementById('provider-generic-rest');

    if (apiFields) apiFields.style.display = provider === 'anthropic-api' ? 'block' : 'none';
    if (cliFields) cliFields.style.display = ['claude-cli', 'claude-persistent', 'copilot-cli'].includes(provider) ? 'block' : 'none';
    if (restFields) restFields.style.display = provider === 'generic-rest' ? 'block' : 'none';
}

function updateSaveButton() {
    const btn = document.getElementById('saveConfigBtn');
    if (btn) {
        btn.disabled = !isDirty;
    }
}

function updateHookHandlersSaveButton() {
    const btn = document.getElementById('saveHookHandlersBtn');
    const indicator = document.getElementById('hookHandlersDirtyIndicator');
    if (btn) {
        btn.disabled = !hookHandlersDirty;
    }
    if (indicator) {
        indicator.style.display = hookHandlersDirty ? 'inline' : 'none';
    }
}

function markHookHandlersDirty() {
    hookHandlersDirty = true;
    updateHookHandlersSaveButton();
}

async function saveConfig() {
    if (!currentConfig || !isDirty) return;

    const inputs = document.querySelectorAll('.config-input');
    const updated = JSON.parse(JSON.stringify(currentConfig));

    inputs.forEach(input => {
        const path = input.dataset.path;
        if (!path) return;

        // Skip hidden provider fields to avoid overwriting config with empty values
        const providerSection = input.closest('.provider-fields');
        if (providerSection && providerSection.style.display === 'none') return;

        const parts = path.split('.');
        let obj = updated;
        for (let i = 0; i < parts.length - 1; i++) {
            if (!obj[parts[i]]) obj[parts[i]] = {};
            obj = obj[parts[i]];
        }

        const key = parts[parts.length - 1];
        if (input.dataset.type === 'bool') {
            obj[key] = input.value === 'true';
        } else if (input.type === 'number') {
            obj[key] = parseInt(input.value, 10);
        } else if (key === 'headers' && input.tagName === 'TEXTAREA') {
            // Parse JSON for headers field
            try {
                obj[key] = JSON.parse(input.value || '{}');
            } catch {
                obj[key] = {};
            }
        } else {
            // Store empty strings as null for optional fields
            obj[key] = input.value || null;
        }
    });

    // Sync enforcementEnabled bool with enforcementMode
    if (updated.enforcementMode) {
        updated.enforcementEnabled = updated.enforcementMode === 'enforce' || updated.enforcementMode === 'approve-only';
    }

    const btn = document.getElementById('saveConfigBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Saving...';
    }

    try {
        await fetch('/api/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updated)
        });

        currentConfig = updated;
        isDirty = false;
        Toast.show('Configuration Saved', 'Changes have been saved successfully. Some changes may require a restart.', 'success');
    } catch (error) {
        Toast.show('Save Failed', error.message, 'danger');
    } finally {
        if (btn) {
            btn.textContent = 'Save Changes';
            updateSaveButton();
        }
    }
}

/* ==========================================================================
   Hook Handlers UI
   ========================================================================== */

function getHookHandlers() {
    if (!currentConfig) return {};
    return currentConfig.hookHandlers || {};
}

function ensureHookEventConfig(eventType) {
    if (!currentConfig.hookHandlers) {
        currentConfig.hookHandlers = {};
    }
    if (!currentConfig.hookHandlers[eventType]) {
        currentConfig.hookHandlers[eventType] = { enabled: true, handlers: [] };
    }
    return currentConfig.hookHandlers[eventType];
}

function getAllHookEventTypes() {
    // Merge predefined types with any custom ones from config
    const fromConfig = Object.keys(getHookHandlers());
    const all = new Set(HOOK_EVENT_TYPES);
    fromConfig.forEach(function(k) { all.add(k); });
    return Array.from(all);
}

function addHookEventType() {
    const input = document.getElementById('newHookEventInput');
    if (!input) return;
    const name = input.value.trim();
    if (!name) return;
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(name)) {
        Toast.show('Invalid Name', 'Hook event name must be alphanumeric (e.g. PreToolUse)', 'warning');
        return;
    }
    const hookHandlers = getHookHandlers();
    if (hookHandlers[name]) {
        Toast.show('Already Exists', 'Hook event "' + name + '" already exists', 'warning');
        return;
    }
    ensureHookEventConfig(name);
    markHookHandlersDirty();
    renderHookHandlers();
    input.value = '';
}

function removeHookEventType(eventType) {
    if (!currentConfig || !currentConfig.hookHandlers) return;
    delete currentConfig.hookHandlers[eventType];
    markHookHandlersDirty();
    renderHookHandlers();
}

function renderHookHandlers() {
    const container = document.getElementById('hookHandlersContent');
    if (!container || !currentConfig) return;

    const hookHandlers = getHookHandlers();
    const allEventTypes = getAllHookEventTypes();

    let html = '<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;">' +
        '<input type="text" id="newHookEventInput" placeholder="New hook event name (e.g. PermissionRequest)" ' +
        'style="flex:1;padding:4px 8px;font-size:0.85em;border:1px solid var(--border-color,#ddd);border-radius:4px;background:var(--bg-secondary,#fff);color:var(--text-primary,#1a1a2e);">' +
        '<button class="btn btn-sm" onclick="addHookEventType()" style="font-size:11px;white-space:nowrap;">+ Add Hook Event</button>' +
        '</div>';

    for (const eventType of allEventTypes) {
        const eventConfig = hookHandlers[eventType] || { enabled: true, handlers: [] };
        const handlers = eventConfig.handlers || [];
        const enabled = eventConfig.enabled !== false;
        const description = HOOK_EVENT_DESCRIPTIONS[eventType] || '';
        const isCustom = !HOOK_EVENT_TYPES.includes(eventType);

        html += `
        <div class="hook-event-card" data-event="${escapeAttr(eventType)}">
            <div class="hook-event-header">
                <div class="hook-event-title">
                    <h4>${escapeHtml(eventType)} ${getHarnessIcons(eventType)}${isCustom ? ' <span style="font-size:0.65em;font-weight:400;color:var(--text-muted);">(custom)</span>' : ''}</h4>
                    <label class="hook-event-toggle">
                        <input type="checkbox" ${enabled ? 'checked' : ''}
                            onchange="toggleHookEvent('${escapeAttr(eventType)}', this.checked)"
                            style="cursor: pointer;">
                        Enabled
                    </label>
                </div>
                <div style="display:flex;gap:4px;">
                    <button class="btn btn-sm" onclick="addHandler('${escapeAttr(eventType)}')" style="font-size: 11px;">+ Add Handler</button>
                    <button class="btn btn-sm" onclick="removeHookEventType('${escapeAttr(eventType)}')" style="font-size: 11px; color: var(--color-danger); border-color: var(--color-danger);" title="Remove this hook event">Remove</button>
                </div>
            </div>
            ${description ? `<p class="hook-event-desc">${escapeHtml(description)}</p>` : ''}
            <div id="handlers-${escapeAttr(eventType)}">
                ${handlers.length === 0
                    ? '<p class="hook-empty-msg">No handlers configured. Click "+ Add Handler" to create one.</p>'
                    : handlers.map((h, idx) => renderHandlerRow(eventType, h, idx, false)).join('')
                }
            </div>
        </div>`;
    }

    container.innerHTML = html;
}

function toggleHandlerEnabled(eventType, index) {
    const eventConfig = (currentConfig.hookHandlers || {})[eventType];
    if (!eventConfig || !eventConfig.handlers || !eventConfig.handlers[index]) return;
    eventConfig.handlers[index].enabled = !eventConfig.handlers[index].enabled;
    markHookHandlersDirty();
    renderEventHandlers(eventType);
}

function renderHandlerRow(eventType, handler, index, editing) {
    if (editing) {
        return renderHandlerEditRow(eventType, handler, index);
    }

    const safeEvent = escapeAttr(eventType);
    const rowId = `handler-${safeEvent}-${index}`;
    const badgeColor = MODE_BADGE_COLORS[handler.mode] || 'var(--text-faint)';
    const promptFile = handler.promptTemplate ? handler.promptTemplate.replace(/^.*[\\\/]/, '') : '';
    const isDisabled = handler.enabled === false;
    const disabledStyle = isDisabled ? 'opacity: 0.45;' : '';
    const disabledBadge = isDisabled ? '<span style="font-size:0.7em;font-weight:600;color:var(--text-muted);background:var(--bg-tertiary,#e5e7eb);padding:1px 5px;border-radius:3px;margin-left:4px;">DISABLED</span>' : '';

    return `
    <div id="${rowId}" class="handler-row" style="${disabledStyle}">
        <div class="handler-row-details">
            <label style="cursor:pointer;display:inline-flex;align-items:center;margin-right:6px;" title="${isDisabled ? 'Enable' : 'Disable'} this handler">
                <input type="checkbox" ${isDisabled ? '' : 'checked'} onchange="toggleHandlerEnabled('${safeEvent}', ${index})" onclick="event.stopPropagation()" style="cursor:pointer;">
            </label>
            <span class="handler-name" title="Handler name">${escapeHtml(handler.name || '(unnamed)')}</span>${disabledBadge}
            <span class="handler-mode-badge" style="background: ${badgeColor};" title="Mode">${escapeHtml(handler.mode || 'log-only')}</span>
            <span class="handler-client-badge" title="Client: ${handler.client || 'all'}">${handler.client ? escapeHtml(handler.client) : 'all'}</span>
            <code class="handler-matcher" title="Matcher pattern: ${escapeAttr(handler.matcher || '*')}">${escapeHtml(handler.matcher || '*')}</code>
            <span class="handler-thresholds" title="Thresholds: Strict / Moderate / Permissive">S:<strong>${handler.thresholdStrict || 95}</strong> M:<strong>${handler.thresholdModerate || 85}</strong> P:<strong>${handler.thresholdPermissive || 70}</strong></span>
            ${handler.autoApprove ? '<span class="handler-auto-approve" title="Auto-approve enabled">Auto-approve</span>' : ''}
            ${promptFile ? `<span class="handler-prompt-label" title="Prompt: ${escapeAttr(handler.promptTemplate)}">Prompt: ${escapeHtml(promptFile)}</span>` : ''}
        </div>
        <div class="handler-actions">
            <button class="btn btn-sm" onclick="editHandler('${safeEvent}', ${index})" style="font-size: 11px; padding: 2px 8px;">Edit</button>
            <button class="btn btn-sm" onclick="removeHandler('${safeEvent}', ${index})" style="font-size: 11px; padding: 2px 8px; color: var(--color-danger); border-color: var(--color-danger);">Remove</button>
        </div>
    </div>`;
}

function renderHandlerEditRow(eventType, handler, index) {
    const safeEvent = escapeAttr(eventType);
    const rowId = `handler-${safeEvent}-${index}`;

    // Match by filename - handler.promptTemplate may be a full path
    const currentPromptFile = handler.promptTemplate ? handler.promptTemplate.replace(/^.*[\\\/]/, '') : '';
    const promptOptions = promptTemplateNames.map(name =>
        `<option value="${escapeAttr(name)}" ${currentPromptFile === name ? 'selected' : ''}>${escapeHtml(name)}</option>`
    ).join('');

    const modeOptions = HANDLER_MODES.map(m =>
        `<option value="${escapeAttr(m.value)}" ${handler.mode === m.value ? 'selected' : ''}>${escapeHtml(m.label)}</option>`
    ).join('');

    return `
    <div id="${rowId}" class="handler-edit-card">
        <div class="handler-edit-grid">
            <div>
                <label class="handler-edit-label">Name</label>
                <input type="text" id="${rowId}-name" value="${escapeAttr(handler.name || '')}"
                    placeholder="e.g. bash-analyzer"
                    class="handler-edit-input handler-edit-input-mono">
            </div>
            <div>
                <label class="handler-edit-label">Matcher Pattern (regex)</label>
                <input type="text" id="${rowId}-matcher" value="${escapeAttr(handler.matcher || '')}"
                    placeholder="e.g. Bash|Write or *"
                    class="handler-edit-input handler-edit-input-mono">
            </div>
            <div>
                <label class="handler-edit-label">Client</label>
                <select id="${rowId}-client" class="handler-edit-input">
                    <option value="" ${!handler.client ? 'selected' : ''}>All Clients</option>
                    <option value="claude" ${handler.client === 'claude' ? 'selected' : ''}>Claude</option>
                    <option value="copilot" ${handler.client === 'copilot' ? 'selected' : ''}>Copilot</option>
                </select>
            </div>
            <div>
                <label class="handler-edit-label">Mode</label>
                <select id="${rowId}-mode" class="handler-edit-input">
                    ${modeOptions}
                </select>
            </div>
            <div>
                <label class="handler-edit-label">Prompt Template</label>
                <select id="${rowId}-prompt" class="handler-edit-input">
                    <option value="">(none)</option>
                    ${promptOptions}
                </select>
            </div>
            <div>
                <label class="handler-edit-label">Strict Threshold</label>
                <input type="number" id="${rowId}-thresholdStrict" value="${handler.thresholdStrict != null ? handler.thresholdStrict : 95}"
                    min="0" max="100" class="handler-edit-input handler-edit-input-mono">
            </div>
            <div>
                <label class="handler-edit-label">Moderate Threshold</label>
                <input type="number" id="${rowId}-thresholdModerate" value="${handler.thresholdModerate != null ? handler.thresholdModerate : 85}"
                    min="0" max="100" class="handler-edit-input handler-edit-input-mono">
            </div>
            <div>
                <label class="handler-edit-label">Permissive Threshold</label>
                <input type="number" id="${rowId}-thresholdPermissive" value="${handler.thresholdPermissive != null ? handler.thresholdPermissive : 70}"
                    min="0" max="100" class="handler-edit-input handler-edit-input-mono">
            </div>
            <div class="handler-edit-checkbox">
                <label>
                    <input type="checkbox" id="${rowId}-enabled" ${handler.enabled !== false ? 'checked' : ''}
                        style="cursor: pointer;">
                    Enabled
                </label>
            </div>
            <div class="handler-edit-checkbox">
                <label>
                    <input type="checkbox" id="${rowId}-autoapprove" ${handler.autoApprove ? 'checked' : ''}
                        style="cursor: pointer;">
                    Auto-approve when safe
                </label>
            </div>
        </div>
        <div class="handler-edit-actions">
            <button class="btn btn-sm" onclick="cancelEditHandler('${safeEvent}', ${index})" style="font-size: 11px; padding: 3px 10px;">Cancel</button>
            <button class="btn btn-sm btn-primary" onclick="applyEditHandler('${safeEvent}', ${index})" style="font-size: 11px; padding: 3px 10px;">Apply</button>
        </div>
    </div>`;
}

function toggleHookEvent(eventType, enabled) {
    const eventConfig = ensureHookEventConfig(eventType);
    eventConfig.enabled = enabled;
    markHookHandlersDirty();
}

function addHandler(eventType) {
    const eventConfig = ensureHookEventConfig(eventType);
    const newHandler = {
        name: '',
        enabled: true,
        matcher: '*',
        client: null,
        mode: 'log-only',
        promptTemplate: '',
        threshold: 85,
        autoApprove: false
    };
    eventConfig.handlers.push(newHandler);
    markHookHandlersDirty();

    // Re-render the handlers list for this event, with the new one in edit mode
    const handlersContainer = document.getElementById(`handlers-${eventType}`);
    if (handlersContainer) {
        const handlers = eventConfig.handlers;
        handlersContainer.innerHTML = handlers.map((h, idx) => {
            if (idx === handlers.length - 1) {
                return renderHandlerRow(eventType, h, idx, true);
            }
            return renderHandlerRow(eventType, h, idx, false);
        }).join('');
    }
}

function removeHandler(eventType, index) {
    const eventConfig = ensureHookEventConfig(eventType);
    if (index >= 0 && index < eventConfig.handlers.length) {
        const name = eventConfig.handlers[index].name || '(unnamed)';
        if (!confirm(`Remove handler "${name}" from ${eventType}?`)) return;
        eventConfig.handlers.splice(index, 1);
        markHookHandlersDirty();
        renderEventHandlers(eventType);
    }
}

function editHandler(eventType, index) {
    const eventConfig = ensureHookEventConfig(eventType);
    const handler = eventConfig.handlers[index];
    if (!handler) return;

    const handlersContainer = document.getElementById(`handlers-${eventType}`);
    if (handlersContainer) {
        const handlers = eventConfig.handlers;
        handlersContainer.innerHTML = handlers.map((h, idx) => {
            return renderHandlerRow(eventType, h, idx, idx === index);
        }).join('');
    }
}

function cancelEditHandler(eventType, index) {
    renderEventHandlers(eventType);
}

function applyEditHandler(eventType, index) {
    const safeEvent = escapeAttr(eventType);
    const rowId = `handler-${safeEvent}-${index}`;

    const nameEl = document.getElementById(`${rowId}-name`);
    const matcherEl = document.getElementById(`${rowId}-matcher`);
    const clientEl = document.getElementById(`${rowId}-client`);
    const modeEl = document.getElementById(`${rowId}-mode`);
    const promptEl = document.getElementById(`${rowId}-prompt`);
    const thresholdStrictEl = document.getElementById(`${rowId}-thresholdStrict`);
    const thresholdModerateEl = document.getElementById(`${rowId}-thresholdModerate`);
    const thresholdPermissiveEl = document.getElementById(`${rowId}-thresholdPermissive`);
    const enabledEl = document.getElementById(`${rowId}-enabled`);
    const autoApproveEl = document.getElementById(`${rowId}-autoapprove`);

    if (!nameEl) return;

    const eventConfig = ensureHookEventConfig(eventType);
    const handler = eventConfig.handlers[index];
    if (!handler) return;

    handler.name = nameEl.value.trim();
    handler.enabled = enabledEl ? enabledEl.checked : true;
    handler.matcher = matcherEl.value.trim() || '*';
    handler.client = clientEl.value || null;
    handler.mode = modeEl.value;
    handler.promptTemplate = promptEl.value || null;
    handler.thresholdStrict = parseInt(thresholdStrictEl?.value, 10) || 95;
    handler.thresholdModerate = parseInt(thresholdModerateEl?.value, 10) || 85;
    handler.thresholdPermissive = parseInt(thresholdPermissiveEl?.value, 10) || 70;
    handler.threshold = handler.thresholdModerate; // Default threshold = moderate
    handler.autoApprove = autoApproveEl.checked;

    markHookHandlersDirty();
    renderEventHandlers(eventType);
}

function renderEventHandlers(eventType) {
    const handlersContainer = document.getElementById(`handlers-${eventType}`);
    if (!handlersContainer) return;

    const eventConfig = (currentConfig.hookHandlers || {})[eventType] || { enabled: true, handlers: [] };
    const handlers = eventConfig.handlers || [];

    if (handlers.length === 0) {
        handlersContainer.innerHTML = '<p class="hook-empty-msg">No handlers configured. Click "+ Add Handler" to create one.</p>';
    } else {
        handlersContainer.innerHTML = handlers.map((h, idx) => renderHandlerRow(eventType, h, idx, false)).join('');
    }
}

async function saveHookHandlers() {
    if (!currentConfig || !hookHandlersDirty) return;

    const btn = document.getElementById('saveHookHandlersBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Saving...';
    }

    try {
        // Build a full config to PUT, merging current config with hook handler changes
        const updated = JSON.parse(JSON.stringify(currentConfig));

        // Clean up empty prompt templates (convert null/empty to undefined so JSON omits them)
        if (updated.hookHandlers) {
            for (const eventType of Object.keys(updated.hookHandlers)) {
                const ec = updated.hookHandlers[eventType];
                if (ec && ec.handlers) {
                    ec.handlers.forEach(h => {
                        if (!h.promptTemplate) {
                            delete h.promptTemplate;
                        }
                        if (h.config && Object.keys(h.config).length === 0) {
                            delete h.config;
                        }
                    });
                }
            }
        }

        await fetch('/api/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updated)
        });

        currentConfig = updated;
        hookHandlersDirty = false;
        updateHookHandlersSaveButton();

        // Auto-sync: reinstall hooks in Claude's settings.json so they match the updated config
        try {
            var hooksStatus = await (await fetch('/api/hooks/status')).json();
            if (hooksStatus.installed) {
                await fetch('/api/hooks/install', { method: 'POST' });
                Toast.show('Hook Handlers Saved', 'Configuration saved and hooks updated.', 'success');
            } else {
                Toast.show('Hook Handlers Saved', 'Configuration saved. Install hooks from Dashboard to activate.', 'success');
            }
        } catch {
            Toast.show('Hook Handlers Saved', 'Configuration saved (hooks sync skipped).', 'success');
        }
    } catch (error) {
        Toast.show('Save Failed', error.message, 'danger');
    } finally {
        if (btn) {
            btn.textContent = 'Save Handlers';
            updateHookHandlersSaveButton();
        }
    }
}

/* ==========================================================================
   Utilities
   ========================================================================== */

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

document.addEventListener('DOMContentLoaded', loadConfig);
