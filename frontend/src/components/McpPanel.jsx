import { useState, useEffect } from 'react';
import { api } from '../api';

export default function McpPanel({ token, user }) {
  const [tools, setTools] = useState([]);
  const [capabilities, setCapabilities] = useState(null);
  const [selectedTool, setSelectedTool] = useState(null);
  const [toolArgs, setToolArgs] = useState({});
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.getMcpTools(token).then(data => setTools(data.tools || [])).catch(console.error);
    api.getMcpCapabilities().then(setCapabilities).catch(console.error);
  }, [token]);

  const handleCallTool = async () => {
    if (!selectedTool) return;
    
    setLoading(true);
    setResult(null);
    
    try {
      const response = await api.callMcpTool(token, selectedTool.name, toolArgs);
      setResult(response);
    } catch (err) {
      setResult({ error: err.message });
    } finally {
      setLoading(false);
    }
  };

  const getToolIcon = (name) => {
    if (name.includes('create')) return '➕';
    if (name.includes('read') || name.includes('get')) return '📖';
    if (name.includes('update')) return '✏️';
    if (name.includes('delete')) return '🗑️';
    if (name.includes('user')) return '👤';
    if (name.includes('agent')) return '🤖';
    return '🔧';
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* MCP Server Info */}
      <div className="lg:col-span-3 bg-gray-800 rounded-lg p-4 border border-gray-700">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-medium">🔌 MCP Server Status</h3>
            <p className="text-gray-400 text-sm mt-1">
              {capabilities?.name || 'Loading...'} v{capabilities?.version || '1.0.0'}
            </p>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 bg-green-500 rounded-full"></span>
              <span>Connected</span>
            </div>
            <div className="text-gray-400">
              {tools.length} tools available for {user.role} role
            </div>
          </div>
        </div>
      </div>

      {/* Available Tools */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h3 className="font-medium mb-3">🛠️ Available Tools</h3>
        <div className="space-y-2">
          {tools.map((tool) => (
            <button
              key={tool.name}
              onClick={() => {
                setSelectedTool(tool);
                setToolArgs({});
                setResult(null);
              }}
              className={`w-full text-left p-3 rounded transition-colors ${
                selectedTool?.name === tool.name
                  ? 'bg-blue-600'
                  : 'bg-gray-700/50 hover:bg-gray-700'
              }`}
            >
              <div className="flex items-center gap-2">
                <span>{getToolIcon(tool.name)}</span>
                <span className="font-medium">{tool.name}</span>
              </div>
              <p className="text-xs text-gray-400 mt-1">{tool.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Tool Input */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h3 className="font-medium mb-3">📝 Tool Input</h3>
        
        {selectedTool ? (
          <div className="space-y-4">
            <div className="bg-gray-700/50 p-3 rounded">
              <h4 className="font-medium text-blue-400">{selectedTool.name}</h4>
              <p className="text-sm text-gray-400 mt-1">{selectedTool.description}</p>
            </div>

            {/* Dynamic Args Input */}
            {selectedTool.parameters && (
              <div className="space-y-3">
                <p className="text-sm text-gray-400">Parameters:</p>
                {Object.entries(selectedTool.parameters).map(([key, schema]) => (
                  <div key={key}>
                    <label className="block text-sm text-gray-300 mb-1">
                      {key} {schema.required && <span className="text-red-400">*</span>}
                    </label>
                    <input
                      type="text"
                      value={toolArgs[key] || ''}
                      onChange={(e) => setToolArgs({ ...toolArgs, [key]: e.target.value })}
                      placeholder={schema.description || key}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm focus:outline-none focus:border-blue-500"
                    />
                  </div>
                ))}
              </div>
            )}

            {/* Quick args for common tools */}
            {selectedTool.name === 'create_item' && (
              <div className="space-y-3">
                <div>
                  <label className="block text-sm text-gray-300 mb-1">Item Name</label>
                  <input
                    type="text"
                    value={toolArgs.name || ''}
                    onChange={(e) => setToolArgs({ ...toolArgs, name: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-300 mb-1">Description</label>
                  <input
                    type="text"
                    value={toolArgs.description || ''}
                    onChange={(e) => setToolArgs({ ...toolArgs, description: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>
            )}

            {(selectedTool.name === 'read_item' || selectedTool.name === 'delete_item') && (
              <div>
                <label className="block text-sm text-gray-300 mb-1">Item ID</label>
                <input
                  type="text"
                  value={toolArgs.item_id || ''}
                  onChange={(e) => setToolArgs({ ...toolArgs, item_id: e.target.value })}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm focus:outline-none focus:border-blue-500"
                />
              </div>
            )}

            <button
              onClick={handleCallTool}
              disabled={loading}
              className="w-full py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 rounded font-medium transition-colors"
            >
              {loading ? '⏳ Executing...' : '▶️ Execute Tool'}
            </button>
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">
            Select a tool from the list to get started
          </p>
        )}
      </div>

      {/* Result */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h3 className="font-medium mb-3">📤 Result</h3>
        
        {result ? (
          <div className={`p-3 rounded ${result.error ? 'bg-red-900/30' : 'bg-green-900/30'}`}>
            <pre className="text-sm overflow-auto whitespace-pre-wrap">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">
            Results will appear here after executing a tool
          </p>
        )}
      </div>

      {/* RBAC Info */}
      <div className="lg:col-span-3 bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h3 className="font-medium mb-3">🔐 RBAC Permissions</h3>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div className={`p-3 rounded ${user.role === 'admin' ? 'bg-purple-900/30 border border-purple-500' : 'bg-gray-700/50'}`}>
            <h4 className="font-medium text-purple-400">Admin</h4>
            <p className="text-gray-400 text-xs mt-1">Full access to all tools including user management</p>
          </div>
          <div className={`p-3 rounded ${user.role === 'user' ? 'bg-blue-900/30 border border-blue-500' : 'bg-gray-700/50'}`}>
            <h4 className="font-medium text-blue-400">User</h4>
            <p className="text-gray-400 text-xs mt-1">CRUD operations and agent execution</p>
          </div>
          <div className={`p-3 rounded ${user.role === 'read_only' ? 'bg-green-900/30 border border-green-500' : 'bg-gray-700/50'}`}>
            <h4 className="font-medium text-green-400">Read Only</h4>
            <p className="text-gray-400 text-xs mt-1">View items and resources only</p>
          </div>
        </div>
      </div>
    </div>
  );
}
