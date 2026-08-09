import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { initTheme } from '../lib/theme';
import App from './App';
import '../styles/globals.css';

const container = document.getElementById('root');
if (!container) throw new Error('Dashboard root element is missing.');

// Applied before the first render, so the page never flashes the wrong theme.
void initTheme().finally(() => {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
