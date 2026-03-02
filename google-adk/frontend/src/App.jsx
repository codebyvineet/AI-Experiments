import React, { useState, useEffect } from 'react';
import { getMe } from './api';
import Login from './components/Login';
import Dashboard from './components/Dashboard';
import AgentPanel from './components/AgentPanel';
import McpPanel from './components/McpPanel';
import ItemsPanel from './components/ItemsPanel';

const TABS = ['Dashboard', 'AI Agent', 'MCP Server', 'Items'];

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [user, setUser] = useState(null);
  const [tab, setTab] = useState('Dashboard');

  useEffect(() => {
    if (token) {
      getMe(token)
        .then(setUser)
        .catch(() => { setToken(null); localStorage.removeItem('token'); });
    }
  }, [token]);

  const handleLogin = (tok, usr) => {
    localStorage.setItem('token', tok);
    setToken(tok);
    setUser(usr);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setToken(null);
    setUser(null);
  };

  if (!token) return <Login onLogin={handleLogin} />;

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
            🤖 MCP Demo — Google ADK
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400">
            {user?.username} <span className="px-2 py-0.5 rounded bg-blue-600/30 text-blue-300 text-xs">{user?.role}</span>
          </span>
          <button onClick={handleLogout} className="text-sm text-red-400 hover:text-red-300">Logout</button>
        </div>
      </header>

      {/* Tabs */}
      <nav className="bg-gray-800/50 border-b border-gray-700 px-6">
        <div className="flex gap-1">
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2.5 text-sm font-medium transition-colors ${
                tab === t
                  ? 'text-blue-400 border-b-2 border-blue-400'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </nav>

      {/* Content */}
      <main className="p-6">
        {tab === 'Dashboard' && <Dashboard token={token} user={user} />}
        {tab === 'AI Agent' && <AgentPanel token={token} user={user} />}
        {tab === 'MCP Server' && <McpPanel token={token} />}
        {tab === 'Items' && <ItemsPanel token={token} user={user} />}
      </main>
    </div>
  );
}
