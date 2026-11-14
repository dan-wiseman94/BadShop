import { Component, useEffect, useRef, type ReactNode } from "react";

type Props = { name: string; className?: string; children: ReactNode };

function FailedPanel({ name, className, retry }: Omit<Props, "children"> & { retry: () => void }) {
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => { button.current?.focus({ preventScroll: true }); }, []);
  return <section className={className} aria-label={`${name} unavailable`}>
    <div className="error-notice" role="alert">
      <p>{name} could not be displayed. Retrying this view does not repeat your edits.</p>
      <button ref={button} onClick={retry}>Retry {name.toLowerCase()}</button>
    </div>
  </section>;
}

/** Isolate rendering failures without restarting the document or sibling panels. */
export class FeatureBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed
      ? <FailedPanel name={this.props.name} className={this.props.className}
          retry={() => this.setState({ failed: false })} />
      : this.props.children;
  }
}
