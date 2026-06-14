import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';

const theme = localStorage.getItem('svaani-theme') || 'mint';
document.documentElement.dataset.theme = theme;

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
