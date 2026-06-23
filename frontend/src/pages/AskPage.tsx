import React, { useState } from 'react';
import { api, EventUpdate } from '../api/client';

export const AskPage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [response, setResponse] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setIsLoading(true);
    setError(null);
    setResponse('');

    try {
      // Submit Ask command
      const result = await api.ask(query);
      setJobId(result.job_id);

      // Stream events
      let fullResponse = '';
      for await (const event of api.streamEventsWebSocket(result.job_id)) {
        const ev = event as EventUpdate;

        if (ev.event_type === 'progress') {
          setResponse(`⟳ ${ev.payload.phase}...\n${ev.payload.message}`);
        } else if (ev.event_type === 'message') {
          fullResponse += ev.payload.text;
          setResponse(fullResponse);
        } else if (ev.event_type === 'result') {
          if (!ev.payload.ok) {
            setError(`Error: ${ev.payload.data?.error || 'Unknown error'}`);
          }
          break;
        }
      }
    } catch (err) {
      setError(`Failed to get response: ${err}`);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold mb-4">❓ Ask</h1>

      <form onSubmit={handleSubmit} className="space-y-3">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask your question..."
          className="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          rows={3}
          disabled={isLoading}
        />
        <button
          type="submit"
          disabled={isLoading || !query.trim()}
          className="w-full bg-indigo-600 text-white py-2 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isLoading ? '🔄 Thinking...' : '🔍 Ask'}
        </button>
      </form>

      {error && (
        <div className="mt-4 p-3 bg-red-100 text-red-800 rounded-lg">
          {error}
        </div>
      )}

      {response && (
        <div className="mt-4 p-4 bg-white rounded-lg border border-gray-300">
          <h2 className="font-semibold mb-2">Answer:</h2>
          <p className="whitespace-pre-wrap text-gray-700">{response}</p>
        </div>
      )}
    </div>
  );
};
