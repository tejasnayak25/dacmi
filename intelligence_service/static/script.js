// --- CONFIGURATION ---
const SUPABASE_URL = 'https://zjvkyhtiarjqvbarrxaf.supabase.co'; 
const SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_JTHJ6GWOFcYI9S2I8_4baQ_c0bfvKYl';

// Initialize Supabase Client
const supabaseClient = supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);

// --- DOM ELEMENTS ---
const chatMessages = document.getElementById('chat-messages');
const queryInput = document.getElementById('query-input');
const sendBtn = document.getElementById('send-btn');
const vectorContext = document.getElementById('vector-context');
const graphContext = document.getElementById('graph-context');
const themeToggle = document.getElementById('theme-toggle');

// Auth & Overlay Elements
const authOverlay = document.getElementById('auth-overlay');
const appContent = document.getElementById('app-content');
const authSubmitBtn = document.getElementById('auth-submit-btn');
const authToggleLink = document.getElementById('auth-toggle-link');
const authSubtitle = document.getElementById('auth-subtitle');
const logoutBtn = document.getElementById('logout-btn');
const profileLogoutBtn = document.getElementById('profile-logout-btn');
const authEmailInput = document.getElementById('auth-email');
const authPassInput = document.getElementById('auth-password');
const authError = document.getElementById('auth-error');

// Settings Elements
const settingsModal = document.getElementById('settings-modal');
const openSettingsBtn = document.getElementById('open-settings');
const closeSettingsBtn = document.getElementById('close-settings');
const settingsTabs = document.querySelectorAll('.settings-tab');
const tabPanes = document.querySelectorAll('.tab-pane');

// --- STATE MANAGEMENT ---
let currentUser = null;
let isSignUp = false;
let chatSocket = null;

// --- AUTHENTICATION ---

async function signOut() {
    console.log('🔌 Disconnecting and signing out...');
    if (chatSocket) {
        chatSocket.close();
        chatSocket = null;
    }
    await supabaseClient.auth.signOut();
    window.location.reload(); 
}

async function handleAuth() {
    const email = authEmailInput?.value;
    const password = authPassInput?.value;
    if (!email || !password) return;
    
    if (authError) authError.style.display = 'none';
    if (authSubmitBtn) {
        authSubmitBtn.disabled = true;
        authSubmitBtn.textContent = 'Processing...';
    }

    try {
        let result;
        if (isSignUp) {
            result = await supabaseClient.auth.signUp({ email, password });
        } else {
            result = await supabaseClient.auth.signInWithPassword({ email, password });
        }

        if (result.error) throw result.error;
    } catch (error) {
        if (authError) {
            authError.textContent = error.message;
            authError.style.display = 'block';
        }
    } finally {
        if (authSubmitBtn) {
            authSubmitBtn.disabled = false;
            authSubmitBtn.textContent = isSignUp ? 'Sign Up' : 'Sign In';
        }
    }
}

if (authSubmitBtn) authSubmitBtn.addEventListener('click', handleAuth);
if (authToggleLink) authToggleLink.addEventListener('click', (e) => {
    e.preventDefault();
    isSignUp = !isSignUp;
    if (authSubtitle) authSubtitle.textContent = isSignUp ? 'Create your new account' : 'Access your personal intelligence engine';
    if (authSubmitBtn) authSubmitBtn.textContent = isSignUp ? 'Sign Up' : 'Sign In';
    if (authToggleLink) authToggleLink.textContent = isSignUp ? 'Already have an account? Sign In' : "Need an account? Sign Up";
});

if (logoutBtn) logoutBtn.addEventListener('click', signOut);
if (profileLogoutBtn) profileLogoutBtn.addEventListener('click', signOut);

// --- WEBSOCKET CHAT ENGINE ---

function initChatSocket(session) {
    if (!session || chatSocket) return;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socketUrl = `${protocol}//${window.location.host}/chat`;
    
    chatSocket = new WebSocket(socketUrl);

    chatSocket.onopen = () => {
        const token = session.access_token;
        chatSocket.send(JSON.stringify({ token: token }));
    };

    chatSocket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            if (data.type === 'auth_status') {
                if (data.status === 'success') {
                    const badge = document.querySelector('.status-badge');
                    if (badge) {
                        badge.textContent = 'Connection Active';
                        badge.style.color = '#4ade80';
                    }
                    if (chatMessages && chatMessages.children.length === 0) {
                        addMessage("Connection established. I am DACMI. How can I help you today?", "bot");
                    }
                }
            } else if (data.type === 'message') {
                removeTypingIndicator();
                addMessage(data.answer, 'bot', data.storage_log);
                updateContextPanel(data.context_used, data.related_concepts);
                enableSendButton();
            }
        } catch (e) {
            console.error('⚠️ Connection Data Error:', e);
            removeTypingIndicator();
            enableSendButton();
        }
    };

    chatSocket.onclose = () => {
        chatSocket = null;
        removeTypingIndicator();
        enableSendButton();
        const badge = document.querySelector('.status-badge');
        if (badge) {
            badge.textContent = 'Connection Offline';
            badge.style.color = '#f87171';
        }
        if (currentUser) {
            setTimeout(async () => {
                const { data } = await supabaseClient.auth.getSession();
                if (data.session) initChatSocket(data.session);
            }, 3000);
        }
    };
}

// --- UI LOGIC ---

function addMessage(text, role, storageLog = null) {
    if (!chatMessages) return;
    const div = document.createElement('div');
    div.className = `message ${role}`;
    
    // Render markdown for bot messages, plain text for user
    let renderedContent;
    if (role === 'bot') {
        // Configure marked options for better rendering
        marked.setOptions({
            breaks: true,
            gfm: true,
            headerIds: false,
        });
        renderedContent = marked.parse(text);
    } else {
        // Escape HTML for user messages and preserve line breaks
        renderedContent = `<p>${text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').split('\n').join('<br>')}</p>`;
    }
    
    let contentHtml = `<div class="message-content">${renderedContent}</div>`;
    if (storageLog) {
        contentHtml += `<div class="storage-log">🧠 ${storageLog}</div>`;
    }
    
    div.innerHTML = contentHtml;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showTypingIndicator() {
    if (!chatMessages || document.getElementById('typing-indicator')) return;
    const div = document.createElement('div');
    div.className = 'message bot typing-indicator';
    div.id = 'typing-indicator';
    div.innerHTML = `<div class="typing"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>`;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function removeTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) indicator.remove();
}

function updateContextPanel(vector, graph) {
    if (!vectorContext || !graphContext) return;

    if (vector && vector.length > 0) {
        vectorContext.innerHTML = vector.map(v => `<div class="context-chip">${v}</div>`).join('');
    } else {
        vectorContext.innerHTML = '<div class="empty-state">Waiting for context...</div>';
    }

    if (graph && graph.length > 0) {
        graphContext.innerHTML = graph.map(g => `
            <div class="graph-link">
                <div class="graph-meta">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M3 12h3m12 0h3M12 3v3m0 12v3"/></svg>
                    ${g.original}
                </div>
                <div class="graph-data">
                    ${g.connections.map(c => `
                        <div class="edge">
                            <span class="edge-label">${c.relation}</span>
                            <span class="edge-target">${c.related}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `).join('');
    } else {
        graphContext.innerHTML = '<div class="empty-state">Awaiting relational data...</div>';
    }
}

async function sendMessage() {
    if (!queryInput) return;
    const text = queryInput.value.trim();
    if (!text || !chatSocket || chatSocket.readyState !== WebSocket.OPEN) return;

    // Disable send button and show loading state
    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.innerHTML = 'Sending...';
        sendBtn.style.opacity = '0.6';
        sendBtn.style.cursor = 'not-allowed';
    }

    addMessage(text, 'user');
    queryInput.value = '';
    showTypingIndicator();
    chatSocket.send(JSON.stringify({ text }));
}

function enableSendButton() {
    if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.innerHTML = 'Send';
        sendBtn.style.opacity = '1';
        sendBtn.style.cursor = 'pointer';
    }
}

if (sendBtn) sendBtn.addEventListener('click', sendMessage);
if (queryInput) queryInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });

// --- UI & THEME MANAGEMENT ---

const savedTheme = localStorage.getItem('dacmi-theme') || 'dark';
document.documentElement.setAttribute('data-theme', savedTheme);

if (themeToggle) {
    themeToggle.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('dacmi-theme', newTheme);
        themeToggle.style.transform = 'scale(0.95)';
        setTimeout(() => themeToggle.style.transform = '', 100);
    });
}

if (openSettingsBtn) openSettingsBtn.addEventListener('click', () => { if (settingsModal) settingsModal.style.display = 'flex'; });
if (closeSettingsBtn) closeSettingsBtn.addEventListener('click', () => { if (settingsModal) settingsModal.style.display = 'none'; });

settingsTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const target = tab.dataset.tab;
        settingsTabs.forEach(t => t.classList.remove('active'));
        tabPanes.forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        const pane = document.getElementById(target);
        if (pane) pane.classList.add('active');
    });
});

// --- AUTH STATE OBSERVER ---

supabaseClient.auth.onAuthStateChange((event, session) => {
    if (session) {
        currentUser = session.user;
        if (authOverlay) authOverlay.style.display = 'none';
        if (appContent) appContent.style.visibility = 'visible';
        
        initChatSocket(session);
        
        const emailDisp = document.getElementById('user-email-display');
        const idDisp = document.getElementById('user-id-display');
        if (emailDisp) emailDisp.textContent = currentUser.email;
        if (idDisp) idDisp.textContent = currentUser.id;
    } else {
        currentUser = null;
        if (authOverlay) authOverlay.style.display = 'flex';
        if (appContent) appContent.style.visibility = 'hidden';
        if (chatSocket) {
            chatSocket.close();
            chatSocket = null;
        }
    }
});
