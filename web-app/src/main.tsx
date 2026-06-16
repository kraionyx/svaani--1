import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { applyCustom, loadCustom } from './theme';
import './styles.css';

const theme = localStorage.getItem('svaani-theme') || 'mint';
document.documentElement.dataset.theme = theme;
// Re-apply the saved custom palette before React mounts to avoid a flash of default colors.
if (theme === 'custom') applyCustom(loadCustom());

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
