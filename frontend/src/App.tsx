import React, { useEffect, useState } from 'react';
import { AskPage } from './pages/AskPage';
import { BrainstormPage } from './pages/BrainstormPage';
import { InterestsPage } from './pages/InterestsPage';
import { ResearchPage } from './pages/ResearchPage';
import { api } from './api/client';

type Tab = 'ask' | 'brainstorm' | 'research' | 'interests';

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<Tab>('ask');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const initTelegram = () => {
      try {
        // Telegram WebApp SDK is loaded via CDN in index.html
        const tg = (window as any).Telegram?.WebApp;

        if (!tg) {
          console.warn('Telegram WebApp not available. Running in development?');
          // In development, skip auth
          setIsAuthenticated(true);
          return;
        }

        // Initialize WebApp
        tg.ready();

        // Get initData
        const initData = tg.initData;
        if (!initData) {
          console.warn('No initData available');
          setIsAuthenticated(true);
          return;
        }

        // Set initData on API client
        api.setInitData(initData);

        // Authenticate with backend
        api.authenticate()
          .then(() => {
            setIsAuthenticated(true);
            setError(null);
          })
          .catch((authError) => {
            console.error('Authentication failed:', authError);
            setError('Failed to authenticate with backend');
            // Still allow to proceed in dev mode
            setIsAuthenticated(true);
          });
      } catch (err) {
        console.error('Telegram initialization error:', err);
        // In development, we might not have Telegram context
        setIsAuthenticated(true);
      }
    };

    initTelegram();
  }, []);

  if (error && !isAuthenticated) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-red-50">
        <div className="bg-white p-6 rounded-lg shadow-lg">
          <p className="text-red-600 font-semibold">Error: {error}</p>
          <p className="text-gray-600 mt-2 text-sm">Check console for details</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600"></div>
          <p className="mt-4 text-gray-700">Initializing...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* Main Content */}
      <div className="flex-1 overflow-auto pb-16">
        {currentTab === 'ask' && <AskPage />}
        {currentTab === 'brainstorm' && <BrainstormPage />}
        {currentTab === 'research' && <ResearchPage />}
        {currentTab === 'interests' && <InterestsPage />}
      </div>

      {/* Bottom Navigation Tabs */}
      <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 flex">
        <NavTab
          label="Ask"
          icon="❓"
          active={currentTab === 'ask'}
          onClick={() => setCurrentTab('ask')}
        />
        <NavTab
          label="Brainstorm"
          icon="🧠"
          active={currentTab === 'brainstorm'}
          onClick={() => setCurrentTab('brainstorm')}
        />
        <NavTab
          label="Research"
          icon="🔍"
          active={currentTab === 'research'}
          onClick={() => setCurrentTab('research')}
        />
        <NavTab
          label="Interests"
          icon="📊"
          active={currentTab === 'interests'}
          onClick={() => setCurrentTab('interests')}
        />
      </div>
    </div>
  );
};

interface NavTabProps {
  label: string;
  icon: string;
  active: boolean;
  onClick: () => void;
}

const NavTab: React.FC<NavTabProps> = ({ label, icon, active, onClick }) => (
  <button
    onClick={onClick}
    className={`flex-1 py-3 px-2 text-center transition-colors ${
      active ? 'border-t-2 border-indigo-600 text-indigo-600' : 'text-gray-600'
    }`}
  >
    <div className="text-xl mb-1">{icon}</div>
    <div className="text-xs font-medium">{label}</div>
  </button>
);

export default App;
