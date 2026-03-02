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
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout
    
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
      // Only mark as auth error if it's an actual auth failure
      if (err.isAuthError) {
        throw err;
      }
      // For timeouts/network errors, throw a different error
      const error = new Error(err.name === 'AbortError' ? 'Request timeout' : err.message);
      error.isNetworkError = true;
      throw error;
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
