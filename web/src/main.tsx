/** Entry: fonts, theme CSS, optional mock backend (VITE_MOCK=1), React Query + motion config, router. */
import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import '@fontsource-variable/space-grotesk';
import './index.css';

import { QueryClientProvider } from '@tanstack/react-query';
import { MotionConfig } from 'motion/react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { eventBus, handoffBus } from './lib/bus';
import { queryClient } from './lib/queries';
import { useHQ } from './lib/store';

declare global {
  interface Window {
    /** dev-only debugging handle: `__HQ.store.getState()` */
    __HQ?: { store: typeof useHQ; handoffBus: typeof handoffBus; eventBus: typeof eventBus };
  }
}

async function boot() {
  if (import.meta.env.DEV) window.__HQ = { store: useHQ, handoffBus, eventBus };
  if (import.meta.env.VITE_MOCK === '1') {
    const { installMock } = await import('./lib/mock');
    installMock();
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <MotionConfig reducedMotion="user">
          <App />
        </MotionConfig>
      </QueryClientProvider>
    </StrictMode>,
  );
}

void boot();
