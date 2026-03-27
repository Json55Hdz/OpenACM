/* ═══════════════════════════════════════════════════════════
   OpenACM Dashboard — Main Application JavaScript
   ═══════════════════════════════════════════════════════════ */

// ─── State ──────────────────────────────────────────────────
let chatWs = null;
let eventsWs = null;
let activityChart = null;
let isWaitingResponse = false;
let currentTarget = { targetUser: 'web', targetChannel: 'web' };
let currentAttachments = [];
let _authToken = localStorage.getItem('openacm_token') || '';

// ─── Auth Gate ──────────────────────────────────────────────
async function checkAuth() {
    if (!_authToken) return false;
    try {
        const resp = await fetch('/api/auth/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: _authToken }),
        });
        return resp.ok;
    } catch {
        return false;
    }
}

document.getElementById('auth-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = document.getElementById('auth-token-input');
    const errorEl = document.getElementById('auth-error');
    const token = input.value.trim();
    if (!token) return;
    
    // Test it
    try {
        const resp = await fetch('/api/auth/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token }),
        });
        if (resp.ok) {
            _authToken = token;
            localStorage.setItem('openacm_token', token);
            document.getElementById('auth-overlay')?.classList.remove('active');
            bootApp();
        } else {
            errorEl.style.display = 'block';
            input.style.borderColor = '#ef4444';
        }
    } catch {
        errorEl.style.display = 'block';
    }
});

// ─── DOM Ready ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    const authed = await checkAuth();
    if (authed) {
        document.getElementById('auth-overlay')?.classList.remove('active');
        bootApp();
    }
    // else: auth modal stays visible
});

async function bootApp() {
    initNavigation();
    initChat();
    initWebSockets();
    initSkills();
    initConfigToggles();
    
    // Check onboarding
    const isSetupNeeded = await checkOnboarding();
    if (!isSetupNeeded) {
        loadDashboard();
        loadConfig();
        loadTools();
        setInterval(loadDashboard, 15000);
    }
}

// ─── Onboarding ─────────────────────────────────────────────
async function checkOnboarding() {
    try {
        const status = await fetchAPI('/api/config/status');
        if (status && status.needs_setup) {
            const overlay = document.getElementById('onboarding-overlay');
            overlay.classList.add('active');
            
            if (status.provider) {
                document.getElementById('onboarding-provider').value = status.provider;
                document.getElementById('ob-group-llm').querySelector('label').innerHTML = `<span id="ob-llm-icon">🧠</span> API Key para ${status.provider} <span class="optional-tag" style="background:#ef444433;color:#ef4444">Requerido</span>`;
            }
            
            document.getElementById('onboarding-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                const llmKeyId = document.getElementById('onboarding-provider').value ? `${document.getElementById('onboarding-provider').value.toUpperCase()}_API_KEY` : 'API_KEY';
                const llmVal = document.getElementById('ob-llm-key').value;
                const tgVal = document.getElementById('ob-telegram-key').value;
                
                const payload = {};
                if (llmVal) payload[llmKeyId] = llmVal;
                if (tgVal) payload['TELEGRAM_BOT_TOKEN'] = tgVal;
                
                const btn = e.target.querySelector('button');
                const oldText = btn.textContent;
                btn.textContent = 'Conectando...';
                
                const res = await fetchAPI('/api/config/setup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if (res && res.status === 'ok') {
                    btn.textContent = '¡Listo!';
                    setTimeout(() => location.reload(), 1000);
                } else {
                    btn.textContent = 'Error';
                    setTimeout(() => btn.textContent = oldText, 2000);
                }
            });
            return true;
        }
    } catch (e) {
        console.error("Error checking onboarding:", e);
    }
    return false;
}

// ─── Navigation ─────────────────────────────────────────────
function initNavigation() {
    const links = document.querySelectorAll('.nav-link');
    const menuToggle = document.getElementById('menu-toggle');
    const sidebar = document.getElementById('sidebar');

    links.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const page = link.dataset.page;
            switchPage(page);
            // Close mobile sidebar
            sidebar.classList.remove('open');
        });
    });

    menuToggle?.addEventListener('click', () => {
        sidebar.classList.toggle('open');
    });
}

function switchPage(pageName) {
    // Update nav links
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.querySelector(`[data-page="${pageName}"]`)?.classList.add('active');

    // Update pages
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(`page-${pageName}`)?.classList.add('active');

    // Update title
    const titles = {
        dashboard: 'Dashboard',
        chat: 'Chat',
        tools: 'Herramientas',
        skills: 'Skills',
        config: 'Configuración',
    };
    document.getElementById('page-title').textContent = titles[pageName] || pageName;
}

// ─── Dashboard ──────────────────────────────────────────────
async function loadDashboard() {
    try {
        // Load stats
        const stats = await fetchAPI('/api/stats');
        if (stats) {
            updateStat('stat-messages-today', stats.messages_today || 0);
            updateStat('stat-tokens-today', formatNumber(stats.tokens_today || 0));
            updateStat('stat-tool-calls', stats.total_tool_calls || 0);
            updateStat('stat-active-convos', stats.active_conversations || 0);

            // Update model badge
            if (stats.current_model) {
                document.getElementById('current-model').textContent = stats.current_model;
            }
        }

        // Load activity history
        const history = await fetchAPI('/api/stats/history?days=14');
        if (history && history.length > 0) {
            renderActivityChart(history);
        }

        // Update status
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        statusDot.classList.add('online');
        statusText.textContent = 'Conectado';
    } catch (err) {
        console.error('Dashboard load error:', err);
    }
}

function updateStat(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = value;
        el.style.animation = 'none';
        // Trigger reflow
        void el.offsetHeight;
        el.style.animation = 'fadeIn 0.3s ease';
    }
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return String(num);
}

function renderActivityChart(data) {
    const ctx = document.getElementById('activity-chart');
    if (!ctx) return;

    const labels = data.map(d => {
        const date = new Date(d.date);
        return date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' });
    });
    const requests = data.map(d => d.requests || 0);
    const tokens = data.map(d => (d.tokens || 0) / 1000); // In thousands

    if (activityChart) {
        activityChart.destroy();
    }

    activityChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Requests',
                    data: requests,
                    backgroundColor: 'rgba(59, 130, 246, 0.6)',
                    borderColor: 'rgba(59, 130, 246, 1)',
                    borderWidth: 1,
                    borderRadius: 4,
                    yAxisID: 'y',
                },
                {
                    label: 'Tokens (K)',
                    data: tokens,
                    type: 'line',
                    borderColor: 'rgba(139, 92, 246, 1)',
                    backgroundColor: 'rgba(139, 92, 246, 0.1)',
                    borderWidth: 2,
                    pointRadius: 3,
                    pointBackgroundColor: 'rgba(139, 92, 246, 1)',
                    fill: true,
                    tension: 0.4,
                    yAxisID: 'y1',
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    labels: { color: '#94a3b8', font: { family: 'Inter', size: 11 } }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: { color: '#64748b', font: { size: 10 } },
                },
                y: {
                    position: 'left',
                    grid: { color: 'rgba(255,255,255,0.04)' },
                    ticks: { color: '#64748b', font: { size: 10 } },
                },
                y1: {
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#8b5cf6', font: { size: 10 } },
                }
            }
        }
    });
}

// ─── Chat ───────────────────────────────────────────────────

function initChat() {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const attachBtn = document.getElementById('attach-btn');
    const fileInput = document.getElementById('chat-file-input');
    
    // Load chat list
    loadChatList();
    document.getElementById('refresh-chat-list')?.addEventListener('click', loadChatList);

    input?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    input?.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 150) + 'px';
    });

    sendBtn?.addEventListener('click', sendMessage);
    
    attachBtn?.addEventListener('click', () => {
        fileInput?.click();
    });
    
    fileInput?.addEventListener('change', handleFileSelect);
}

async function handleFileSelect(e) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    
    const previewZone = document.getElementById('chat-preview-zone');
    previewZone.classList.add('active');
    
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const formData = new FormData();
        formData.append('file', file);
        
        // Show loading state
        const chip = document.createElement('div');
        chip.className = 'attachment-chip loading';
        chip.innerHTML = `<span>⏳ Subiendo ${file.name}...</span>`;
        previewZone.appendChild(chip);
        
        try {
            const uploadHeaders = {};
            if (_authToken) uploadHeaders['Authorization'] = `Bearer ${_authToken}`;
            const response = await fetch('/api/chat/upload', {
                method: 'POST',
                headers: uploadHeaders,
                body: formData
            });
            const data = await response.json();
            
            if (response.ok) {
                currentAttachments.push({
                    id: data.file_id,
                    name: data.filename,
                    type: data.content_type
                });
                
                // Replace loading with actual preview
                const isImage = data.content_type.startsWith('image/');
                chip.className = 'attachment-chip';
                chip.innerHTML = `
                    ${isImage ? `<span>🖼️</span>` : `<span>📄</span>`}
                    <span title="${data.filename}">${data.filename.substring(0, 15)}${data.filename.length > 15 ? '...' : ''}</span>
                    <span class="remove-attachment" data-id="${data.file_id}">×</span>
                `;
                
                chip.querySelector('.remove-attachment').addEventListener('click', function() {
                    const idToRemove = this.getAttribute('data-id');
                    currentAttachments = currentAttachments.filter(a => a.id !== idToRemove);
                    chip.remove();
                    if (currentAttachments.length === 0) {
                        previewZone.classList.remove('active');
                    }
                });
            } else {
                chip.innerHTML = `<span style="color:red">Error: ${file.name}</span>`;
            }
        } catch (err) {
            chip.innerHTML = `<span style="color:red">Error: ${file.name}</span>`;
            console.error(err);
        }
    }
    e.target.value = ''; // Reset input
}

function sendMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if ((!text && currentAttachments.length === 0) || isWaitingResponse) return;

    // Add user bubble (with attachment previews)
    addChatBubble(text, 'user', null, [...currentAttachments]);
    input.value = '';
    input.style.height = 'auto';
    
    // Clear preview zone
    const previewZone = document.getElementById('chat-preview-zone');
    previewZone.innerHTML = '';
    previewZone.classList.remove('active');

    // Show typing indicator
    showTyping();
    isWaitingResponse = true;

    // Send via WebSocket
    if (chatWs && chatWs.readyState === WebSocket.OPEN) {
        const payload = { 
            message: text,
            target_user_id: currentTarget.targetUser,
            target_channel_id: currentTarget.targetChannel
        };
        if (currentAttachments.length > 0) {
            payload.attachments = currentAttachments.map(a => a.id);
        }
        chatWs.send(JSON.stringify(payload));
    } else {
        hideTyping();
        addChatBubble('❌ No hay conexión al servidor. Recarga la página.', 'error');
        isWaitingResponse = false;
    }
    
    currentAttachments = [];
}

async function loadChatList() {
    const chatListEl = document.getElementById('chat-list');
    if (!chatListEl) return;
    
    try {
        const convos = await fetchAPI('/api/conversations');
        if (!convos) return;
        
        // Build items
        let html = `
            <div class="chat-item ${currentTarget.targetChannel === 'web' ? 'active' : ''}" data-channel="web" data-user="web" onclick="switchChatContext('web', 'web', 'Web Local')">
                <span class="chat-icon">🌐</span>
                <div class="chat-info" style="flex: 1; overflow: hidden;">
                    <div style="font-size: 0.9rem; font-weight: 500;">Web Local</div>
                </div>
            </div>
        `;
        
        convos.forEach(c => {
            if (c.channel_id === 'web') return;
            const isLocal = c.channel_id === 'console';
            const icon = isLocal ? '🖥️' : '📱';
            let title = `${isLocal ? 'Console' : 'Telegram'} - ${c.user_id}`;
            if (c.channel_id.startsWith('-')) title = `📱 Grupo - ${c.channel_id}`;
            
            const lsSnippet = c.last_message ? `<div style="font-size: 0.75rem; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${c.last_message}</div>` : '';
            
            const isActive = currentTarget.targetChannel === c.channel_id ? 'active' : '';
            html += `
                <div class="chat-item ${isActive}" data-channel="${c.channel_id}" data-user="${c.user_id}" onclick="switchChatContext('${c.channel_id}', '${c.user_id}', '${title}')">
                    <span class="chat-icon">${icon}</span>
                    <div class="chat-info" style="flex: 1; overflow: hidden;">
                        <div style="font-size: 0.9rem; font-weight: 500;">${title}</div>
                        ${lsSnippet}
                    </div>
                </div>
            `;
        });
        
        chatListEl.innerHTML = html;
    } catch (e) {
        console.error("Error loading chat list", e);
    }
}

async function switchChatContext(channelId, userId, title) {
    if (currentTarget.targetChannel === channelId && currentTarget.targetUser === userId) return;
    
    currentTarget.targetChannel = channelId;
    currentTarget.targetUser = userId;
    
    document.querySelectorAll('.chat-item').forEach(el => el.classList.remove('active'));
    document.querySelector(`.chat-item[data-channel="${channelId}"]`)?.classList.add('active');
    
    document.getElementById('current-chat-title').textContent = ` Hablando en: ${title}`;
    
    // Clear chat
    const container = document.getElementById('chat-messages');
    container.innerHTML = '';
    
    // Load history
    try {
        const history = await fetchAPI(`/api/conversations/${channelId}/${userId}?limit=50`);
        if (history && history.length > 0) {
            history.forEach(msg => {
                const label = msg.role === 'user' ? (channelId==='web'? 'Tú' : `Usuario (${userId})`) : null;
                addChatBubble(msg.content, msg.role === 'user' ? 'user' : 'assistant', label);
            });
        } else {
             container.innerHTML = `<div class="chat-welcome">
                <div class="welcome-icon">🧠</div>
                <h2>Contexto Limpio</h2>
                <p>Iniciando charla en ${title}</p>
            </div>`;
        }
    } catch (e) {
        console.error("Error loading history", e);
    }
}

function addChatBubble(content, type = 'assistant', badge = null, attachments = []) {
    const container = document.getElementById('chat-messages');
    // Remove welcome screen
    const welcome = container.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    const wrapper = document.createElement('div');
    wrapper.className = `chat-bubble ${type}`;
    
    if (badge) {
        const badgeEl = document.createElement('div');
        badgeEl.className = 'network-badge';
        badgeEl.textContent = badge;
        wrapper.appendChild(badgeEl);
    }

    if (content) {
        const textEl = document.createElement('div');
        
        // Auto-render internal media links
        const mediaRegex = /\[?(?:http:\/\/localhost:\d+)?\/api\/media\/([a-zA-Z0-9_-]+\.([a-zA-Z0-9]+))\]?/g;
        
        if (mediaRegex.test(content)) {
             // We need to carefully replace the matched links while preserving the rest of the text
             // We'll replace the full regex match, checking if the extension is an image or a generic file
             const formattedContent = content.replace(mediaRegex, (match, filename, ext) => {
                 const imageExts = ['png', 'jpg', 'jpeg', 'gif', 'webp'];
                 if (imageExts.includes(ext.toLowerCase())) {
                     return `<br><a href="/api/media/${filename}" target="_blank"><img src="/api/media/${filename}" style="max-width:100%; border-radius:8px; margin-top:0.5rem;" alt="Media"></a><br>`;
                 } else {
                     return `<br>
                     <a href="/api/media/${filename}" download target="_blank" class="file-card" style="display:flex; align-items:center; background:rgba(255,255,255,0.05); padding:10px; border-radius:8px; border:1px solid rgba(255,255,255,0.1); margin-top:0.5rem; text-decoration:none; color:inherit;">
                         <span style="font-size:1.5rem; margin-right:10px;">📄</span>
                         <div style="flex:1">
                             <div style="font-size:0.85rem;font-weight:bold">${filename}</div>
                             <div style="font-size:0.7rem;color:#94a3b8">Haz clic para descargar</div>
                         </div>
                     </a><br>`;
                 }
             });
             textEl.innerHTML = formattedContent.replace(/\n(?![^<]*>)/g, '<br>');
        } else {
             textEl.textContent = content; // Fallback to safe text
        }
        
        wrapper.appendChild(textEl);
    }
    
    if (attachments && attachments.length > 0) {
        attachments.forEach(att => {
            const attContainer = document.createElement('div');
            attContainer.className = 'bubble-attachment';
            if (att.type && att.type.startsWith('image/')) {
                attContainer.innerHTML = `<img src="/api/media/${att.id}" alt="${att.name || 'image'}">`;
            } else {
                attContainer.innerHTML = `
                    <a href="/api/media/${att.id}" target="_blank" class="file-card">
                        <span style="font-size:1.5rem">📄</span>
                        <div style="flex:1">
                            <div style="font-size:0.85rem;font-weight:bold">${att.name || 'Archivo'}</div>
                            <div style="font-size:0.7rem;color:#94a3b8">Hacer clic para ver/descargar</div>
                        </div>
                    </a>
                `;
            }
            wrapper.appendChild(attContainer);
        });
    }

    container.appendChild(wrapper);
    container.scrollTop = container.scrollHeight;
}

function showTyping() {
    const container = document.getElementById('chat-messages');
    const typing = document.createElement('div');
    typing.className = 'chat-bubble typing';
    typing.id = 'typing-indicator';
    typing.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
    container.appendChild(typing);
    container.scrollTop = container.scrollHeight;
}

function hideTyping() {
    document.getElementById('typing-indicator')?.remove();
}

// ─── WebSockets ─────────────────────────────────────────────
function initWebSockets() {
    connectChatWs();
    connectEventsWs();
}

function connectChatWs() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const tokenParam = _authToken ? `?token=${_authToken}` : '';
    chatWs = new WebSocket(`${protocol}//${location.host}/ws/chat${tokenParam}`);

    chatWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        hideTyping();
        isWaitingResponse = false;

        if (data.type === 'response') {
            addChatBubble(data.content, 'assistant');
        } else if (data.type === 'error') {
            addChatBubble(`❌ ${data.content}`, 'error');
        }
    };

    chatWs.onclose = () => {
        setTimeout(connectChatWs, 3000);
    };

    chatWs.onerror = () => {
        hideTyping();
        isWaitingResponse = false;
    };
}

function connectEventsWs() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const tokenParam = _authToken ? `?token=${_authToken}` : '';
    eventsWs = new WebSocket(`${protocol}//${location.host}/ws/events${tokenParam}`);

    eventsWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        addEventToLog(data);
        
        // Cross-channel sync: inject foreign messages into Web Chat if viewing the target channel or web general
        if (data.type === 'message.received') {
            if (data.channel_id === currentTarget.targetChannel) {
                // We are looking at this chat currently
                addChatBubble(data.content, 'user', `${data.channel_type === 'web' ? 'Tú' : '📱 ' + data.channel_type + ' - ' + data.user_id}`);
            }
            // Update sidebar if we got a message
            loadChatList();
        } else if (data.type === 'message.sent') {
            if (data.channel_id === currentTarget.targetChannel && currentTarget.targetChannel !== 'web') {
                 // The assistant replied natively on the channel we are looking at!
                 addChatBubble(data.content, 'assistant', `📱 Respuesta a ${data.channel_type}`);
            }
        } else if (data.type === 'tool.called') {
            if (data.channel_id === currentTarget.targetChannel || (currentTarget.targetChannel === 'web' && data.channel_id === 'web')) {
                addToolTrace(data.tool, data.arguments, 'running', data.channel_id + '-' + data.tool);
            }
        } else if (data.type === 'tool.result') {
            if (data.channel_id === currentTarget.targetChannel || (currentTarget.targetChannel === 'web' && data.channel_id === 'web')) {
                addToolTrace(data.tool, data.result, 'done', data.channel_id + '-' + data.tool);
            }
        }
    };

    eventsWs.onclose = () => {
        setTimeout(connectEventsWs, 3000);
    };

    // Keep alive
    setInterval(() => {
        if (eventsWs.readyState === WebSocket.OPEN) {
            eventsWs.send('ping');
        }
    }, 30000);
}

function addEventToLog(data) {
    const log = document.getElementById('event-log');
    if (!log) return;

    const now = new Date();
    const time = now.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    const eventTexts = {
        'message.received': `📩 Mensaje de ${data.user_id || '?'} en ${data.channel_type || '?'}`,
        'message.sent': `📤 Respuesta enviada (${data.tokens || 0} tokens)`,
        'tool.called': `🔧 Tool: ${data.tool || '?'}`,
        'tool.result': `✅ Resultado: ${(data.result || '').substring(0, 60)}...`,
        'llm.request': `🧠 LLM request → ${data.model || '?'}`,
        'llm.response': `⚡ LLM response (${data.tokens || 0} tokens, ${(data.elapsed || 0).toFixed(1)}s)`,
    };

    const text = eventTexts[data.type] || `${data.type}: ${JSON.stringify(data).substring(0, 80)}`;

    const item = document.createElement('div');
    item.className = 'event-item';
    item.innerHTML = `
        <span class="event-time">${time}</span>
        <span class="event-text">${text}</span>
    `;

    // Add to top
    log.prepend(item);

    // Limit items
    while (log.children.length > 50) {
        log.lastChild.remove();
    }
}

// ─── Tools ──────────────────────────────────────────────────
async function loadTools() {
    try {
        const tools = await fetchAPI('/api/tools');
        const container = document.getElementById('tools-list');
        if (!container || !tools) return;

        container.innerHTML = tools.map(tool => `
            <div class="tool-card">
                <div class="tool-card-header">
                    <span class="tool-name">${tool.name}</span>
                    <span class="risk-badge ${tool.risk_level}">${tool.risk_level}</span>
                </div>
                <p class="tool-description">${tool.description}</p>
            </div>
        `).join('');

        // Load executions
        const execs = await fetchAPI('/api/tools/executions?limit=20');
        const tbody = document.getElementById('executions-body');
        if (!tbody || !execs) return;

        tbody.innerHTML = execs.map(ex => {
            const time = new Date(ex.timestamp).toLocaleTimeString('es-ES', {
                hour: '2-digit', minute: '2-digit'
            });
            const status = ex.success ? '✅' : '❌';
            const args = (ex.arguments || '').substring(0, 40);
            return `
                <tr>
                    <td>${time}</td>
                    <td>${ex.tool_name}</td>
                    <td>${args}</td>
                    <td>${status}</td>
                    <td>${ex.elapsed_ms}ms</td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Tools load error:', err);
    }
}

// ─── Config ─────────────────────────────────────────────────
async function loadConfig() {
    try {
        const config = await fetchAPI('/api/config');
        if (!config) return;

        // Model info
        const modelInfo = await fetchAPI('/api/config/model');
        if (modelInfo) {
            document.getElementById('config-provider').textContent = modelInfo.provider || '-';
            document.getElementById('config-model').textContent = modelInfo.model || '-';
            document.getElementById('current-model').textContent = modelInfo.model || '-';
        }

        // Security
        const secMode = config.security?.execution_mode || '-';
        const secEl = document.getElementById('config-security-mode');
        secEl.textContent = secMode;
        secEl.style.background = secMode === 'confirmation'
            ? 'rgba(245, 158, 11, 0.15)' : secMode === 'yolo'
            ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)';
        secEl.style.color = secMode === 'confirmation'
            ? '#f59e0b' : secMode === 'yolo'
            ? '#ef4444' : '#10b981';

        const whitelistCount = config.security?.whitelisted_commands?.length || 0;
        document.getElementById('config-whitelist-count').textContent = `${whitelistCount} comandos`;

        // Channels
        const channelsEl = document.getElementById('config-channels');
        if (channelsEl && config.channels) {
            const channels = [
                { name: 'Discord', enabled: config.channels.discord?.enabled, icon: '🎮' },
                { name: 'Telegram', enabled: config.channels.telegram?.enabled, icon: '📱' },
                { name: 'WhatsApp', enabled: config.channels.whatsapp?.enabled, icon: '🟢' },
            ];
            channelsEl.innerHTML = channels.map(ch => `
                <div class="config-field">
                    <label>${ch.icon} ${ch.name}</label>
                    <span class="config-value" style="color: ${ch.enabled ? '#10b981' : '#64748b'}">
                        ${ch.enabled ? '✅ Habilitado' : '⭘ Deshabilitado'}
                    </span>
                </div>
            `).join('');
        }

        // Fetch available models over API and populate the dataset
        const dataListEl = document.getElementById('model-dataset');
        if (dataListEl) {
            const availableModels = await fetchAPI('/api/config/available_models');
            if (availableModels && availableModels.length > 0) {
                dataListEl.innerHTML = availableModels.map(m => `<option value="${m}"></option>`).join('');
            }
            // Put current model in input box so they see what they have
            const inputEl = document.getElementById('model-input');
            if (inputEl && modelInfo) {
                inputEl.value = modelInfo.model.replace('openai/', '');
            }
        }

        // Full JSON
        document.getElementById('config-full').textContent = JSON.stringify(config, null, 2);

        // Model change button
        document.getElementById('model-change-btn')?.addEventListener('click', async () => {
            const input = document.getElementById('model-input');
            const model = input ? input.value.trim() : '';
            if (!model) return;
            
            const result = await fetchAPI('/api/config/model', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model }),
            });
            if (result?.status === 'ok') {
                document.getElementById('config-model').textContent = result.model;
                document.getElementById('current-model').textContent = result.model;
            }
        });
    } catch (err) {
        console.error('Config load error:', err);
    }
}

// ─── Utilities ──────────────────────────────────────────────
async function fetchAPI(url, options = {}) {
    try {
        // Inject auth token
        if (_authToken) {
            if (!options.headers) options.headers = {};
            options.headers['Authorization'] = `Bearer ${_authToken}`;
        }
        const response = await fetch(url, options);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (err) {
        console.error(`API error (${url}):`, err);
        return null;
    }
}

// ─── Toggles & Config ───────────────────────────────────────
function initConfigToggles() {
    // Verbose toggle sync (localStorage)
    const verboseCheckbox = document.getElementById('config-verbose-channels');
    if (verboseCheckbox) {
        // Load existing
        const isVerbose = localStorage.getItem('openACMToggleVerbose') !== 'false';
        verboseCheckbox.checked = isVerbose;
        
        // Set init backend state
        fetchAPI('/api/config/verbose_channels', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: isVerbose })
        });
        
        verboseCheckbox.addEventListener('change', (e) => {
            localStorage.setItem('openACMToggleVerbose', e.target.checked);
            fetchAPI('/api/config/verbose_channels', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: e.target.checked })
            });
        });
    }

    // Web Chat tool log toggle
    const toggleLogBtn = document.getElementById('toggle-tool-logs');
    if (toggleLogBtn) {
        toggleLogBtn.addEventListener('change', (e) => {
            const isToolVisible = e.target.checked;
            document.querySelectorAll('.chat-bubble.tool-trace').forEach(el => {
                el.style.display = isToolVisible ? 'block' : 'none';
            });
        });
    }

    // Quick setup
    document.getElementById('btn-quick-setup')?.addEventListener('click', () => {
        document.getElementById('onboarding-overlay')?.classList.add('active');
    });
}

// ─── Utility Data Renderers ─────────────────────────────────

function addToolTrace(toolName, output, status, traceId) {
    const container = document.getElementById('chat-messages');
    const isToolVisible = document.getElementById('toggle-tool-logs')?.checked;
    
    // Check if trace exists
    let existingTrace = [...container.querySelectorAll('.tool-trace')].find(el => el.dataset.trace === traceId);
    
    if (status === 'running') {
        const wrapper = document.createElement('div');
        wrapper.className = 'chat-bubble tool-trace running';
        wrapper.dataset.trace = traceId;
        wrapper.style.display = isToolVisible ? 'block' : 'none';
        wrapper.style.background = 'var(--bg-tertiary)';
        wrapper.style.border = '1px dashed var(--accent-orange)';
        wrapper.style.color = 'var(--text-muted)';
        wrapper.style.fontFamily = 'monospace';
        wrapper.style.fontSize = '0.8rem';
        wrapper.innerHTML = `⚙️ Ejecutando <strong>${toolName}</strong>... <br><pre style="margin-top:0.5rem; white-space: pre-wrap;">${output}</pre>`;
        container.appendChild(wrapper);
        container.scrollTop = container.scrollHeight;
    } else {
        if (existingTrace) {
            existingTrace.classList.remove('running');
            existingTrace.style.border = '1px solid var(--accent-green)';
            existingTrace.innerHTML = `✅ <strong>${toolName}</strong> finalizado. <details style="cursor:pointer;"><summary>Ver resultado</summary><pre style="margin-top:0.5rem; white-space: pre-wrap;">${output}</pre></details>`;
            container.scrollTop = container.scrollHeight;
        }
    }
}

// ─── Skills ─────────────────────────────────────────────────
async function loadSkills() {
    try {
        const skills = await fetchAPI('/api/skills');
        if (!skills) return;
        
        const container = document.getElementById('skills-list');
        container.innerHTML = skills.map(skill => `
            <div class="skill-card ${skill.is_active ? '' : 'inactive'} ${skill.is_builtin ? 'builtin' : ''}">
                <div class="skill-header">
                    <h4 class="skill-name">${skill.name}</h4>
                    <span class="skill-category ${skill.category}">${skill.category}</span>
                </div>
                <p class="skill-description">${skill.description}</p>
                <div class="skill-footer">
                    <div class="skill-status">
                        <span class="skill-status-dot ${skill.is_active ? '' : 'inactive'}"></span>
                        ${skill.is_active ? 'Activa' : 'Inactiva'}
                        ${skill.is_builtin ? ' • Built-in' : ''}
                    </div>
                    <div class="skill-actions">
                        <button class="skill-btn toggle" onclick="toggleSkill(${skill.id}, ${!skill.is_active})">
                            ${skill.is_active ? 'Desactivar' : 'Activar'}
                        </button>
                        ${!skill.is_builtin ? `
                            <button class="skill-btn" onclick="editSkill(${skill.id})">Editar</button>
                            <button class="skill-btn delete" onclick="deleteSkill(${skill.id})">Eliminar</button>
                        ` : ''}
                    </div>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error('Error loading skills:', err);
    }
}

async function toggleSkill(id, activate) {
    try {
        await fetchAPI(`/api/skills/${id}/toggle`, { method: 'POST' });
        loadSkills();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

function initSkills() {
    // Load skills when page is shown
    document.getElementById('nav-skills').addEventListener('click', loadSkills);
    
    // Create skill modal
    const createModal = document.getElementById('skill-modal');
    document.getElementById('btn-create-skill').addEventListener('click', () => {
        document.getElementById('skill-form').reset();
        document.getElementById('skill-id').value = '';
        document.getElementById('skill-modal-title').textContent = 'Nueva Skill';
        createModal.classList.add('active');
    });
    
    document.getElementById('skill-modal-close').addEventListener('click', () => {
        createModal.classList.remove('active');
    });
    
    document.getElementById('skill-cancel').addEventListener('click', () => {
        createModal.classList.remove('active');
    });
    
    document.getElementById('skill-save').addEventListener('click', async () => {
        const id = document.getElementById('skill-id').value;
        const data = {
            name: document.getElementById('skill-name').value,
            description: document.getElementById('skill-description').value,
            category: document.getElementById('skill-category').value,
            content: document.getElementById('skill-content').value,
        };
        
        try {
            if (id) {
                await fetchAPI(`/api/skills/${id}`, {
                    method: 'PUT',
                    body: JSON.stringify(data),
                });
            } else {
                await fetchAPI('/api/skills', {
                    method: 'POST',
                    body: JSON.stringify(data),
                });
            }
            createModal.classList.remove('active');
            loadSkills();
        } catch (err) {
            alert('Error: ' + err.message);
        }
    });
    
    // Generate skill modal
    const generateModal = document.getElementById('generate-skill-modal');
    document.getElementById('btn-generate-skill').addEventListener('click', () => {
        document.getElementById('generate-skill-form').reset();
        generateModal.classList.add('active');
    });
    
    document.getElementById('generate-modal-close').addEventListener('click', () => {
        generateModal.classList.remove('active');
    });
    
    document.getElementById('generate-cancel').addEventListener('click', () => {
        generateModal.classList.remove('active');
    });
    
    document.getElementById('generate-submit').addEventListener('click', async () => {
        const data = {
            name: document.getElementById('gen-skill-name').value,
            description: document.getElementById('gen-skill-description').value,
            use_cases: document.getElementById('gen-skill-usecases').value,
        };
        
        try {
            const btn = document.getElementById('generate-submit');
            btn.textContent = 'Generando...';
            btn.disabled = true;
            
            await fetchAPI('/api/skills/generate', {
                method: 'POST',
                body: JSON.stringify(data),
            });
            
            generateModal.classList.remove('active');
            loadSkills();
        } catch (err) {
            alert('Error: ' + err.message);
        } finally {
            const btn = document.getElementById('generate-submit');
            btn.textContent = 'Generar';
            btn.disabled = false;
        }
    });
}

async function editSkill(id) {
    try {
        const skills = await fetchAPI('/api/skills');
        const skill = skills.find(s => s.id === id);
        if (!skill) return;
        
        document.getElementById('skill-id').value = skill.id;
        document.getElementById('skill-name').value = skill.name;
        document.getElementById('skill-description').value = skill.description;
        document.getElementById('skill-category').value = skill.category;
        document.getElementById('skill-content').value = skill.content;
        document.getElementById('skill-modal-title').textContent = 'Editar Skill';
        document.getElementById('skill-modal').classList.add('active');
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function deleteSkill(id) {
    if (!confirm('¿Eliminar esta skill permanentemente?')) return;
    
    try {
        await fetchAPI(`/api/skills/${id}`, { method: 'DELETE' });
        loadSkills();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}
