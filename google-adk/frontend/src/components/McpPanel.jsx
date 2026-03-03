import React, { useState, useEffect } from 'react';
import { getMcpTools } from '../api';

export default function McpPanel({ token, user }) {
  const [tools, setTools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [formValues, setFormValues] = useState({});
  const [result, setResult] = useState(null);
  const [executing, setExecuting] = useState(false);

  useEffect(() => {
    getMcpTools()
      .then(data => setTools(data.tools || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSelect = (i) => {
    setSelected(i);
    setFormValues({});
    setResult(null);
  };

  const handleExecute = async () => {
    if (selected === null) return;
    const tool = tools[selected];
    setExecuting(true);
    setResult(null);
    try {
      const resp = await fetch(`/mcp-proxy/tools/${tool.name}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(formValues),
      });
      const data = await resp.json();
      setResult({ ok: resp.ok, data });
    } catch (err) {
      setResult({ ok: false, data: { error: err.message } });
    }
    setExecuting(false);
  };

  const selectedTool = selected !== null ? tools[selected] : null;
  const schema = selectedTool?.inputSchema || selectedTool?.parameters || {};
  const props = schema.properties || {};

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">🔌 MCP Server Tools</h2>
        <div className="text-xs text-gray-500">
          {tools.length} tools available • Port 8001
        </div>
      </div>

      {/* RBAC info */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-3">
        <div className="flex items-center gap-4 text-sm">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
            user?.role === 'admin' ? 'bg-purple-600/30 text-purple-300' :
            user?.role === 'user' ? 'bg-blue-600/30 text-blue-300' :
            'bg-gray-600/30 text-gray-300'
          }`}>{user?.role}</span>
          <span>✅ Read tools</span>
          <span>{user?.role !== 'read_only' ? '✅' : '❌'} Execute write tools</span>
        </div>
      </div>

      {loading ? (
        <p className="text-gray-400">Loading tools...</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4" style={{ minHeight: '400px' }}>
          {/* Column 1: Tool list */}
          <div className="space-y-2 overflow-y-auto" style={{ maxHeight: '600px' }}>
            {tools.map((tool, i) => (
              <div
                key={i}
                onClick={() => handleSelect(i)}
                className={`rounded-lg p-3 cursor-pointer transition-colors border ${
                  selected === i
                    ? 'border-blue-500 bg-blue-900/20'
                    : 'border-gray-700 bg-gray-800 hover:border-gray-600'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span>🔧</span>
                  <code className="text-blue-400 text-sm font-medium">{tool.name}</code>
                </div>
                <p className="text-xs text-gray-400 mt-1 line-clamp-2">{tool.description}</p>
              </div>
            ))}
          </div>

          {/* Column 2: Parameters form */}
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
            {selectedTool ? (
              <>
                <h3 className="font-medium text-sm mb-3 flex items-center gap-2">
                  <span>⚙️</span> {selectedTool.name}
                </h3>
                <p className="text-xs text-gray-400 mb-3">{selectedTool.description}</p>
                <div className="space-y-3">
                  {Object.entries(props).map(([name, propSchema]) => (
                    <div key={name}>
                      <label className="block text-xs text-gray-400 mb-1">
                        {name}
                        {schema.required?.includes(name) && <span className="text-red-400 ml-1">*</span>}
                        <span className="ml-1 text-gray-600">({propSchema.type || 'any'})</span>
                      </label>
                      {propSchema.type === 'object' ? (
                        <textarea
                          value={formValues[name] || ''}
                          onChange={e => setFormValues({ ...formValues, [name]: e.target.value })}
                          placeholder='{"key": "value"}'
                          rows={3}
                          className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white font-mono"
                        />
                      ) : propSchema.type === 'integer' || propSchema.type === 'number' ? (
                        <input
                          type="number"
                          value={formValues[name] || propSchema.default || ''}
                          onChange={e => setFormValues({ ...formValues, [name]: e.target.value })}
                          className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white"
                        />
                      ) : (
                        <input
                          type="text"
                          value={formValues[name] || ''}
                          onChange={e => setFormValues({ ...formValues, [name]: e.target.value })}
                          placeholder={propSchema.description || name}
                          className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-white"
                        />
                      )}
                    </div>
                  ))}
                </div>
                <button
                  onClick={handleExecute}
                  disabled={executing}
                  className="mt-4 w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white rounded text-sm font-medium"
                >
                  {executing ? '⏳ Executing...' : '▶ Execute Tool'}
                </button>
              </>
            ) : (
              <div className="flex items-center justify-center h-full text-gray-500 text-sm">
                Select a tool to configure
              </div>
            )}
          </div>

          {/* Column 3: Result */}
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
            <h3 className="font-medium text-sm mb-3">📤 Result</h3>
            {result ? (
              <div className={`rounded p-3 text-sm font-mono overflow-auto ${
                result.ok ? 'bg-green-900/20 border border-green-700/50' : 'bg-red-900/20 border border-red-700/50'
              }`} style={{ maxHeight: '400px' }}>
                <pre className="whitespace-pre-wrap text-xs">{JSON.stringify(result.data, null, 2)}</pre>
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-gray-500 text-sm">
                Execute a tool to see results
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
