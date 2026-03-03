import React, { useState } from 'react';
import { login, register } from '../api';

export default function Login({ onLogin }) {
  const [isRegister, setIsRegister] = useState(false);
  const [form, setForm] = useState({ username: '', password: '', email: '', role: 'user' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isRegister) {
        await register(form);
        setIsRegister(false);
        setError('');
      }
      const data = await login(form.username, form.password);
      onLogin(data.access_token, data.user || { username: form.username });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center">
      <div className="bg-gray-800 rounded-lg shadow-xl p-8 w-full max-w-md border border-gray-700">
        <h1 className="text-2xl font-bold text-center mb-2 bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
          🤖 MCP Demo — Google ADK
        </h1>
        <p className="text-gray-400 text-center text-sm mb-6">
          {isRegister ? 'Create an account' : 'Sign in to your account'}
        </p>

        {error && (
          <div className="bg-red-900/30 border border-red-700 text-red-300 rounded p-3 mb-4 text-sm">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-300 mb-1">Username</label>
            <input
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
              value={form.username}
              onChange={e => setForm({ ...form, username: e.target.value })}
              required
            />
          </div>
          {isRegister && (
            <div>
              <label className="block text-sm text-gray-300 mb-1">Email</label>
              <input
                type="email"
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                value={form.email}
                onChange={e => setForm({ ...form, email: e.target.value })}
                required
              />
            </div>
          )}
          <div>
            <label className="block text-sm text-gray-300 mb-1">Password</label>
            <input
              type="password"
              className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
              value={form.password}
              onChange={e => setForm({ ...form, password: e.target.value })}
              required
            />
          </div>
          {isRegister && (
            <div>
              <label className="block text-sm text-gray-300 mb-1">Role</label>
              <select
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                value={form.role}
                onChange={e => setForm({ ...form, role: e.target.value })}
              >
                <option value="user">User</option>
                <option value="admin">Admin</option>
                <option value="read_only">Read Only</option>
              </select>
            </div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white rounded py-2 font-medium transition-colors disabled:opacity-50"
          >
            {loading ? 'Loading...' : isRegister ? 'Register' : 'Sign In'}
          </button>
        </form>

        <p className="text-center text-sm text-gray-400 mt-4">
          {isRegister ? 'Already have an account?' : "Don't have an account?"}{' '}
          <button onClick={() => { setIsRegister(!isRegister); setError(''); }} className="text-blue-400 hover:underline">
            {isRegister ? 'Sign In' : 'Register'}
          </button>
        </p>

        {/* Quick login buttons */}
        {!isRegister && (
          <div className="mt-6 border-t border-gray-700 pt-4">
            <p className="text-xs text-gray-500 text-center mb-3">Quick Login (Demo Users)</p>
            <div className="grid grid-cols-3 gap-2">
              {[
                { username: 'admin', password: 'admin123456', role: 'admin', color: 'bg-purple-600 hover:bg-purple-700' },
                { username: 'testuser', password: 'user123456', role: 'user', color: 'bg-blue-600 hover:bg-blue-700' },
                { username: 'viewer', password: 'viewer123456', role: 'read_only', color: 'bg-gray-600 hover:bg-gray-500' },
              ].map(u => (
                <button
                  key={u.username}
                  disabled={loading}
                  onClick={async () => {
                    setError('');
                    setLoading(true);
                    try {
                      const data = await login(u.username, u.password);
                      onLogin(data.access_token, data.user || { username: u.username, role: u.role });
                    } catch {
                      setError(`User "${u.username}" not registered yet. Register first.`);
                    } finally {
                      setLoading(false);
                    }
                  }}
                  className={`${u.color} text-white rounded py-2 text-xs font-medium transition-colors disabled:opacity-50`}
                >
                  <div>{u.username}</div>
                  <div className="text-[10px] opacity-70">{u.role}</div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
