import { useState, useRef, useEffect, useCallback } from 'react';
import { api } from '../api';

const API_BASE = 'http://localhost:8000';

/**
 * Chat-like session interface for AI Agent interactions.
 * 
 * Similar to Claude/Copilot sessions:
 * - Session list on left
 * - Chat thread in center
 * - Always-visible message input
 * - Stop/Resume capability
 */
export default function ChatSession({ token, user }) {
  // Session state
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [sessionState, setSessionState] = useState(null);
  
  // Chat state
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [planExpanded, setPlanExpanded] = useState(true);
  
  // Refs
  const messagesEndRef = useRef(null);
  const abortControllerRef = useRef(null);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load sessions on mount
  useEffect(() => {
    if (token) {
      loadSessions();
    }
  }, [token]);

  // Load sessions from backend
  const loadSessions = async () => {
    try {
      const data = await api.listSessions(token);
      setSessions(data);
    } catch (err) {
      console.error('Failed to load sessions:', err);
    }
  };

  // Add message to chat
  const addMessage = useCallback((msg) => {
    setMessages(prev => [...prev, { 
      ...msg, 
      id: Date.now() + Math.random(),
      timestamp: msg.timestamp || new Date().toISOString() 
    }]);
  }, []);

  // Stream SSE events
  const streamSSE = async (url, onEvent) => {
    setIsStreaming(true);
    abortControllerRef.current = new AbortController();
    
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
              onEvent(data);
            } catch (e) {
              console.error('Parse error:', e);
            }
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('Stream error:', err);
        addMessage({ role: 'system', content: `Error: ${err.message}`, type: 'error' });
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
    }
  };

  // Create new session
  const handleNewSession = async () => {
    if (!inputValue.trim()) return;
    
    const goal = inputValue.trim();
    setInputValue('');
    setMessages([]);
    setSessionState(null);
    
    // Add user message
    addMessage({ role: 'user', content: goal });
    addMessage({ role: 'assistant', content: 'Creating plan...', type: 'status' });
    
    try {
      // Create session
      const session = await api.createSession(token, goal);
      setActiveSessionId(session.session_id);
      
      // Stream plan generation
      const planSteps = [];
      await streamSSE(`${API_BASE}/stream/sessions/${session.session_id}/plan`, (event) => {
        if (event.type === 'plan_step') {
          planSteps.push(event.step);
          // Update the status message with progress
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last?.type === 'status') {
              return [...prev.slice(0, -1), { 
                ...last, 
                content: `Planning... (${planSteps.length} steps)` 
              }];
            }
            return prev;
          });
        } else if (event.type === 'plan_complete') {
          // Replace status with plan message
          setMessages(prev => {
            const filtered = prev.filter(m => m.type !== 'status');
            return [...filtered, { 
              role: 'assistant', 
              type: 'plan',
              plan: event.plan,
              content: `I've created a plan with ${event.plan?.length || 0} steps.`
            }];
          });
          setSessionState({ status: 'awaiting_approval', plan: event.plan });
        }
      });
      
      // Refresh sessions list
      loadSessions();
      
    } catch (err) {
      addMessage({ role: 'system', content: `Error: ${err.message}`, type: 'error' });
    }
  };

  // Execute plan
  const handleExecute = async () => {
    if (!activeSessionId) return;
    
    addMessage({ role: 'assistant', content: 'Executing plan...', type: 'status' });
    setSessionState(prev => ({ ...prev, status: 'executing' }));
    
    const results = [];
    await streamSSE(`${API_BASE}/stream/sessions/${activeSessionId}/execute`, (event) => {
      if (event.type === 'step_start') {
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last?.type === 'status') {
            return [...prev.slice(0, -1), { 
              ...last, 
              content: `Executing step ${event.step_index + 1}...` 
            }];
          }
          return prev;
        });
      } else if (event.type === 'task_complete' && event.result) {
        results.push({
          task: event.task_name || 'Task',
          result: event.result
        });
      } else if (event.type === 'execution_complete') {
        // Replace status with completion message
        setMessages(prev => {
          const filtered = prev.filter(m => m.type !== 'status');
          return [...filtered, { 
            role: 'assistant', 
            type: 'result',
            results,
            summary: event.summary,
            content: `Execution complete! ${results.length} tasks completed.`
          }];
        });
        setSessionState(prev => ({ ...prev, status: 'completed' }));
      }
    });
    
    loadSessions();
  };

  // Stop execution
  const handleStop = async () => {
    // Abort current stream
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    
    if (activeSessionId) {
      try {
        await api.stopSession(token, activeSessionId);
        addMessage({ role: 'system', content: 'Session stopped. You can resume or send a new message.', type: 'info' });
        setSessionState(prev => ({ ...prev, status: 'stopped' }));
        loadSessions();
      } catch (err) {
        console.error('Failed to stop:', err);
      }
    }
  };

  // Send follow-up message
  const handleSendMessage = async () => {
    if (!inputValue.trim()) return;
    
    const content = inputValue.trim();
    setInputValue('');
    
    // If no active session, create new one
    if (!activeSessionId) {
      handleNewSession();
      return;
    }
    
    addMessage({ role: 'user', content });
    
    try {
      const result = await api.sendMessage(token, activeSessionId, content);
      
      if (result.result?.plan) {
        addMessage({ 
          role: 'assistant', 
          type: 'plan',
          plan: result.result.plan,
          content: `I've updated the plan based on your message.`
        });
        setSessionState({ status: 'awaiting_approval', plan: result.result.plan });
      } else {
        addMessage({ 
          role: 'assistant', 
          content: result.message || 'Message received.'
        });
      }
    } catch (err) {
      addMessage({ role: 'system', content: `Error: ${err.message}`, type: 'error' });
    }
  };

  // Select session from sidebar
  const handleSelectSession = async (sessionId) => {
    if (isStreaming) {
      handleStop();
    }
    
    setActiveSessionId(sessionId);
    setMessages([]);
    
    try {
      const state = await api.getSession(token, sessionId);
      setSessionState(state);
      
      // Reconstruct messages from state
      if (state.goal) {
        addMessage({ role: 'user', content: state.goal });
      }
      
      if (state.plan && state.plan.length > 0) {
        addMessage({ 
          role: 'assistant', 
          type: 'plan',
          plan: state.plan,
          content: `Plan with ${state.plan.length} steps.`
        });
      }
      
      if (state.results && state.results.length > 0) {
        addMessage({ 
          role: 'assistant', 
          type: 'result',
          results: state.results,
          content: `Completed with ${state.results.length} results.`
        });
      }
      
      if (state.status === 'stopped') {
        addMessage({ role: 'system', content: 'Session was stopped. You can resume or send a new message.', type: 'info' });
      }
    } catch (err) {
      addMessage({ role: 'system', content: `Error loading session: ${err.message}`, type: 'error' });
    }
  };

  // Get status badge color
  const getStatusColor = (status) => {
    const colors = {
      'planning': 'bg-blue-500',
      'awaiting_approval': 'bg-yellow-500',
      'executing': 'bg-purple-500',
      'completed': 'bg-green-500',
      'stopped': 'bg-orange-500',
      'failed': 'bg-red-500'
    };
    return colors[status] || 'bg-gray-500';
  };

  // Render plan component
  const renderPlan = (plan) => {
    if (!plan || plan.length === 0) return null;
    
    return (
      <div className="mt-2 bg-gray-700/50 rounded-lg overflow-hidden">
        <button 
          onClick={() => setPlanExpanded(!planExpanded)}
          className="w-full px-3 py-2 flex items-center justify-between text-sm text-gray-300 hover:bg-gray-600/50"
        >
          <span>📋 {plan.length} steps</span>
          <span>{planExpanded ? '▼' : '▶'}</span>
        </button>
        {planExpanded && (
          <div className="px-3 pb-3 space-y-2">
            {plan.map((step, i) => (
              <div key={i} className="flex items-start gap-2 text-sm">
                <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs
                  ${step.status === 'completed' ? 'bg-green-600' : 'bg-gray-600'}`}>
                  {i + 1}
                </span>
                <div className="flex-1">
                  <div className="text-gray-200">{step.description}</div>
                  <div className="text-xs text-gray-500">{step.phase} • {step.execution_mode}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  // Render results component
  const renderResults = (results, summary) => {
    if (!results || results.length === 0) return null;
    
    return (
      <div className="mt-2 bg-gray-700/50 rounded-lg p-3">
        {summary && (
          <div className="mb-2 p-2 bg-green-900/30 rounded text-sm text-green-300">
            {typeof summary === 'string' ? summary : JSON.stringify(summary)}
          </div>
        )}
        <div className="space-y-2">
          {results.slice(0, 3).map((r, i) => (
            <div key={i} className="text-sm">
              <div className="text-gray-400">{r.task}</div>
              <div className="bg-gray-800 rounded p-2 text-xs text-gray-300 max-h-24 overflow-auto">
                {typeof r.result === 'string' ? r.result : JSON.stringify(r.result, null, 2)}
              </div>
            </div>
          ))}
          {results.length > 3 && (
            <div className="text-xs text-gray-500">+ {results.length - 3} more results</div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="flex h-[calc(100vh-180px)] bg-gray-900 rounded-lg overflow-hidden border border-gray-700">
      {/* Sidebar - Sessions List */}
      <div className="w-64 bg-gray-800 border-r border-gray-700 flex flex-col">
        <div className="p-3 border-b border-gray-700">
          <button
            onClick={() => {
              setActiveSessionId(null);
              setMessages([]);
              setSessionState(null);
            }}
            className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
          >
            <span>+</span> New Session
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto">
          {sessions.length === 0 ? (
            <div className="p-4 text-gray-500 text-sm text-center">
              No sessions yet
            </div>
          ) : (
            sessions.map((s) => (
              <div
                key={s.session_id}
                onClick={() => handleSelectSession(s.session_id)}
                className={`p-3 border-b border-gray-700 cursor-pointer transition-colors
                  ${activeSessionId === s.session_id ? 'bg-gray-700' : 'hover:bg-gray-750'}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-gray-500 font-mono">
                    {s.session_id.slice(0, 8)}
                  </span>
                  <span className={`px-2 py-0.5 rounded text-xs text-white ${getStatusColor(s.status)}`}>
                    {s.status === 'awaiting_approval' ? 'ready' : s.status}
                  </span>
                </div>
                <div className="text-sm text-gray-300 truncate">
                  {s.goal || 'No goal'}
                </div>
              </div>
            ))
          )}
        </div>
        
        <div className="p-3 border-t border-gray-700">
          <button
            onClick={loadSessions}
            className="w-full px-3 py-1.5 text-sm text-gray-400 hover:text-gray-200 transition-colors"
          >
            🔄 Refresh
          </button>
        </div>
      </div>
      
      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="p-3 border-b border-gray-700 flex items-center justify-between bg-gray-800">
          <div className="flex items-center gap-3">
            <span className="text-lg">🤖</span>
            <div>
              <div className="font-medium">AI Agent</div>
              <div className="text-xs text-gray-500">
                {sessionState?.status || 'Ready for new session'}
              </div>
            </div>
          </div>
          
          {isStreaming && (
            <button
              onClick={handleStop}
              className="px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded text-sm font-medium transition-colors"
            >
              ⏹ Stop
            </button>
          )}
        </div>
        
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center text-gray-500">
                <div className="text-4xl mb-4">💬</div>
                <div className="text-lg mb-2">Start a conversation</div>
                <div className="text-sm">
                  Describe what you want to do and I'll create a plan.
                </div>
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <div 
                key={msg.id}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div className={`max-w-[80%] rounded-lg p-3 ${
                  msg.role === 'user' 
                    ? 'bg-blue-600' 
                    : msg.type === 'error'
                    ? 'bg-red-900/50 border border-red-700'
                    : msg.type === 'info'
                    ? 'bg-yellow-900/50 border border-yellow-700'
                    : 'bg-gray-700'
                }`}>
                  <div className="text-sm">{msg.content}</div>
                  
                  {/* Plan expansion */}
                  {msg.type === 'plan' && msg.plan && renderPlan(msg.plan)}
                  
                  {/* Results expansion */}
                  {msg.type === 'result' && renderResults(msg.results, msg.summary)}
                  
                  <div className="text-xs text-gray-500 mt-1">
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              </div>
            ))
          )}
          
          {/* Action buttons after plan */}
          {sessionState?.status === 'awaiting_approval' && !isStreaming && (
            <div className="flex justify-center gap-2 py-2">
              <button
                onClick={handleExecute}
                className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg font-medium transition-colors"
              >
                ▶️ Execute Plan
              </button>
              <button
                onClick={() => {
                  setInputValue('Please modify the plan to...');
                }}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded-lg font-medium transition-colors"
              >
                ✏️ Edit
              </button>
            </div>
          )}
          
          {/* Resume button for stopped sessions */}
          {sessionState?.status === 'stopped' && !isStreaming && (
            <div className="flex justify-center gap-2 py-2">
              <button
                onClick={handleExecute}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors"
              >
                ▶️ Resume
              </button>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>
        
        {/* Input Area */}
        <div className="p-4 border-t border-gray-700 bg-gray-800">
          <div className="flex gap-2">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && !e.shiftKey && (activeSessionId ? handleSendMessage() : handleNewSession())}
              placeholder={activeSessionId ? "Send a message..." : "What would you like to do?"}
              className="flex-1 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg focus:outline-none focus:border-blue-500"
              disabled={isStreaming}
            />
            <button
              onClick={activeSessionId ? handleSendMessage : handleNewSession}
              disabled={!inputValue.trim() || isStreaming}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg font-medium transition-colors"
            >
              {isStreaming ? '...' : '→'}
            </button>
          </div>
          
          {/* Role indicator */}
          <div className="mt-2 text-xs text-gray-500 flex items-center justify-between">
            <span>
              👤 {user?.username} ({user?.role})
            </span>
            {user?.role === 'read_only' && (
              <span className="text-yellow-500">⚠️ Write operations will be denied</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
