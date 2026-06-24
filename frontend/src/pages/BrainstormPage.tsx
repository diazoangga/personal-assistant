import React, { useState } from 'react';
import { api, EventUpdate } from '../api/client';

export const BrainstormPage: React.FC = () => {
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<Array<{ role: string; text: string }>>([]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    setIsLoading(true);

    try {
      const result = await api.brainstorm(input, sessionId);
      if (!sessionId) setSessionId(result.job_id);

      // Add user message
      setMessages((prev) => [...prev, { role: 'user', text: input }]);
      setInput('');

      // Stream assistant response
      let assistantText = '';
      for await (const event of api.streamEventsWebSocket(result.job_id)) {
        const ev = event as EventUpdate;

        if (ev.event_type === 'message') {
          assistantText += ev.payload.text;
          setMessages((prev) => {
            const updated = [...prev];
            if (updated[updated.length - 1]?.role === 'assistant') {
              updated[updated.length - 1].text = assistantText;
            } else {
              updated.push({ role: 'assistant', text: assistantText });
            }
            return updated;
          });
        } else if (ev.event_type === 'result') {
          break;
        }
      }
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'error', text: `Error: ${err}` }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="p-4 max-w-2xl mx-auto flex flex-col h-full">
      <h1 className="text-3xl font-bold mb-4">🧠 Brainstorm</h1>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto mb-4 space-y-3">
        {messages.length === 0 ? (
          <p className="text-gray-500 text-center py-8">Start a brainstorming session...</p>
        ) : (
          messages.map((msg, idx) => (
            <div
              key={idx}
              className={`p-3 rounded-lg ${
                msg.role === 'user'
                  ? 'bg-indigo-100 text-indigo-900 ml-8'
                  : msg.role === 'error'
                  ? 'bg-red-100 text-red-900'
                  : 'bg-gray-100 text-gray-900 mr-8'
              }`}
            >
              {msg.text}
            </div>
          ))
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="space-y-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Your idea, question, or continuation..."
          className="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          rows={2}
          disabled={isLoading}
        />
        <button
          type="submit"
          disabled={isLoading || !input.trim()}
          className="w-full bg-indigo-600 text-white py-2 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {isLoading ? '💭 Thinking...' : '✈️ Send'}
        </button>
      </form>
    </div>
  );
};
