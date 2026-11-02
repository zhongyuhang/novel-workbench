import { Component, type ErrorInfo, type ReactNode } from "react";

type ErrorBoundaryProps = {
  title: string;
  children: ReactNode;
};

type ErrorBoundaryState = {
  error: Error | null;
  resetKey: number;
};

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, resetKey: 0 };

  static getDerivedStateFromError(error: Error): Pick<ErrorBoundaryState, "error"> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(this.props.title, error, info.componentStack);
  }

  private retry = () => {
    this.setState((current) => ({ error: null, resetKey: current.resetKey + 1 }));
  };

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="empty" role="alert">
          <p className="empty-title">{this.props.title}暂时打不开</p>
          <p>这一块出了问题，工作区的其他部分还可以继续用。</p>
          <button className="ghost" type="button" onClick={this.retry}>
            重试
          </button>
        </div>
      );
    }
    return <div key={this.state.resetKey}>{this.props.children}</div>;
  }
}
