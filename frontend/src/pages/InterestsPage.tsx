import React, { useEffect, useState } from 'react';
import { api } from '../api/client';

export const InterestsPage: React.FC = () => {
  const [interests, setInterests] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    loadInterests();
  }, []);

  const loadInterests = async () => {
    setIsLoading(true);
    try {
      // TODO: Get interests from backend
      // const result = await api.getInterests(0.3);
      // Stream and parse...
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold mb-4">📊 Your Interests</h1>

      <button
        onClick={loadInterests}
        disabled={isLoading}
        className="mb-4 px-4 py-2 bg-indigo-600 text-white rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50"
      >
        {isLoading ? '🔄 Loading...' : '🔄 Refresh'}
      </button>

      {interests.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          <p>No tracked interests yet.</p>
          <p className="text-sm mt-2">Your interests will appear here as you ask questions and use the assistant.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {interests.map((interest, idx) => (
            <div key={idx} className="p-3 bg-white rounded-lg border border-gray-300">
              <div className="flex justify-between items-center mb-2">
                <h3 className="font-semibold">{interest.label}</h3>
                <span className="text-sm text-gray-600">{(interest.strength * 100).toFixed(0)}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-indigo-600 h-2 rounded-full"
                  style={{ width: `${interest.strength * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-8 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <p className="text-blue-800 text-sm">
          💡 Interests are automatically tracked from your activity and updated based on your interactions.
        </p>
      </div>
    </div>
  );
};
