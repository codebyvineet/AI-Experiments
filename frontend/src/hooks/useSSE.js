import { useState, useCallback } from 'react';

export function useSSE() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [events, setEvents] = useState([]);

  const startStream = useCallback((url, token) => {
    return new Promise((resolve, reject) => {
      setIsStreaming(true);
      setEvents([]);

      // For SSE with auth, we need to use fetch with ReadableStream
      fetch(url, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
        .then(response => {
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';

          function read() {
            reader.read().then(({ done, value }) => {
              if (done) {
                setIsStreaming(false);
                resolve(events);
                return;
              }

              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split('\n\n');
              buffer = lines.pop() || '';

              for (const line of lines) {
                if (line.startsWith('data: ')) {
                  try {
                    const data = JSON.parse(line.slice(6));
                    setEvents(prev => [...prev, data]);
                    
                    if (data.type === 'error') {
                      setIsStreaming(false);
                      reject(new Error(data.error));
                      return;
                    }
                  } catch (e) {
                    console.error('Parse error:', e);
                  }
                }
              }

              read();
            }).catch(err => {
              setIsStreaming(false);
              reject(err);
            });
          }

          read();
        })
        .catch(err => {
          setIsStreaming(false);
          reject(err);
        });
    });
  }, []);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  return { isStreaming, events, startStream, clearEvents };
}
