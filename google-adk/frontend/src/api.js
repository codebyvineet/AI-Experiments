const BASE = '';

function headers(token) {
  const h = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

async function request(url, opts = {}) {
  const res = await fetch(BASE + url, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// Auth
export const register = (data) =>
  request('/auth/register', { method: 'POST', headers: headers(), body: JSON.stringify(data) });

export const login = (username, password) =>
  request('/auth/login', { method: 'POST', headers: headers(), body: JSON.stringify({ username, password }) });

export const getMe = (token) =>
  request('/auth/me', { headers: headers(token) });

export const getHealth = () =>
  request('/health');

export const getRolePermissions = (role) =>
  request(`/auth/permissions/${role}`);

// Items
export const listItems = (token) =>
  request('/items/', { headers: headers(token) });

export const createItem = (token, data) =>
  request('/items/', { method: 'POST', headers: headers(token), body: JSON.stringify(data) });

export const updateItem = (token, id, data) =>
  request(`/items/${id}`, { method: 'PUT', headers: headers(token), body: JSON.stringify(data) });

export const deleteItem = (token, id) =>
  request(`/items/${id}`, { method: 'DELETE', headers: headers(token) });

// MCP
export const getMcpTools = () =>
  request('/mcp/tools');

// Agent
export const createSession = (token) =>
  request('/agent/sessions', { method: 'POST', headers: headers(token) });

export const listSessions = (token) =>
  request('/agent/sessions', { headers: headers(token) });

export const getSessionState = (token, id) =>
  request(`/agent/sessions/${id}`, { headers: headers(token) });

export const chatMessage = (token, sessionId, message) =>
  request(`/agent/sessions/${sessionId}/chat`, {
    method: 'POST', headers: headers(token), body: JSON.stringify({ message })
  });

export const chatStream = (token, sessionId, message) => {
  return fetch(`${BASE}/agent/sessions/${sessionId}/chat/stream`, {
    method: 'POST',
    headers: headers(token),
    body: JSON.stringify({ message }),
  });
};

export const enterPlanMode = (token, sessionId, goal) =>
  request(`/agent/sessions/${sessionId}/plan`, {
    method: 'POST', headers: headers(token), body: JSON.stringify({ goal })
  });

export const executeStep = (token, sessionId) =>
  request(`/agent/sessions/${sessionId}/execute-step`, {
    method: 'POST', headers: headers(token)
  });

export const executeAllSteps = (token, sessionId) =>
  request(`/agent/sessions/${sessionId}/execute-all`, {
    method: 'POST', headers: headers(token)
  });

export const archiveSession = (token, sessionId) =>
  request(`/agent/sessions/${sessionId}/archive`, {
    method: 'POST', headers: headers(token), body: JSON.stringify({})
  });
