import React, { useState, useEffect } from 'react';
import { getHealth, getRolePermissions } from '../api';

export default function Dashboard({ token, user }) {
  const [health, setHealth] = useState(null);
  const [mcpHealth, setMcpHealth] = useState(null);
  const [perms, setPerms] = useState(null);
  const [sessions, setSessions] = useState([]);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => {});
    // Fetch MCP health
    fetch('/mcp/health').then(r => r.json()).then(setMcpHealth).catch(() => setMcpHealth({ status: 'unreachable' }));
    if (user?.role) getRolePermissions(user.role).then(setPerms).catch(() => {});
    // Fetch recent sessions
    if (token) {
      fetch('/agent/sessions', { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.json())
        .then(data => setSessions(Array.isArray(data) ? data.slice(0, 5) : []))
        .catch(() => {});
    }
  }, [user, token]);

  const apiOk = !!health;
  const mongoOk = health?.mongodb === 'connected';
  const redisOk = health?.redis === 'connected';
  const mcpOk = mcpHealth?.status === 'healthy';

  return (
    <div className="space-y-6 max-w-5xl">
      <h2 className="text-xl font-semibold">Dashboard</h2>

      {/* 4 Health Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <HealthCard title="API Server" status={apiOk ? 'connected' : 'disconnected'} icon="🖥️" detail="Port 8000" />
        <HealthCard title="MongoDB" status={mongoOk ? 'connected' : 'disconnected'} icon="🗃️" detail="Port 27017" />
        <HealthCard title="Redis" status={redisOk ? 'connected' : 'disconnected'} icon="⚡" detail="Port 6379" />
        <HealthCard title="MCP Server" status={mcpOk ? 'connected' : 'disconnected'} icon="🔧" detail="Port 8001" />
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 text-center">
          <div className="text-2xl font-bold text-blue-400">{sessions.length}</div>
          <div className="text-sm text-gray-400">Recent Sessions</div>
        </div>
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 text-center">
          <div className="text-2xl font-bold text-purple-400">{user?.role || '—'}</div>
          <div className="text-sm text-gray-400">Your Role</div>
        </div>
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 text-center">
          <div className="text-2xl font-bold text-green-400">Google ADK</div>
          <div className="text-sm text-gray-400">Framework</div>
        </div>
      </div>

      {/* User Info + Permissions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-5">
          <h3 className="text-lg font-medium mb-3">👤 User Info</h3>
          <div className="space-y-2 text-sm">
            <div><span className="text-gray-400">Username:</span> <span className="text-white">{user?.username}</span></div>
            <div><span className="text-gray-400">Role:</span> <span className={`px-2 py-0.5 rounded text-xs ${
              user?.role === 'admin' ? 'bg-purple-600/30 text-purple-300' :
              user?.role === 'user' ? 'bg-blue-600/30 text-blue-300' :
              'bg-gray-600/30 text-gray-300'
            }`}>{user?.role}</span></div>
            <div><span className="text-gray-400">ID:</span> <span className="text-gray-300 text-xs font-mono">{user?.id}</span></div>
          </div>
        </div>

        {perms && (
          <div className="bg-gray-800 rounded-lg border border-gray-700 p-5">
            <h3 className="text-lg font-medium mb-3">🔐 Permissions</h3>
            <div className="space-y-1 text-sm">
              <PermRow perm="items:read" has={perms.permissions?.includes('items:read')} />
              <PermRow perm="items:write" has={perms.permissions?.includes('items:write')} />
              <PermRow perm="items:delete" has={perms.permissions?.includes('items:delete')} />
              <PermRow perm="agent:execute" has={perms.permissions?.includes('agent:execute')} />
              <PermRow perm="mcp:read" has={perms.permissions?.includes('mcp:read')} />
              <PermRow perm="mcp:write" has={perms.permissions?.includes('mcp:write')} />
            </div>
          </div>
        )}
      </div>

      {/* Recent Sessions */}
      {sessions.length > 0 && (
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-5">
          <h3 className="text-lg font-medium mb-3">📋 Recent Sessions</h3>
          <div className="space-y-2">
            {sessions.map(s => (
              <div key={s.session_id} className="flex items-center justify-between bg-gray-700/50 rounded px-3 py-2 text-sm">
                <span className="font-mono text-xs text-gray-300">{s.session_id?.slice(0, 8)}...</span>
                <span className={`px-2 py-0.5 rounded text-xs ${
                  s.is_planning_mode ? 'bg-yellow-600/30 text-yellow-300' :
                  s.is_complete ? 'bg-green-600/30 text-green-300' :
                  'bg-blue-600/30 text-blue-300'
                }`}>
                  {s.is_planning_mode ? 'Planning' : s.is_complete ? 'Complete' : 'Active'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Architecture */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-5">
        <h3 className="text-lg font-medium mb-3">🏗️ System Architecture</h3>
        <div className="text-sm text-gray-300 font-mono bg-gray-900 rounded p-3 overflow-x-auto whitespace-pre">
{`┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  Frontend    │───▶│  Backend API │───▶│   MongoDB   │
│  React+Vite  │    │  FastAPI     │    │   Port 27017│
│  Port 3000   │    │  Port 8000   │    └─────────────┘
└─────────────┘    │  Google ADK  │    ┌─────────────┐
                   │  Vertex AI   │───▶│    Redis     │
                   └──────┬───────┘    │   Port 6379  │
                          │            └─────────────┘
                   ┌──────▼───────┐
                   │  MCP Server  │
                   │  FastMCP     │
                   │  Port 8001   │
                   └──────────────┘`}
        </div>
      </div>
    </div>
  );
}

function HealthCard({ title, status, icon, detail }) {
  const ok = status === 'connected';
  return (
    <div className={`rounded-lg border p-4 ${ok ? 'border-green-700 bg-green-900/20' : 'border-red-700 bg-red-900/20'}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">{icon}</span>
        <span className="font-medium text-sm">{title}</span>
      </div>
      <div className={`text-sm font-medium ${ok ? 'text-green-400' : 'text-red-400'}`}>
        {ok ? '✅ Connected' : '❌ Disconnected'}
      </div>
      <div className="text-xs text-gray-500 mt-1">{detail}</div>
    </div>
  );
}

function PermRow({ perm, has }) {
  return (
    <div className="flex items-center gap-2">
      <span>{has ? '✅' : '❌'}</span>
      <span className={`font-mono ${has ? 'text-gray-200' : 'text-gray-500'}`}>{perm}</span>
    </div>
  );
}
