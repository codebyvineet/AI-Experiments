import { useState, useRef, useEffect } from 'react';
import { api } from '../api';

export default function AgentPanel({ token, user }) {
  const [goal, setGoal] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const [plan, setPlan] = useState([]);
  const [events, setEvents] = useState([]);
  const [results, setResults] = useState([]); // Store execution results
  const [finalSummary, setFinalSummary] = useState(null); // Final summary
  const [status, setStatus] = useState('idle'); // idle, planning, planned, executing, completed
  const [isStreaming, setIsStreaming] = useState(false);
  const eventsEndRef = useRef(null);

  // Note: Agent is accessible to all users. Authorization happens at tool execution level.
  // A read_only user can create plans, but write operations will fail with 403 during execution.

  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  const addEvent = (event) => {
    setEvents(prev => [...prev, { ...event, timestamp: new Date().toISOString() }]);
  };

  const streamSSE = async (url) => {
    setIsStreaming(true);
    try {
      const response = await fetch(url, {
        headers: { 'Authorization': `Bearer ${token}` }
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
                setPlan(prev => [...prev, data.step]);
              } else if (data.type === 'plan_complete') {
                setPlan(data.plan);
                setStatus('planned');
              } else if (data.type === 'step_complete') {
                setPlan(prev => prev.map((s, i) => 
                  i === data.step_index ? { ...s, status: 'completed' } : s
                ));
              } else if (data.type === 'task_complete' && data.result) {
                // Capture task results
                const taskName = data.task?.name || data.task_name || data.message || 'Task';
                setResults(prev => [...prev, {
                  task: taskName,
                  result: data.result,
                  timestamp: new Date().toISOString()
                }]);
              } else if (data.type === 'execution_stopped') {
                // Authorization failure or other stop event
                setStatus('stopped');
                setFinalSummary(`⚠️ Execution Stopped\n\nReason: ${data.reason || 'unknown'}\n${data.message || ''}\n\nFailed task: ${data.failed_task || 'unknown'}`);
              } else if (data.type === 'execution_complete') {
                setStatus('completed');
                // Capture final summary if provided
                if (data.summary) {
                  // Format summary for display
                  const summaryText = typeof data.summary === 'string' 
                    ? data.summary 
                    : data.summary.summary || data.summary.message || JSON.stringify(data.summary, null, 2);
                  setFinalSummary(summaryText);
                }
              }
            } catch (e) {
              console.error('Parse error:', e);
            }
          }
        }
      }
    } catch (err) {
      addEvent({ type: 'error', error: err.message });
    } finally {
      setIsStreaming(false);
    }
  };

  const handleCreateSession = async () => {
    if (!goal.trim()) return;
    
    setEvents([]);
    setPlan([]);
    setResults([]);
    setFinalSummary(null);
    setStatus('planning');
    addEvent({ type: 'user_action', action: 'Creating session', goal });

    try {
      const session = await api.createSession(token, goal);
      
      // Check for auth errors
      if (session.detail === 'Could not validate credentials' || session.detail === 'Not authenticated') {
        addEvent({ type: 'error', error: 'Session expired. Please log in again.' });
        setStatus('idle');
        return;
      }
      
      // Check if session_id exists
      if (!session.session_id) {
        addEvent({ type: 'error', error: `Failed to create session: ${JSON.stringify(session)}` });
        setStatus('idle');
        return;
      }
      
      setSessionId(session.session_id);
      addEvent({ type: 'session_created', session_id: session.session_id });
      
      // Start plan generation stream
      await streamSSE(`/stream/sessions/${session.session_id}/plan`);
    } catch (err) {
      addEvent({ type: 'error', error: err.message });
      setStatus('idle');
    }
  };

  const handleExecutePlan = async () => {
    if (!sessionId) return;
    
    setStatus('executing');
    addEvent({ type: 'user_action', action: 'Executing plan' });
    
    await streamSSE(`/stream/sessions/${sessionId}/execute`);
  };

  const handleUpdateStep = (stepIndex, field, value) => {
    setPlan(prev => prev.map((step, i) => 
      i === stepIndex ? { ...step, [field]: value } : step
    ));
  };

  const handleSavePlan = async () => {
    if (!sessionId) return;
    
    try {
      await api.updatePlan(token, sessionId, plan);
      addEvent({ type: 'plan_updated', message: 'Plan saved successfully' });
    } catch (err) {
      addEvent({ type: 'error', error: err.message });
    }
  };

  const getEventIcon = (type) => {
    const icons = {
      user_action: '👤',
      session_created: '🆕',
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

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Left Panel - Controls & Plan */}
      <div className="space-y-4">
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
            disabled={isStreaming}
          />
          <div className="flex gap-2 mt-3">
            <button
              onClick={handleCreateSession}
              disabled={isStreaming || !goal.trim()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded font-medium transition-colors"
            >
              {status === 'idle' ? '🚀 Create Plan' : '🔄 New Session'}
            </button>
            {status === 'planned' && (
              <>
                <button
                  onClick={handleSavePlan}
                  disabled={isStreaming}
                  className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 rounded font-medium transition-colors"
                >
                  💾 Save Changes
                </button>
                <button
                  onClick={handleExecutePlan}
                  disabled={isStreaming}
                  className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 rounded font-medium transition-colors"
                >
                  ▶️ Execute Plan
                </button>
              </>
            )}
          </div>
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
            events.map((event, i) => (
              <div 
                key={i}
                className={`text-sm p-2 rounded ${
                  event.type === 'error' ? 'bg-red-900/30 text-red-300' :
                  event.type.includes('complete') ? 'bg-green-900/30 text-green-300' :
                  event.type === 'thinking' ? 'bg-yellow-900/30 text-yellow-300' :
                  'bg-gray-700/50 text-gray-300'
                }`}
              >
                <span className="mr-2">{getEventIcon(event.type)}</span>
                <span className="text-gray-500 text-xs mr-2">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
                {event.message || event.content || event.action || event.error || JSON.stringify(event)}
              </div>
            ))
          )}
          <div ref={eventsEndRef} />
        </div>
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
                        {new Date(result.timestamp).toLocaleTimeString()}
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
  );
}
