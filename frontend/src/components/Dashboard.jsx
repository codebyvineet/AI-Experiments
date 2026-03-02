import { useState, useEffect } from 'react';
import { api } from '../api';

export default function Dashboard({ token, user, health }) {
  const [mcpInfo, setMcpInfo] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [items, setItems] = useState([]);

  useEffect(() => {
    api.getMcpCapabilities().then(setMcpInfo).catch(console.error);
    api.listSessions(token).then(data => setSessions(data.sessions || [])).catch(console.error);
    api.listItems(token).then(data => setItems(data.items || [])).catch(console.error);
  }, [token]);

  const StatusCard = ({ title, icon, status, details }) => (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-2xl">{icon}</span>
        <h3 className="font-medium">{title}</h3>
      </div>
      <div className="flex items-center gap-2 mb-2">
        <span className={`w-3 h-3 rounded-full ${status === 'connected' || status === 'healthy' ? 'bg-green-500' : 'bg-red-500'}`}></span>
        <span className="text-sm text-gray-300 capitalize">{status}</span>
      </div>
      {details && <p className="text-xs text-gray-500">{details}</p>}
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatusCard
          title="API Server"
          icon="🖥️"
          status={health?.status || 'unknown'}
          details="FastAPI Backend"
        />
        <StatusCard
          title="MongoDB"
          icon="🍃"
          status={health?.mongodb || 'unknown'}
          details="Hot State Storage"
        />
        <StatusCard
          title="Redis"
          icon="⚡"
          status={health?.redis || 'unknown'}
          details="Cold State Storage"
        />
        <StatusCard
          title="MCP Server"
          icon="🔌"
          status={mcpInfo ? 'connected' : 'unknown'}
          details={mcpInfo?.name || 'Model Context Protocol'}
        />
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="text-gray-400 text-sm mb-1">Active Sessions</h3>
          <p className="text-3xl font-bold text-blue-400">{sessions.length}</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="text-gray-400 text-sm mb-1">Items in DB</h3>
          <p className="text-3xl font-bold text-green-400">{items.length}</p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="text-gray-400 text-sm mb-1">Your Role</h3>
          <p className="text-3xl font-bold text-purple-400 capitalize">{user?.role}</p>
        </div>
      </div>

      {/* System Architecture */}
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
        <h3 className="text-lg font-medium mb-4">🏗️ System Architecture</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
          <div className="bg-gray-700/50 rounded p-4">
            <h4 className="font-medium text-blue-400 mb-2">Frontend (React)</h4>
            <ul className="text-gray-400 space-y-1">
              <li>• Dashboard UI</li>
              <li>• Agent Interaction Panel</li>
              <li>• MCP Tools Interface</li>
              <li>• Real-time SSE Streaming</li>
            </ul>
          </div>
          <div className="bg-gray-700/50 rounded p-4">
            <h4 className="font-medium text-green-400 mb-2">Backend (FastAPI)</h4>
            <ul className="text-gray-400 space-y-1">
              <li>• REST API Endpoints</li>
              <li>• SSE Streaming</li>
              <li>• JWT Authentication</li>
              <li>• Multi-Agent Orchestration</li>
            </ul>
          </div>
          <div className="bg-gray-700/50 rounded p-4">
            <h4 className="font-medium text-purple-400 mb-2">MCP Server</h4>
            <ul className="text-gray-400 space-y-1">
              <li>• CRUD Tool Operations</li>
              <li>• RBAC Access Control</li>
              <li>• Resource Management</li>
              <li>• Token Generation</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Recent Sessions */}
      {sessions.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
          <h3 className="text-lg font-medium mb-4">📋 Recent Agent Sessions</h3>
          <div className="space-y-2">
            {sessions.slice(0, 5).map((session) => (
              <div key={session.session_id} className="bg-gray-700/50 rounded p-3 flex justify-between items-center">
                <div>
                  <p className="font-medium">{session.goal}</p>
                  <p className="text-xs text-gray-500">{session.session_id}</p>
                </div>
                <span className={`px-2 py-1 rounded text-xs ${
                  session.status === 'completed' ? 'bg-green-900 text-green-300' :
                  session.status === 'executing' ? 'bg-blue-900 text-blue-300' :
                  'bg-gray-600 text-gray-300'
                }`}>
                  {session.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
