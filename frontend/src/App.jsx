import { useState, useEffect } from 'react';
import { api } from './api';
import Login from './components/Login';
import Dashboard from './components/Dashboard';
import AgentPanel from './components/AgentPanel';
import McpPanel from './components/McpPanel';
import ItemsPanel from './components/ItemsPanel';

function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '');
  const [user, setUser] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [health, setHealth] = useState(null);

  useEffect(() => {
    if (token) {
      api.getMe(token)
        .then(setUser)
        .catch(() => {
          setToken('');
          localStorage.removeItem('token');
        });
    }
  }, [token]);

  useEffect(() => {
    const checkHealth = () => {
      api.getHealth().then(setHealth).catch(() => setHealth(null));
    };
    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleLogin = (newToken) => {
    setToken(newToken);
    localStorage.setItem('token', newToken);
  };

  const handleLogout = () => {
    setToken('');
    setUser(null);
    localStorage.removeItem('token');
  };

  if (!token || !user) {
    return <Login onLogin={handleLogin} />;
  }

  const tabs = [
    { id: 'dashboard', label: 'Dashboard', icon: '📊' },
    { id: 'agent', label: 'AI Agent', icon: '🤖' },
    { id: 'mcp', label: 'MCP Server', icon: '🔌' },
    { id: 'items', label: 'Items CRUD', icon: '📦' },
  ];

  return (
    <div className="min-h-screen bg-gray-900">
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700">
        <div className="max-w-7xl mx-auto px-4 py-3 flex justify-between items-center">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-bold text-white">🧪 AI Experiments</h1>
            {health && (
              <div className="flex items-center gap-2 text-sm">
                <span className={`w-2 h-2 rounded-full ${health.status === 'healthy' ? 'bg-green-500' : 'bg-red-500'}`}></span>
                <span className="text-gray-400">
                  MongoDB: {health.mongodb} | Redis: {health.redis}
                </span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-4">
            <span className="text-gray-300">
              👤 {user.username} ({user.role})
            </span>
            <button
              onClick={handleLogout}
              className="px-3 py-1 bg-red-600 hover:bg-red-700 rounded text-sm"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      {/* Navigation */}
      <nav className="bg-gray-800/50 border-b border-gray-700">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-3 text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? 'text-blue-400 border-b-2 border-blue-400'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                {tab.icon} {tab.label}
              </button>
            ))}
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {activeTab === 'dashboard' && <Dashboard token={token} user={user} health={health} />}
        {activeTab === 'agent' && <AgentPanel token={token} user={user} />}
        {activeTab === 'mcp' && <McpPanel token={token} user={user} />}
        {activeTab === 'items' && <ItemsPanel token={token} user={user} />}
      </main>
    </div>
  );
}

export default App;
