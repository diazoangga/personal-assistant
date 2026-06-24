import React, { useState } from 'react';

export const ResearchPage: React.FC = () => {
  const [topic, setTopic] = useState('');
  const [depth, setDepth] = useState<'shallow' | 'normal' | 'deep'>('normal');
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<any>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;

    setIsLoading(true);
    try {
      // TODO: Implement research with graph visualization
      // const jobId = await api.research(topic, depth);
      // Stream events and update graph...
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold mb-4">🔍 Research</h1>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className="block text-sm font-medium mb-1">Topic</label>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="Topic to research..."
            className="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            disabled={isLoading}
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Depth</label>
          <select
            value={depth}
            onChange={(e) => setDepth(e.target.value as any)}
            className="w-full p-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            disabled={isLoading}
          >
            <option value="shallow">Shallow</option>
            <option value="normal">Normal</option>
            <option value="deep">Deep</option>
          </select>
        </div>

        <button
          type="submit"
          disabled={isLoading || !topic.trim()}
          className="w-full bg-indigo-600 text-white py-2 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {isLoading ? '🔄 Researching...' : '🚀 Research'}
        </button>
      </form>

      {result && (
        <div className="mt-4 p-4 bg-white rounded-lg border border-gray-300">
          <h2 className="font-semibold mb-2">Results:</h2>
          <p className="text-gray-700">{JSON.stringify(result, null, 2)}</p>
        </div>
      )}

      <div className="mt-8 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <p className="text-blue-800 text-sm">
          📝 Note: Graph visualization coming soon. This will show the citation and knowledge graphs.
        </p>
      </div>
    </div>
  );
};
