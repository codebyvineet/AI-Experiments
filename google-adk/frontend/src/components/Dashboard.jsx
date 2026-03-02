import React, { useState, useEffect } from 'react';
import { getHealth, getRolePermissions } from '../api';

export default function Dashboard({ token, user }) {
  const [health, setHealth] = useState(null);
  const [perms, setPerms] = useState(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => {});
    if (user?.role) getRolePermissions(user.role).then(setPerms).catch(() => {});
  }, [user]);

  return (
    <div className="space-y-6 max-w-4xl">
      <h2 className="text-xl font-semibold">Dashboard</h2>

      {/* Health */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-5">
        <h3 className="text-lg font-medium mb-3 flex items-center gap-2">
          <span className={`w-3 h-3 rounded-full ${health?.status === 'healthy' ? 'bg-green-500' : 'bg-red-500'}`} />
          System Health
        </h3>
        {health ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <Stat label="Status" value={health.status} color={health.status === 'healthy' ? 'green' : 'red'} />
            <Stat label="MongoDB" value={health.mongodb || health.services?.mongodb || 'unknown'} color={(health.mongodb || health.services?.mongodb) === 'connected' ? 'green' : 'red'} />
            <Stat label="Redis" value={health.redis || health.services?.redis || 'unknown'} color={(health.redis || health.services?.redis) === 'connected' ? 'green' : 'red'} />
            <Stat label="Framework" value="Google ADK" color="blue" />
          </div>
        ) : (
          <p className="text-gray-400 text-sm">Loading...</p>
        )}
      </div>

      {/* User Info */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-5">
        <h3 className="text-lg font-medium mb-3">👤 User Info</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div><span className="text-gray-400">Username:</span> <span className="text-white">{user?.username}</span></div>
          <div><span className="text-gray-400">Role:</span> <span className="px-2 py-0.5 rounded bg-blue-600/30 text-blue-300 text-xs">{user?.role}</span></div>
          <div><span className="text-gray-400">Email:</span> <span className="text-white">{user?.email || 'N/A'}</span></div>
          <div><span className="text-gray-400">ID:</span> <span className="text-gray-300 text-xs font-mono">{user?.id}</span></div>
        </div>
      </div>

      {/* Permissions */}
      {perms && (
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-5">
          <h3 className="text-lg font-medium mb-3">🔐 Permissions ({user?.role})</h3>
          <div className="flex flex-wrap gap-2">
            {(perms.permissions || []).map(p => (
              <span key={p} className="px-2 py-1 bg-gray-700 rounded text-xs text-gray-300 font-mono">{p}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color }) {
  const colors = { green: 'text-green-400', red: 'text-red-400', blue: 'text-blue-400', yellow: 'text-yellow-400' };
  return (
    <div>
      <div className="text-gray-400">{label}</div>
      <div className={`font-medium ${colors[color] || 'text-white'}`}>{value}</div>
    </div>
  );
}
