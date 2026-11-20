import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export function AppWindow({ title, children, onClose, dirty = false, saving = false, backLabel }: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  dirty?: boolean;
  saving?: boolean;
  backLabel?: string;
}) {
  const id = useId();
  const [minimized, setMinimized] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const closeButton = useRef<HTMLButtonElement>(null);
  const minimizeButton = useRef<HTMLButtonElement>(null);
  const keepEditing = useRef<HTMLButtonElement>(null);
  const windowRef = useRef<HTMLElement>(null);
  const toggleLabel = minimized ? 'Restore ' : 'Minimize ';
  const expandLabel = expanded && !minimized ? 'Restore size of ' : 'Expand ';

  useEffect(() => {
    if (confirmClose) keepEditing.current?.focus();
  }, [confirmClose]);

  function requestClose() {
    if (saving) return;
    if (dirty) setConfirmClose(true);
    else onClose();
  }

  function cancelClose() {
    setConfirmClose(false);
    closeButton.current?.focus();
  }

  function rememberWindow() {
    window.requestAnimationFrame?.(() => windowRef.current?.scrollIntoView?.({ block: 'nearest' }));
  }

  function toggleExpanded() {
    setExpanded(minimized || !expanded);
    setMinimized(false);
    rememberWindow();
  }

  return <section className="app-window" aria-labelledby={id + '-title'} ref={windowRef}
    data-minimized={minimized} data-expanded={expanded && !minimized}
    onKeyDown={event => {
      if (confirmClose && event.key === 'Escape') {
        event.stopPropagation();
        cancelClose();
      }
    }}>
    <header className="app-window-bar">
      <div className="app-window-controls" role="group" aria-label="Window controls">
        <button ref={closeButton} className="window-control window-close" type="button" disabled={saving}
          title={saving ? 'Saving in progress' : 'Close ' + title} aria-label={'Close ' + title} onClick={requestClose}>
          <svg aria-hidden="true" viewBox="0 0 12 12"><path d="m3.5 3.5 5 5m0-5-5 5"/></svg>
        </button>
        <button ref={minimizeButton} className="window-control window-minimize" type="button" aria-controls={id + '-body'} aria-expanded={!minimized}
          title={toggleLabel + title} aria-label={toggleLabel + title} onClick={() => setMinimized(!minimized)}>
          <svg aria-hidden="true" viewBox="0 0 12 12"><path d="M3 6h6"/></svg>
        </button>
        <button className="window-control window-expand" type="button" aria-pressed={expanded && !minimized}
          title={expandLabel + title} aria-label={expandLabel + title} onClick={toggleExpanded}>
          <svg aria-hidden="true" viewBox="0 0 12 12"><path d="M4 3H3v1m5 5h1V8M3 3l2 2m4 4L7 7"/></svg>
        </button>
      </div>
      <span className="app-window-title" id={id + '-title'}>{title}</span>
      {minimized ? <button className="secondary window-text-action" type="button" onClick={() => {
        setMinimized(false);
        rememberWindow();
        minimizeButton.current?.focus();
      }}>Restore window</button> : backLabel && <button className="secondary window-text-action" type="button"
        disabled={saving} onClick={requestClose}>{backLabel}</button>}
    </header>
    {confirmClose && <div className="window-confirmation">
      <p role="alert">Close this window? Unsaved changes in this window will be lost.</p>
      <div className="actions">
        <button className="secondary" ref={keepEditing} type="button" onClick={cancelClose}>Keep editing</button>
        <button className="window-discard" type="button" disabled={saving} onClick={onClose}>Close without saving</button>
      </div>
    </div>}
    <div className="app-window-body" id={id + '-body'} hidden={minimized}>{children}</div>
  </section>;
}
