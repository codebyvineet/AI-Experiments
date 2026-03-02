import React, { useState, useEffect } from 'react';
import { getMcpTools } from '../api';

export default function McpPanel({ token }) {
  const [tools, setTools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    getMcpTools()
      .then(data => setTools(data.tools || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="max-w-4xl space-y-6">
      <h2 className="text-xl font-semibold">🔌 MCP Server Tools</h2>
      <p className="text-gray-400 text-sm">
        These tools are exposed by the standalone MCP server and available to the AI agent.
      </p>

      {loading ? (
        <p className="text-gray-400">Loading tools...</p>
      ) : tools.length === 0 ? (
        <p className="text-gray-400">No tools available</p>
      ) : (
        <div className="grid gap-3">
          {tools.map((tool, i) => (
            <div
              key={i}
              onClick={() => setSelected(selected === i ? null : i)}
              className="bg-gray-800 border border-gray-700 rounded-lg p-4 cursor-pointer hover:border-gray-600 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-lg">🔧</span>
                  <code className="text-blue-400 font-medium">{tool.name}</code>
                </div>
                <span className="text-xs text-gray-500">{selected === i ? '▼' : '▶'}</span>
              </div>
              <p className="text-sm text-gray-400 mt-1">{tool.description}</p>

              {selected === i && tool.parameters && (
                <div className="mt-3 bg-gray-900 rounded p-3">
                  <h4 className="text-sm text-gray-300 font-medium mb-2">Parameters</h4>
                  {tool.parameters.properties
                    ? Object.entries(tool.parameters.properties).map(([name, schema]) => (
                        <div key={name} className="flex items-start gap-2 text-sm mb-1">
                          <code className="text-purple-400">{name}</code>
                          <span className="text-gray-500">({schema.type || 'any'})</span>
                          {schema.description && <span className="text-gray-400">— {schema.description}</span>}
                        </div>
                      ))
                    : Object.entries(tool.parameters).map(([name, type]) => (
                        <div key={name} className="flex items-start gap-2 text-sm mb-1">
                          <code className="text-purple-400">{name}</code>
                          <span className="text-gray-500">({String(type)})</span>
                        </div>
                      ))
                  }
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
