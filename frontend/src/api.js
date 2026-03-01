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
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    // Normalize the response - backend returns user_id, frontend expects id
    return {
      ...data,
      id: data.user_id || data.id,
      role: data.role || 'user'
    };
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
    // API returns array directly, wrap it
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

  // Streaming Sessions
  async createSession(token, goal) {
    const res = await fetch(`${API_BASE}/stream/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ goal })
    });
    return res.json();
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

  // SSE Streaming endpoints
  streamPlanGeneration(token, sessionId, onEvent, onError, onComplete) {
    const eventSource = new EventSource(
      `${API_BASE}/stream/sessions/${sessionId}/plan?token=${token}`
    );
    
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        onEvent(data);
        if (data.type === 'plan_complete' || data.type === 'error') {
          eventSource.close();
          onComplete?.();
        }
      } catch (err) {
        console.error('Parse error:', err);
      }
    };

    eventSource.onerror = (e) => {
      eventSource.close();
      onError?.(e);
    };

    return () => eventSource.close();
  },

  streamPlanExecution(token, sessionId, onEvent, onError, onComplete) {
    const eventSource = new EventSource(
      `${API_BASE}/stream/sessions/${sessionId}/execute?token=${token}`
    );
    
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        onEvent(data);
        if (data.type === 'execution_complete' || data.type === 'error') {
          eventSource.close();
          onComplete?.();
        }
      } catch (err) {
        console.error('Parse error:', err);
      }
    };

    eventSource.onerror = (e) => {
      eventSource.close();
      onError?.(e);
    };

    return () => eventSource.close();
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

  // MCP Server info
  async getMcpCapabilities() {
    const res = await fetch(`${API_BASE}/mcp/capabilities`);
    return res.json();
  }
};
