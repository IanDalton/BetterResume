import React from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/inter';
import App from './App';
import './index.css';
import { I18nProvider } from './i18n';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ToastProvider } from './components/ui';

createRoot(document.getElementById('root')!).render(
	<ErrorBoundary>
		<I18nProvider>
			<ToastProvider>
				<App />
			</ToastProvider>
		</I18nProvider>
	</ErrorBoundary>
);
