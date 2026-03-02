import { useState } from 'react';
import { api } from '../api';

// Demo users for quick login
const DEMO_USERS = [
  { username: 'admin_demo', password: 'admin123', role: 'admin', color: 'purple' },
  { username: 'user_demo', password: 'user123', role: 'user', color: 'blue' },
  { username: 'viewer_demo', password: 'viewer123', role: 'read_only', color: 'gray' },
];

export default function Login({ onLogin }) {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (isRegister) {
        const result = await api.register(username, password, email);
        if (result.error || result.detail) {
          throw new Error(result.error || result.detail);
        }
        // Auto-login after register
        const loginResult = await api.login(username, password);
        if (loginResult.access_token) {
          onLogin(loginResult.access_token);
        }
      } else {
        const result = await api.login(username, password);
        if (result.access_token) {
          onLogin(result.access_token);
        } else {
          throw new Error(result.detail || 'Login failed');
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleQuickLogin = async (user) => {
    setError('');
    setLoading(true);
    try {
      const result = await api.login(user.username, user.password);
      if (result.access_token) {
        onLogin(result.access_token);
      } else {
        throw new Error(result.detail || 'Login failed - run ./scripts/create_demo_users.sh first');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900">
      <div className="bg-gray-800 p-8 rounded-lg shadow-xl w-full max-w-md">
        <h1 className="text-2xl font-bold text-white mb-2 text-center">
          🧪 AI Experiments
        </h1>
        <p className="text-gray-400 text-center mb-6">
          Multi-Agent System with MCP Server
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-300 mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded focus:outline-none focus:border-blue-500 text-white"
              required
            />
          </div>

          {isRegister && (
            <div>
              <label className="block text-sm text-gray-300 mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded focus:outline-none focus:border-blue-500 text-white"
                required
              />
            </div>
          )}

          <div>
            <label className="block text-sm text-gray-300 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded focus:outline-none focus:border-blue-500 text-white"
              required
            />
          </div>

          {error && (
            <div className="text-red-400 text-sm bg-red-900/30 p-2 rounded">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 rounded font-medium transition-colors"
          >
            {loading ? 'Loading...' : isRegister ? 'Register' : 'Login'}
          </button>
        </form>

        <div className="mt-4 text-center">
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="text-blue-400 hover:underline text-sm"
          >
            {isRegister ? 'Already have an account? Login' : "Don't have an account? Register"}
          </button>
        </div>

        {/* Quick Login Buttons */}
        <div className="mt-6 pt-6 border-t border-gray-700">
          <p className="text-gray-400 text-xs text-center mb-3">Quick Login (Demo Users)</p>
          <div className="flex gap-2">
            {DEMO_USERS.map((user) => (
              <button
                key={user.username}
                onClick={() => handleQuickLogin(user)}
                disabled={loading}
                className={`flex-1 py-2 px-2 rounded text-xs font-medium transition-colors disabled:opacity-50
                  ${user.color === 'purple' ? 'bg-purple-600 hover:bg-purple-700' : ''}
                  ${user.color === 'blue' ? 'bg-blue-600 hover:bg-blue-700' : ''}
                  ${user.color === 'gray' ? 'bg-gray-600 hover:bg-gray-500' : ''}
                `}
              >
                <div>{user.role}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
