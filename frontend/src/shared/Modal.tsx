import type { ReactNode } from "react";
import "./ui.css";

type Props = {
  title: string;
  children: ReactNode;
  onClose?: () => void;
  wide?: boolean;
};

/** A focused pop-up over the current screen. Closed only by its own visible buttons. */
export function Modal({ title, children, onClose, wide }: Props) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className={wide ? "modal modal-wide" : "modal"}>
        <header className="modal-head">
          <h2>{title}</h2>
          {onClose && (
            <button className="btn btn-quiet" onClick={onClose}>
              Cancel
            </button>
          )}
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
