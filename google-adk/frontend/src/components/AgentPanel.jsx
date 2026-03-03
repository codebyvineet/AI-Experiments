import React, { useState, useEffect, useRef } from 'react';
import {
  createSession, listSessions, getSessionState,
  chatStream, enterPlanMode, executeStep, executeAllSteps, archiveSession
} from '../api';

export default function AgentPanel({ token, user }) {
  const [mode, setMode] = useState('chat');
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [planState, setPlanState] = useState(null);
  const msgEnd = useRef(null);

  useEffect(() => {
    loadSessions();
    const interval = setInterval(loadSessions, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    msgEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadSessions = async () => {
    try {
      const data = await listSessions(token);
      setSessions(Array.isArray(data) ? data : data.sessions || []);
    } catch {}
  };

  const handleNewSession = async () => {
    try {
      const data = await createSession(token);
      setActiveSession(data.session_id);
      setMessages([]);
      setPlanState(null);
      loadSessions();
    } catch (err) {
      addSystemMsg('Error creating session: ' + err.message);
    }
  };

  const addSystemMsg = (text) => {
    setMessages(prev => [...prev, { role: 'system', content: text }]);
  };

  const handleSend = async () => {
    if (!input.trim() || !activeSession || loading) return;
    const msg = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: msg }]);
    setLoading(true);

    if (mode === 'chat') {
      await handleChatStream(msg);
    } else {
      await handlePlanSend(msg);
    }
    setLoading(false);
  };

  const handleChatStream = async (msg) => {
    try {
      const res = await chatStream(token, activeSession, msg);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Stream error' }));
        addSystemMsg('Error: ' + (err.detail || res.statusText));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let assistantMsg = '';
      let currentIdx = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw || raw === '[DONE]') continue;
          try {
            const evt = JSON.parse(raw);
            if (evt.type === 'tool_call') {
              setMessages(prev => [...prev, {
                role: 'tool_call',
                name: evt.tool || evt.name,
                args: evt.args || evt.arguments || {}
              }]);
            } else if (evt.type === 'tool_result') {
              setMessages(prev => [...prev, {
                role: 'tool_result',
                name: evt.tool || evt.name,
                result: evt.result
              }]);
            } else if (evt.type === 'text') {
              if (currentIdx === null) {
                currentIdx = messages.length + 1; // approximate
                setMessages(prev => [...prev, { role: 'assistant', content: evt.content }]);
              } else {
                assistantMsg += evt.content;
                setMessages(prev => {
                  const copy = [...prev];
                  const last = copy[copy.length - 1];
                  if (last && last.role === 'assistant') {
                    copy[copy.length - 1] = { ...last, content: last.content + evt.content };
                  }
                  return copy;
                });
              }
            } else if (evt.type === 'error') {
              addSystemMsg('Error: ' + evt.content);
            }
          } catch {}
        }
      }
    } catch (err) {
      addSystemMsg('Stream error: ' + err.message);
    }
  };

  const handlePlanSend = async (msg) => {
    try {
      if (!planState || planState.status === 'completed') {
        const data = await enterPlanMode(token, activeSession, msg);
        setPlanState(data);
        setMessages(prev => [...prev, {
          role: 'plan',
          plan: data.plan || [],
          steps: data.plan || data.steps || []
        }]);
      } else {
        addSystemMsg('Plan already active. Use Execute buttons.');
      }
    } catch (err) {
      addSystemMsg('Plan error: ' + err.message);
    }
  };

  const handleExecuteStep = async () => {
    if (!activeSession || loading) return;
    setLoading(true);
    try {
      const data = await executeStep(token, activeSession);
      setMessages(prev => [...prev, {
        role: 'step_result',
        step: data.step_number,
        result: data.result || data.message
      }]);
      if (data.status === 'completed' || data.all_complete) {
        setPlanState(prev => ({ ...prev, status: 'completed' }));
        addSystemMsg('✅ All steps completed!');
      }
    } catch (err) {
      addSystemMsg('Step error: ' + err.message);
    }
    setLoading(false);
  };

  const handleExecuteAll = async () => {
    if (!activeSession || loading) return;
    setLoading(true);
    try {
      const data = await executeAllSteps(token, activeSession);
      const stepResults = data.execution_results || data.results || [];
      setMessages(prev => [...prev, {
        role: 'system',
        content: `Executed ${stepResults.length} steps. Status: ${data.status}`
      }]);
      for (const r of stepResults) {
        setMessages(prev => [...prev, {
          role: 'step_result',
          step: r.current_step || r.step_number,
          result: r.step?.result?.text || r.result || r.message || 'Done'
        }]);
      }
      setPlanState(prev => ({ ...prev, status: 'completed' }));
    } catch (err) {
      addSystemMsg('Execute all error: ' + err.message);
    }
    setLoading(false);
  };

  const loadSession = async (id) => {
    setActiveSession(id);
    setMessages([]);
    setPlanState(null);
    try {
      const data = await getSessionState(token, id);
      if (data.mode === 'plan' && data.plan) {
        setPlanState(data);
      }
    } catch {}
  };

  return (
    <div className="flex gap-4 h-[calc(100vh-140px)]">
      {/* Sidebar */}
      <div className="w-64 bg-gray-800 rounded-lg border border-gray-700 flex flex-col">
        <div className="p-3 border-b border-gray-700">
          <button
            onClick={handleNewSession}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white rounded py-2 text-sm font-medium transition-colors"
          >
            + New Session
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.map(s => {
            const sid = s.session_id || s.id;
            const status = s.is_complete ? 'Complete' : s.is_planning_mode ? 'Planning' : 'Active';
            const statusColor = s.is_complete ? 'bg-green-600' : s.is_planning_mode ? 'bg-yellow-600' : 'bg-blue-600';
            return (
              <button
                key={sid}
                onClick={() => loadSession(sid)}
                className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                  activeSession === sid
                    ? 'bg-blue-600/20 text-blue-300'
                    : 'text-gray-400 hover:bg-gray-700'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs truncate">{sid.slice(0, 8)}...</span>
                  <span className={`${statusColor} text-white text-xs px-1.5 py-0.5 rounded`}>{status}</span>
                </div>
                <div className="text-xs text-gray-500 mt-0.5">{s.mode || (s.is_planning_mode ? 'plan' : 'chat')}</div>
              </button>
            );
          })}
          {sessions.length === 0 && (
            <p className="text-gray-500 text-sm text-center py-4">No sessions yet</p>
          )}
        </div>
      </div>

      {/* Main area */}
      <div className="flex-1 flex flex-col bg-gray-800 rounded-lg border border-gray-700">
        {/* Mode toggle + read_only warning */}
        <div className="p-3 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex bg-gray-700 rounded-lg p-0.5">
              {['chat', 'plan'].map(m => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                    mode === m
                      ? 'bg-blue-600 text-white'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  {m === 'chat' ? '💬 Chat Mode' : '📋 Plan Mode'}
                </button>
              ))}
            </div>
            {user?.role === 'read_only' && (
              <span className="text-xs text-yellow-400 bg-yellow-900/30 border border-yellow-700/50 rounded px-2 py-1">
                ⚠️ Read-only — write operations will be denied
              </span>
            )}
          </div>
          {activeSession && (
            <span className="text-xs text-gray-500 font-mono">Session: {activeSession.slice(0, 12)}...</span>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {!activeSession ? (
            <div className="flex items-center justify-center h-full text-gray-500">
              Create or select a session to begin
            </div>
          ) : messages.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-500">
              {mode === 'chat' ? 'Send a message to start chatting' : 'Enter a goal to create a plan'}
            </div>
          ) : (
            messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)
          )}
          <div ref={msgEnd} />
        </div>

        {/* Plan controls */}
        {mode === 'plan' && planState && planState.status !== 'completed' && (
          <div className="px-4 py-2 border-t border-gray-700 flex gap-2">
            <button
              onClick={handleExecuteStep}
              disabled={loading}
              className="px-4 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded text-sm disabled:opacity-50"
            >
              ▶ Execute Next Step
            </button>
            <button
              onClick={handleExecuteAll}
              disabled={loading}
              className="px-4 py-1.5 bg-purple-600 hover:bg-purple-700 text-white rounded text-sm disabled:opacity-50"
            >
              ⏩ Execute All
            </button>
          </div>
        )}

        {/* Input */}
        <div className="p-3 border-t border-gray-700">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSend()}
              placeholder={mode === 'chat' ? 'Type a message...' : 'Enter a goal for the plan...'}
              className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
              disabled={!activeSession || loading}
            />
            <button
              onClick={handleSend}
              disabled={!activeSession || loading || !input.trim()}
              className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors disabled:opacity-50"
            >
              {loading ? '...' : 'Send'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Simple markdown-like rendering for assistant messages */
function renderMarkdown(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="bg-gray-800 px-1 py-0.5 rounded text-blue-300 text-xs">$1</code>')
    .replace(/^- (.+)/gm, '<li class="ml-4 list-disc text-gray-300">$1</li>')
    .replace(/^(\d+)\. (.+)/gm, '<li class="ml-4 list-decimal text-gray-300">$2</li>')
    .replace(/\n/g, '<br/>');
}

function MessageBubble({ msg }) {
  const [expanded, setExpanded] = useState(false);

  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="bg-blue-600 rounded-lg rounded-br-sm px-4 py-2 max-w-[70%]">
          <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
        </div>
      </div>
    );
  }

  if (msg.role === 'assistant') {
    return (
      <div className="flex justify-start">
        <div className="bg-gray-700 rounded-lg rounded-bl-sm px-4 py-2 max-w-[70%]">
          <div className="text-sm prose-sm" dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }} />
        </div>
      </div>
    );
  }

  if (msg.role === 'tool_call') {
    // Hide auth_token from displayed args
    const displayArgs = { ...msg.args };
    delete displayArgs.auth_token;
    return (
      <div className="flex justify-start">
        <div className="bg-yellow-900/30 border border-yellow-700/50 rounded-lg px-4 py-2 max-w-[80%]">
          <div className="flex items-center gap-2 text-yellow-400 text-sm font-medium">
            🔧 Calling <code className="bg-gray-800 px-1.5 py-0.5 rounded">{msg.name}</code>
          </div>
          {Object.keys(displayArgs).length > 0 && (
            <pre className="text-xs text-gray-400 mt-1 overflow-x-auto">{JSON.stringify(displayArgs, null, 2)}</pre>
          )}
        </div>
      </div>
    );
  }

  if (msg.role === 'tool_result') {
    const resultStr = typeof msg.result === 'string' ? msg.result : JSON.stringify(msg.result, null, 2);
    return (
      <div className="flex justify-start">
        <div className="bg-green-900/20 border border-green-700/50 rounded-lg px-4 py-2 max-w-[80%]">
          <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-2 text-green-400 text-sm font-medium">
            ✅ Result from <code className="bg-gray-800 px-1.5 py-0.5 rounded">{msg.name}</code>
            <span className="text-xs">{expanded ? '▼' : '▶'}</span>
          </button>
          {expanded && (
            <pre className="text-xs text-gray-300 mt-2 bg-gray-800 rounded p-2 overflow-x-auto max-h-60 overflow-y-auto">{resultStr}</pre>
          )}
        </div>
      </div>
    );
  }

  if (msg.role === 'plan') {
    const planSteps = Array.isArray(msg.plan) ? msg.plan : msg.steps || [];
    const planText = typeof msg.plan === 'string' ? msg.plan : '';
    return (
      <div className="bg-purple-900/20 border border-purple-700/50 rounded-lg px-4 py-3">
        <h4 className="text-purple-300 font-medium mb-2">📋 Plan Generated</h4>
        {planText && <p className="text-sm text-gray-300 mb-2">{planText}</p>}
        {planSteps.length > 0 && (
          <ol className="list-decimal list-inside space-y-1">
            {planSteps.map((s, i) => (
              <li key={i} className="text-sm text-gray-400">
                {typeof s === 'string' ? s : s.description || s.action || JSON.stringify(s)}
                {s.status && <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${s.status === 'completed' ? 'bg-green-900/50 text-green-400' : 'bg-gray-700 text-gray-400'}`}>{s.status}</span>}
              </li>
            ))}
          </ol>
        )}
      </div>
    );
  }

  if (msg.role === 'step_result') {
    return (
      <div className="bg-green-900/20 border border-green-700/50 rounded-lg px-4 py-2">
        <div className="text-green-400 text-sm font-medium">Step {msg.step} Result</div>
        <p className="text-sm text-gray-300 mt-1">{typeof msg.result === 'string' ? msg.result : JSON.stringify(msg.result)}</p>
      </div>
    );
  }

  // system
  return (
    <div className="text-center">
      <span className="text-xs text-gray-500 bg-gray-800 px-3 py-1 rounded-full">{msg.content}</span>
    </div>
  );
}
