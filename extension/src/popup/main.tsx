import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';
import '../styles/globals.css';

// The popup is a fixed-width canvas; the dashboard is not. The class is what
// tells the shared stylesheet which one it is rendering into.
document.body.classList.add('sw-popup');

const container = document.getElementById('root');
if (!container) throw new Error('Popup root element is missing.');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
