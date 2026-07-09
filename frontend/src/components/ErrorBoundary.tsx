import React from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardFooter, Button } from './ui';
import { trackEvent } from '../services/analytics';

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
      return (
        <div className="flex min-h-screen items-center justify-center p-4">
          <Card className="max-w-md">
            <CardHeader>
              <CardTitle>Something went wrong</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-neutral-600 dark:text-neutral-400">
                An unexpected error occurred. Reloading the page usually fixes this; your progress is saved locally.
              </p>
            </CardContent>
            <CardFooter>
              <Button onClick={() => window.location.reload()}>Reload</Button>
            </CardFooter>
          </Card>
        </div>
      );
    }
    return this.props.children;
  }
}
