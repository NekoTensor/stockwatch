import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { initTheme } from '../lib/theme';
import App from './App';
import '../styles/globals.css';

const container = document.getElementById('root');
if (!container) throw new Error('Popup root element is missing.');

document.body.classList.add('sw-popup');

// Applied before the first render: doing it in an effect paints the default
// theme and then replaces it, which reads as a flash on every open.
void initTheme().finally(() => {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
