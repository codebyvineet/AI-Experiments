import { useState, useRef, useEffect, useCallback } from 'react';
import { api, API_BASE } from '../api';

export default function AgentPanel({ token, user }) {
  const [mode, setMode] = useState('plan'); // 'plan' or 'chat'
  const [goal, setGoal] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const [plan, setPlan] = useState([]);
  const [events, setEvents] = useState([]);
  const [results, setResults] = useState([]);
  const [finalSummary, setFinalSummary] = useState(null);
  const [status, setStatus] = useState('idle'); // idle, planning, planned, executing, completed, stopped
  const [isStreaming, setIsStreaming] = useState(false);
  const [previousSessions, setPreviousSessions] = useState([]);
  const [messageInput, setMessageInput] = useState('');
  // Chat mode state
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState([]);
  const [chatStreaming, setChatStreaming] = useState(false);
  const chatEndRef = useRef(null);
  const chatAbortRef = useRef(null);
  const eventsEndRef = useRef(null);
  const abortControllerRef = useRef(null);

  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  // Chat mode: send message and stream ReAct agent response
  const handleChatSend = async () => {
    const msg = chatInput.trim();
    if (!msg || chatStreaming) return;

    setChatInput('');
    setChatMessages(prev => [...prev, { role: 'user', content: msg }]);
    setChatStreaming(true);
    chatAbortRef.current = new AbortController();

    // Placeholder for assistant response that we'll build up
    const assistantIdx = { current: null };

    try {
      const response = await fetch(`${API_BASE}/stream/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ message: msg }),
        signal: chatAbortRef.current.signal,
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));

            if (data.type === 'thinking') {
              setChatMessages(prev => [...prev, { role: 'system', content: `🤔 ${data.message}` }]);
            } else if (data.type === 'tool_call') {
              setChatMessages(prev => [...prev, {
                role: 'tool',
                content: `🔧 Calling **${data.tool}**(${JSON.stringify(data.args || {})})`,
                tool: data.tool,
                toolType: 'call',
              }]);
            } else if (data.type === 'tool_result') {
              setChatMessages(prev => [...prev, {
                role: 'tool',
                content: data.result,
                tool: data.tool,
                toolType: 'result',
              }]);
            } else if (data.type === 'response') {
              setChatMessages(prev => [...prev, { role: 'assistant', content: data.message }]);
            } else if (data.type === 'error') {
              setChatMessages(prev => [...prev, { role: 'error', content: `❌ ${data.error}` }]);
            }
          } catch (e) {
            console.error('Chat SSE parse error:', e);
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setChatMessages(prev => [...prev, { role: 'error', content: `❌ ${err.message}` }]);
      }
    } finally {
      setChatStreaming(false);
      chatAbortRef.current = null;
    }
  };

  const handleChatStop = () => {
    if (chatAbortRef.current) {
      chatAbortRef.current.abort();
    }
    setChatStreaming(false);
  };

  // Restore session WITHOUT clearing other sessions' state
  const restoreSession = async (sid) => {
    // Don't restore if already on this session
    if (sid === sessionId) return;
    
    // Abort any active SSE stream before switching
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    if (chatAbortRef.current) {
      chatAbortRef.current.abort();
      chatAbortRef.current = null;
    }
    setIsStreaming(false);
    setChatStreaming(false);
    
    try {
      const session = await api.getSession(token, sid);
      if (session) {
        setSessionId(session.session_id || sid);
        setGoal(session.goal || '');
        // Initialize plan steps with status
        setPlan((session.plan || []).map(step => ({
          ...step, 
          status: session.status === 'completed' ? 'completed' : (step.status || 'pending')
        })));
        setResults(session.results || []);
        
        // Map backend status to frontend status
        const statusMap = {
          'awaiting_approval': 'planned',
          'executing': 'executing',
          'completed': 'completed',
          'planning': 'planning',
          'stopped': 'stopped'
        };
        setStatus(statusMap[session.status] || 'idle');
        
        // Don't clear events - just add restoration event
        addEvent({ type: 'session_restored', session_id: sid, message: `Loaded session: ${session.status}` });
      }
    } catch (err) {
      console.error('Failed to restore session:', err);
      addEvent({ type: 'error', error: `Failed to load session: ${err.message}` });
    }
  };

  const addEvent = useCallback((event) => {
    setEvents(prev => [...prev, { ...event, timestamp: new Date().toISOString() }]);
  }, []);

  // Enhanced SSE streaming with abort support
  const streamSSE = async (path) => {
    setIsStreaming(true);
    abortControllerRef.current = new AbortController();
    const url = `${API_BASE}${path}`;
    
    try {
      const response = await fetch(url, {
        headers: { 'Authorization': `Bearer ${token}` },
        signal: abortControllerRef.current.signal
      });
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              addEvent(data);
              
              // Handle specific events
              if (data.type === 'plan_step') {
                setPlan(prev => [...prev, { ...data.step, status: 'pending' }]);
              } else if (data.type === 'plan_complete') {
                // Initialize all steps with pending status
                setPlan(data.plan.map(step => ({ ...step, status: step.status || 'pending' })));
                setStatus('planned');
              } else if (data.type === 'step_start') {
                // Mark current step as running, previous as completed
                setPlan(prev => prev.map((s, i) => ({
                  ...s,
                  status: i === data.step_number - 1 ? 'running' : 
                          i < data.step_number - 1 ? 'completed' : 'pending'
                })));
              } else if (data.type === 'step_complete') {
                setPlan(prev => prev.map((s, i) => 
                  i === data.step_number - 1 ? { ...s, status: 'completed' } : s
                ));
              } else if (data.type === 'execution_complete') {
                // Mark all steps as completed when execution finishes
                setPlan(prev => prev.map(s => ({ ...s, status: 'completed' })));
                setStatus('completed');
                if (data.summary) {
                  const summaryText = typeof data.summary === 'string' 
                    ? data.summary 
                    : JSON.stringify(data.summary, null, 2);
                  setFinalSummary(summaryText);
                }
              } else if (data.type === 'task_complete') {
                const taskName = data.task_name || data.message || 'Task';
                const taskStatus = data.status || 'completed';
                if (data.result) {
                  setResults(prev => [...prev, {
                    task: taskName,
                    status: taskStatus,
                    result: data.result,
                    timestamp: new Date().toISOString()
                  }]);
                }
              } else if (data.type === 'execution_stopped') {
                setStatus('stopped');
                setFinalSummary(`⚠️ Execution Stopped\n\nReason: ${data.reason || 'unknown'}\n${data.message || ''}`);
              }
            } catch (e) {
              console.error('Parse error:', e);
            }
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        addEvent({ type: 'error', error: err.message });
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
    }
  };

  // Stop current operation
  const handleStop = async () => {
    // Abort the SSE stream
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    
    // Tell backend to stop
    if (sessionId) {
      try {
        await api.stopSession(token, sessionId);
        setStatus('stopped');
        addEvent({ type: 'session_stopped', message: 'Session stopped by user' });
        refreshSessions();
      } catch (err) {
        console.error('Failed to stop:', err);
      }
    }
    
    setIsStreaming(false);
  };

  const handleCreateSession = async () => {
    if (!goal.trim()) return;
    
    // Clear state for new session
    setEvents([]);
    setPlan([]);
    setResults([]);
    setFinalSummary(null);
    setStatus('planning');
    addEvent({ type: 'user_action', action: 'Creating session', goal });

    try {
      const session = await api.createSession(token, goal);
      
      if (session.detail === 'Could not validate credentials' || session.detail === 'Not authenticated') {
        addEvent({ type: 'error', error: 'Session expired. Please log in again.' });
        setStatus('idle');
        return;
      }
      
      if (!session.session_id) {
        addEvent({ type: 'error', error: `Failed to create session: ${JSON.stringify(session)}` });
        setStatus('idle');
        return;
      }
      
      setSessionId(session.session_id);
      addEvent({ type: 'session_created', session_id: session.session_id });
      
      // Immediately add the new session to the list with planning status
      setPreviousSessions(prev => [{
        session_id: session.session_id,
        goal: goal,
        status: 'planning'
      }, ...prev]);
      
      await streamSSE(`/stream/sessions/${session.session_id}/plan`);
      refreshSessions(); // Update sessions list with final status
    } catch (err) {
      addEvent({ type: 'error', error: err.message });
      setStatus('idle');
    }
  };

  const handleExecutePlan = async () => {
    if (!sessionId) return;
    
    setStatus('executing');
    setResults([]); // Clear previous results
    addEvent({ type: 'user_action', action: 'Executing plan' });
    
    await streamSSE(`/stream/sessions/${sessionId}/execute`);
    refreshSessions(); // Update sessions list
  };

  const handleResume = async () => {
    if (!sessionId) return;
    
    setStatus('executing');
    addEvent({ type: 'user_action', action: 'Resuming execution' });
    
    await streamSSE(`/stream/sessions/${sessionId}/execute`);
    refreshSessions();
  };

  // Auto-save plan on change with debounce
  const saveTimeoutRef = useRef(null);
  
  const handleUpdateStep = (stepIndex, field, value) => {
    const newPlan = plan.map((step, i) => 
      i === stepIndex ? { ...step, [field]: value } : step
    );
    setPlan(newPlan);
    
    // Auto-save with debounce (500ms after last change)
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }
    saveTimeoutRef.current = setTimeout(async () => {
      if (sessionId) {
        try {
          await api.updatePlan(token, sessionId, newPlan);
          // Silent save - no event needed
        } catch (err) {
          console.error('Auto-save failed:', err);
        }
      }
    }, 500);
  };

  // Start new session (clear current)
  const handleNewSession = () => {
    setSessionId(null);
    setGoal('');
    setPlan([]);
    setEvents([]);
    setResults([]);
    setFinalSummary(null);
    setStatus('idle');
    setMessageInput('');
  };

  // Send message to current session (interrupts and replans)
  const handleSendMessage = async () => {
    if (!sessionId || !messageInput.trim()) return;
    
    const message = messageInput.trim();
    setMessageInput('');
    addEvent({ type: 'user_action', action: `Message sent: ${message}` });
    
    try {
      // Stop current execution if running
      if (isStreaming) {
        abortControllerRef.current?.abort();
        setIsStreaming(false);
      }
      
      // Send message to backend
      const response = await api.sendMessage(token, sessionId, message);
      
      if (response.action === 'replan' || response.needs_replan) {
        addEvent({ type: 'status', message: 'Replanning based on your input...' });
        setStatus('planning');
        // Trigger replan stream
        await streamSSE(`/stream/sessions/${sessionId}/plan`);
      } else {
        addEvent({ type: 'status', message: response.message || 'Message received' });
      }
      
      refreshSessions();
    } catch (err) {
      addEvent({ type: 'error', error: `Failed to send message: ${err.message}` });
    }
  };

  // Cancel/delete a stuck session
  const handleCancelSession = async (sid) => {
    if (!confirm('Cancel this session? This cannot be undone.')) return;
    
    try {
      await api.deleteSession(token, sid, false);
      addEvent({ type: 'status', message: `Session ${sid.slice(0, 8)} cancelled` });
      
      // If we cancelled the current session, clear state
      if (sid === sessionId) {
        handleNewSession();
      }
      
      refreshSessions();
    } catch (err) {
      addEvent({ type: 'error', error: `Failed to cancel session: ${err.message}` });
    }
  };

  const handleDeleteSession = async (sid) => {
    if (!confirm('Permanently delete this session? This cannot be undone and all data will be lost.')) return;
    
    try {
      await api.deleteSession(token, sid, true);
      addEvent({ type: 'status', message: `Session ${sid.slice(0, 8)} permanently deleted` });
      
      // If we deleted the current session, clear state
      if (sid === sessionId) {
        handleNewSession();
      }
      
      refreshSessions();
    } catch (err) {
      addEvent({ type: 'error', error: `Failed to delete session: ${err.message}` });
    }
  };

  const getEventIcon = (type) => {
    const icons = {
      user_action: '👤',
      session_created: '🆕',
      session_restored: '🔄',
      session_stopped: '⏹️',
      status: '📢',
      thinking: '🤔',
      plan_step: '📝',
      plan_complete: '✅',
      plan_updated: '💾',
      step_start: '▶️',
      step_complete: '✔️',
      parallel_start: '⚡',
      parallel_complete: '🔄',
      task_start: '🔧',
      task_complete: '✓',
      execution_complete: '🎉',
      execution_stopped: '🚫',
      authorization_failed: '🔒',
      error: '❌'
    };
    return icons[type] || '📌';
  };

  const getStatusColor = (s) => {
    const colors = {
      'awaiting_approval': 'bg-yellow-600',
      'executing': 'bg-blue-600',
      'completed': 'bg-green-600',
      'stopped': 'bg-orange-600',
      'planning': 'bg-purple-600',
      'initialized': 'bg-gray-600'
    };
    return colors[s] || 'bg-gray-600';
  };

  const refreshSessions = async () => {
    try {
      const sessions = await api.listSessions(token);
      if (Array.isArray(sessions)) {
        setPreviousSessions(sessions);
      }
    } catch (err) {
      console.error('Failed to refresh sessions:', err);
    }
  };

  useEffect(() => {
    if (token) {
      refreshSessions();
      const interval = setInterval(refreshSessions, 10000);
      return () => clearInterval(interval);
    }
  }, [token]);

  return (
    <div>
      {/* Mode Toggle */}
      <div className="flex items-center gap-2 mb-4">
        <button
          onClick={() => setMode('plan')}
          className={`px-4 py-2 rounded-lg font-medium text-sm transition-colors ${
            mode === 'plan'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
          }`}
        >
          📋 Plan Mode
        </button>
        <button
          onClick={() => setMode('chat')}
          className={`px-4 py-2 rounded-lg font-medium text-sm transition-colors ${
            mode === 'chat'
              ? 'bg-purple-600 text-white'
              : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
          }`}
        >
          💬 Chat Mode
        </button>
        <span className="text-xs text-gray-500 ml-2">
          {mode === 'plan'
            ? 'Multi-step planning with approval'
            : 'Direct AI tool calling (ReAct agent)'}
        </span>
      </div>

      {/* Chat Mode UI */}
      {mode === 'chat' && (
        <div className="bg-gray-800 rounded-lg border border-gray-700 flex flex-col h-[700px]">
          <div className="p-3 border-b border-gray-700 flex items-center justify-between">
            <h3 className="font-medium">💬 Chat with AI Agent</h3>
            <span className="text-xs text-gray-500">
              ReAct agent — AI calls MCP tools autonomously
            </span>
          </div>

          {/* Chat Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {chatMessages.length === 0 ? (
              <div className="text-gray-500 text-center py-12">
                <p className="text-lg mb-2">Ask anything — the AI will use tools as needed</p>
                <p className="text-sm">Examples: "List all items", "Create an employee named John", "How many items do we have?"</p>
              </div>
            ) : (
              chatMessages.map((msg, i) => (
                <div
                  key={i}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  {msg.role === 'tool' && msg.toolType === 'result' ? (
                    // Collapsible tool result
                    <details className="max-w-[80%] bg-green-900/20 text-green-300 border border-green-700/50 rounded-lg text-xs">
                      <summary className="px-3 py-2 cursor-pointer hover:bg-green-900/30">
                        ✅ <strong>{msg.tool}</strong> returned data
                      </summary>
                      <pre className="px-3 py-2 border-t border-green-700/30 overflow-x-auto max-h-48 whitespace-pre-wrap break-words font-mono">
                        {typeof msg.content === 'string' ? msg.content.slice(0, 2000) : JSON.stringify(msg.content, null, 2).slice(0, 2000)}
                      </pre>
                    </details>
                  ) : (
                    <div
                      className={`max-w-[80%] rounded-lg px-4 py-2 text-sm ${
                        msg.role === 'user'
                          ? 'bg-blue-600 text-white'
                          : msg.role === 'assistant'
                          ? 'bg-gray-700 text-gray-200'
                          : msg.role === 'tool'
                          ? 'bg-yellow-900/30 text-yellow-300 border border-yellow-700/50'
                          : msg.role === 'system'
                          ? 'bg-gray-700/50 text-gray-400 italic text-xs'
                          : 'bg-red-900/30 text-red-300'
                      }`}
                    >
                      {msg.role === 'assistant' ? (
                        <div
                          className="prose prose-invert prose-sm max-w-none [&_ul]:list-disc [&_ul]:ml-4 [&_ol]:list-decimal [&_ol]:ml-4 [&_strong]:text-white"
                          dangerouslySetInnerHTML={{
                            __html: (typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content))
                              .replace(/&/g, '&amp;')
                              .replace(/</g, '&lt;')
                              .replace(/>/g, '&gt;')
                              .replace(/"/g, '&quot;')
                              .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                              .replace(/^\* /gm, '• ')
                              .replace(/\n/g, '<br/>')
                          }}
                        />
                      ) : (
                        <pre className="whitespace-pre-wrap break-words">
                          {typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
            {chatStreaming && (
              <div className="flex justify-start">
                <div className="bg-gray-700/50 rounded-lg px-4 py-2 text-sm text-gray-400 flex items-center gap-2">
                  <span className="w-2 h-2 bg-purple-400 rounded-full animate-pulse"></span>
                  AI is thinking...
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Chat Input */}
          <div className="p-3 border-t border-gray-700">
            <div className="flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleChatSend()}
                placeholder="Ask the AI agent anything..."
                className="flex-1 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-purple-500"
                disabled={chatStreaming}
              />
              {chatStreaming ? (
                <button
                  onClick={handleChatStop}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg font-medium transition-colors"
                >
                  ⏹ Stop
                </button>
              ) : (
                <button
                  onClick={handleChatSend}
                  disabled={!chatInput.trim()}
                  className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg font-medium transition-colors"
                >
                  Send
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Plan Mode UI (existing) */}
      {mode === 'plan' && (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Left Panel - Controls & Plan */}
      <div className="space-y-4">
        {/* Sessions Panel - Always visible */}
        <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium text-gray-300">📂 Sessions ({previousSessions.length})</h4>
            <div className="flex gap-2">
              <button 
                onClick={handleNewSession}
                className="px-2 py-1 text-xs bg-blue-600 hover:bg-blue-700 rounded"
              >
                + New
              </button>
              <button 
                onClick={refreshSessions}
                className="text-xs text-gray-500 hover:text-gray-300"
              >
                🔄
              </button>
            </div>
          </div>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {previousSessions.length === 0 ? (
              <div className="text-xs text-gray-500 text-center py-2">No sessions yet</div>
            ) : (
              previousSessions.map((s) => (
                <div 
                  key={s.session_id}
                  className={`flex items-center justify-between p-2 rounded text-xs transition-colors
                    ${sessionId === s.session_id ? 'bg-blue-900/50 border border-blue-600' : 'bg-gray-700/50 hover:bg-gray-700'}`}
                >
                  <div 
                    className="flex-1 truncate cursor-pointer"
                    onClick={() => restoreSession(s.session_id)}
                  >
                    <span className="text-gray-400 mr-2 font-mono">{s.session_id.slice(0, 8)}</span>
                    <span className="text-gray-300">{s.goal?.slice(0, 20) || 'No goal'}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className={`px-2 py-0.5 rounded text-xs text-white ${getStatusColor(s.status)}`}>
                      {s.status === 'awaiting_approval' ? 'ready' : s.status}
                    </span>
                    {/* Cancel button for stuck executing sessions */}
                    {s.status === 'executing' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleCancelSession(s.session_id); }}
                        className="px-1 py-0.5 text-red-400 hover:text-red-300 hover:bg-red-900/30 rounded"
                        title="Cancel stuck session"
                      >
                        ✕
                      </button>
                    )}
                    {/* Delete button for non-executing sessions */}
                    {s.status !== 'executing' && s.status !== 'planning' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteSession(s.session_id); }}
                        className="px-1 py-0.5 text-gray-400 hover:text-red-400 hover:bg-red-900/30 rounded"
                        title="Delete session permanently"
                      >
                        🗑️
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Current Session Info */}
        {sessionId && (
          <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs text-gray-500">Session: </span>
                <span className="text-xs font-mono text-gray-300">{sessionId.slice(0, 12)}...</span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded text-xs text-white ${
                  status === 'planning' ? 'bg-purple-600' :
                  status === 'planned' ? 'bg-yellow-600' :
                  status === 'executing' ? 'bg-blue-600' :
                  status === 'completed' ? 'bg-green-600' :
                  status === 'stopped' ? 'bg-orange-600' :
                  'bg-gray-600'
                }`}>
                  {status}
                </span>
                {isStreaming && (
                  <button
                    onClick={handleStop}
                    className="px-2 py-1 text-xs bg-red-600 hover:bg-red-700 rounded"
                  >
                    ⏹ Stop
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Role Info Banner */}
        <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-400">
              Role: <span className="text-white font-medium">{user?.role}</span>
            </span>
            <span className="text-gray-500">
              {user?.role === 'read_only' 
                ? '⚠️ Write operations will be denied during execution' 
                : '✅ Full tool access'}
            </span>
          </div>
        </div>

        {/* Goal Input */}
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <h3 className="font-medium mb-3">🎯 Define Your Goal</h3>
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="E.g., Search and analyze data, then create a report and store it..."
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded resize-none h-24 focus:outline-none focus:border-blue-500"
            disabled={isStreaming || !!sessionId}
          />
          <div className="flex flex-wrap gap-2 mt-3">
            {/* Create Plan - Only for new sessions */}
            {!sessionId && (
              <button
                onClick={handleCreateSession}
                disabled={isStreaming || !goal.trim()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded font-medium transition-colors"
              >
                🚀 Create Plan
              </button>
            )}
            {/* Execute Plan - For planned sessions */}
            {status === 'planned' && (
              <button
                onClick={handleExecutePlan}
                disabled={isStreaming}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 rounded font-medium transition-colors"
              >
                ▶️ Execute Plan
              </button>
            )}
            {/* Resume - For stopped sessions */}
            {status === 'stopped' && (
              <button
                onClick={handleResume}
                disabled={isStreaming}
                className="px-4 py-2 bg-orange-600 hover:bg-orange-700 disabled:bg-gray-600 rounded font-medium transition-colors"
              >
                ▶️ Resume
              </button>
            )}
            {/* Completed status */}
            {status === 'completed' && (
              <span className="px-4 py-2 text-green-400 flex items-center gap-2">
                ✅ Completed
              </span>
            )}
            {/* Executing status */}
            {status === 'executing' && (
              <span className="px-4 py-2 text-blue-400 flex items-center gap-2">
                <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse"></span>
                Executing...
              </span>
            )}
          </div>
          
          {/* Add More Input - Always visible when session exists */}
          {sessionId && (
            <div className="mt-4 pt-4 border-t border-gray-600">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={messageInput}
                  onChange={(e) => setMessageInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                  placeholder="Add more context or change the goal..."
                  className="flex-1 px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm focus:outline-none focus:border-blue-500"
                />
                <button
                  onClick={handleSendMessage}
                  disabled={!messageInput.trim()}
                  className="px-4 py-2 bg-cyan-600 hover:bg-cyan-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded text-sm font-medium transition-colors"
                >
                  ➕ Add Input
                </button>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Add more details and AI will update the plan accordingly
              </p>
            </div>
          )}
        </div>

        {/* Plan Editor */}
        {plan.length > 0 && (
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <h3 className="font-medium mb-3">📋 Execution Plan {status === 'planned' && '(Editable)'}</h3>
            <div className="space-y-3">
              {plan.map((step, index) => (
                <div 
                  key={step.step_id || index}
                  className={`bg-gray-700/50 rounded p-3 border-l-4 ${
                    step.status === 'completed' ? 'border-green-500' :
                    step.status === 'running' ? 'border-blue-500' :
                    'border-gray-500'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-gray-400">
                      Step {index + 1} • {step.phase} • {step.execution_mode}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      step.status === 'completed' ? 'bg-green-900 text-green-300' :
                      step.status === 'running' ? 'bg-blue-900 text-blue-300' :
                      'bg-gray-600 text-gray-300'
                    }`}>
                      {step.status}
                    </span>
                  </div>
                  
                  {status === 'planned' ? (
                    <input
                      type="text"
                      value={step.description}
                      onChange={(e) => handleUpdateStep(index, 'description', e.target.value)}
                      className="w-full px-2 py-1 bg-gray-600 border border-gray-500 rounded text-sm focus:outline-none focus:border-blue-500"
                    />
                  ) : (
                    <p className="font-medium">{step.description}</p>
                  )}

                  {/* Sub-tasks */}
                  {step.sub_tasks && (
                    <div className="mt-2 pl-3 border-l border-gray-600 space-y-1">
                      {step.sub_tasks.map((task, ti) => (
                        <div key={ti} className="flex items-center gap-2 text-sm text-gray-400">
                          <span className={`w-2 h-2 rounded-full ${
                            task.status === 'completed' ? 'bg-green-500' :
                            task.status === 'running' ? 'bg-blue-500' :
                            'bg-gray-500'
                          }`}></span>
                          {task.name}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Right Panel - Event Stream */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 flex flex-col h-[600px]">
        <div className="p-3 border-b border-gray-700 flex items-center justify-between">
          <h3 className="font-medium">📡 Event Stream</h3>
          {isStreaming && (
            <span className="flex items-center gap-2 text-sm text-blue-400">
              <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse"></span>
              Streaming...
            </span>
          )}
        </div>
        
        <div className="flex-1 overflow-y-auto p-3 space-y-2 scrollbar-thin">
          {events.length === 0 ? (
            <p className="text-gray-500 text-center py-8">
              Events will appear here as the agent works...
            </p>
          ) : (
            events.map((event, i) => {
              // Format event message based on type
              const getMessage = () => {
                if (event.message) return event.message;
                if (event.content) return event.content;
                if (event.action) return event.action;
                if (event.error) return event.error;
                
                // Format specific event types
                switch(event.type) {
                  case 'session_created':
                    return `Session created: ${event.session_id?.slice(0, 8)}...`;
                  case 'plan_step':
                    return `Step ${event.step_number}: ${event.step?.description || 'Planning step'}`;
                  case 'plan_complete':
                    return `Plan complete with ${event.total_steps || event.plan?.length || 0} steps`;
                  case 'task_complete':
                    return `Task completed: ${event.task_name || 'Task'}`;
                  case 'execution_complete':
                    return event.summary || 'Execution complete';
                  default:
                    return event.type || 'Event received';
                }
              };
              
              return (
                <div 
                  key={i}
                  className={`text-sm p-2 rounded ${
                    event.type === 'error' ? 'bg-red-900/30 text-red-300' :
                    event.type?.includes('complete') ? 'bg-green-900/30 text-green-300' :
                    event.type === 'thinking' ? 'bg-yellow-900/30 text-yellow-300' :
                    'bg-gray-700/50 text-gray-300'
                  }`}
                >
                  <span className="mr-2">{getEventIcon(event.type)}</span>
                  <span className="text-gray-500 text-xs mr-2">
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </span>
                  {getMessage()}
                </div>
              );
            })
          )}
          <div ref={eventsEndRef} />
        </div>
        
        {/* Message Input - Always visible when session exists */}
      </div>

      {/* Results Panel - Full Width Below */}
      {(results.length > 0 || finalSummary || status === 'completed') && (
        <div className="lg:col-span-2 bg-gray-800 rounded-lg border border-gray-700">
          <div className="p-3 border-b border-gray-700 flex items-center justify-between">
            <h3 className="font-medium">📊 Results & Output</h3>
            {status === 'completed' && (
              <span className="text-sm text-green-400 flex items-center gap-2">
                <span className="w-2 h-2 bg-green-400 rounded-full"></span>
                Execution Complete
              </span>
            )}
          </div>
          
          <div className="p-4 space-y-4">
            {/* Final Summary */}
            {finalSummary && (
              <div className="bg-green-900/20 border border-green-700 rounded-lg p-4">
                <h4 className="font-medium text-green-400 mb-2">✅ Summary</h4>
                <p className="text-gray-200 whitespace-pre-wrap">{finalSummary}</p>
              </div>
            )}
            
            {/* Task Results */}
            {results.length > 0 && (
              <div className="space-y-3">
                <h4 className="font-medium text-gray-400">Task Results:</h4>
                {results.map((result, i) => (
                  <div key={i} className="bg-gray-700/50 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-blue-400">{result.task}</span>
                      <span className="text-xs text-gray-500">
                        {result.timestamp ? new Date(result.timestamp).toLocaleTimeString() : ''}
                      </span>
                    </div>
                    <div className="bg-gray-900/50 rounded p-3 overflow-x-auto">
                      <pre className="text-sm text-gray-300 whitespace-pre-wrap">
                        {typeof result.result === 'string' 
                          ? result.result 
                          : JSON.stringify(result.result, null, 2)}
                      </pre>
                    </div>
                  </div>
                ))}
              </div>
            )}
            
            {/* No results yet but completed */}
            {status === 'completed' && results.length === 0 && !finalSummary && (
              <div className="text-gray-400 text-center py-4">
                <p>Execution completed. Check the event stream for details.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
      )}
    </div>
  );
}
