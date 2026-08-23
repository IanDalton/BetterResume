import React from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardFooter, Button } from './ui';
import { trackEvent } from '../services/analytics';
import { detectInitialLang, dictionaries } from '../i18n';

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    trackEvent('error_boundary_catch', { message: error.message, stack: info.componentStack ?? undefined });
  }

  render() {
    if (this.state.error) {
      // This boundary can catch errors thrown by I18nProvider itself, so it cannot
      // rely on useI18n()/context here — resolve a language directly instead.
      const dict = dictionaries[detectInitialLang()];
      return (
        <div className="flex min-h-screen items-center justify-center p-4">
          <Card className="max-w-md">
            <CardHeader>
              <CardTitle>{dict['errorBoundary.title']}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-neutral-600 dark:text-neutral-400">
                {dict['errorBoundary.body']}
              </p>
            </CardContent>
            <CardFooter>
              <Button onClick={() => window.location.reload()}>{dict['errorBoundary.reload']}</Button>
            </CardFooter>
          </Card>
        </div>
      );
    }
    return this.props.children;
  }
}
