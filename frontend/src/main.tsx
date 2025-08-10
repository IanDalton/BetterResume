import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './index.css';
import { I18nProvider } from './i18n';

createRoot(document.getElementById('root')!).render(
	<I18nProvider>
		<App />
	</I18nProvider>
);
