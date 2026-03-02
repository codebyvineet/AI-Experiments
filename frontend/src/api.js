const API_BASE = 'http://localhost:8000';

export const api = {
  // Auth
  async login(username, password) {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    return res.json();
  },

  async register(username, password, email, role = 'user') {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, email, role })
    });
    return res.json();
  },

  async getMe(token) {
    // Retry with backoff to handle cases where backend is busy with SSE streams
    const maxRetries = 2;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      const controller = new AbortController();
      const timeout = attempt === 0 ? 8000 : 12000; // 8s first, 12s retry
      const timeoutId = setTimeout(() => controller.abort(), timeout);
      
      try {
        const res = await fetch(`${API_BASE}/auth/me`, {
          headers: { 'Authorization': `Bearer ${token}` },
          signal: controller.signal
        });
        clearTimeout(timeoutId);
        
        if (res.status === 401 || res.status === 403) {
          const error = new Error('Unauthorized');
          error.isAuthError = true;
          throw error;
        }
        
        const data = await res.json();
        return {
          ...data,
          id: data.user_id || data.id,
          role: data.role || 'user'
        };
      } catch (err) {
        clearTimeout(timeoutId);
        // Auth errors should not be retried
        if (err.isAuthError) {
          throw err;
        }
        // Retry on network/timeout errors
        if (attempt < maxRetries) {
          await new Promise(r => setTimeout(r, 1000 * (attempt + 1))); // backoff
          continue;
        }
        const error = new Error(err.name === 'AbortError' ? 'Request timeout' : err.message);
        error.isNetworkError = true;
        throw error;
      }
    }
  },

  // Health
  async getHealth() {
    const res = await fetch(`${API_BASE}/health`);
    return res.json();
  },

  // Items CRUD
  async listItems(token) {
    const res = await fetch(`${API_BASE}/items/`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    return { items: Array.isArray(data) ? data : (data.items || []) };
  },

  async createItem(token, item) {
    const res = await fetch(`${API_BASE}/items/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(item)
    });
    return res.json();
  },

  async updateItem(token, itemId, item) {
    const res = await fetch(`${API_BASE}/items/${itemId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(item)
    });
    return res.json();
  },

  async deleteItem(token, itemId) {
    const res = await fetch(`${API_BASE}/items/${itemId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    return res.json();
  },

  // Session Management
  async createSession(token, goal) {
    const res = await fetch(`${API_BASE}/stream/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ goal })
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || `HTTP ${res.status}: Session creation failed`);
    }
    return data;
  },

  async getSession(token, sessionId) {
    const res = await fetch(`${API_BASE}/stream/sessions/${sessionId}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    return res.json();
  },

  async listSessions(token) {
    const res = await fetch(`${API_BASE}/stream/sessions`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    return data.sessions || [];
  },

  async deleteSession(token, sessionId, permanent = false) {
    const url = permanent 
      ? `${API_BASE}/stream/sessions/${sessionId}?permanent=true`
      : `${API_BASE}/stream/sessions/${sessionId}`;
    const res = await fetch(url, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    return res.json();
  },

  async stopSession(token, sessionId) {
    const res = await fetch(`${API_BASE}/stream/sessions/${sessionId}/stop`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    return res.json();
  },

  async resumeSession(token, sessionId) {
    const res = await fetch(`${API_BASE}/stream/sessions/${sessionId}/resume`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    return res.json();
  },

  async sendMessage(token, sessionId, content) {
    const res = await fetch(`${API_BASE}/stream/sessions/${sessionId}/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ content })
    });
    return res.json();
  },

  async updatePlan(token, sessionId, plan) {
    const res = await fetch(`${API_BASE}/stream/sessions/${sessionId}/plan`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ session_id: sessionId, plan })
    });
    return res.json();
  },

  // MCP
  async getMcpTools(token) {
    const res = await fetch(`${API_BASE}/stream/mcp/tools`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    return res.json();
  },

  async callMcpTool(token, toolName, args = {}) {
    const res = await fetch(`${API_BASE}/stream/mcp/call/${toolName}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(args)
    });
    return res.json();
  },

  async getMcpCapabilities() {
    const res = await fetch(`${API_BASE}/mcp/capabilities`);
    return res.json();
  }
};
