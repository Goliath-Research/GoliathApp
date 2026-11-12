"use client";

import type { ReactNode } from "react";
import { useEffect, useId, useState } from "react";

export type PropertyInspectorModalProps = {
  open: boolean;
  title: string;
  breadcrumb?: readonly string[];
  children: ReactNode;
  onOk: () => void;
  onCancel: () => void;
  okDisabled?: boolean;
  okLabel?: string;
  /** When true, cancel returns to the parent inspector (nested modal stack). */
  nested?: boolean;
};

/**
 * Stack of open inspector modals (innermost last). Nested inspectors open on top of their
 * parent; Escape and the breadcrumb only act on the innermost modal so closing a child
 * returns to its parent instead of dismissing the whole chain.
 */
const openModalStack: string[] = [];

export function isTopmostInspectorModal(id: string): boolean {
  return openModalStack[openModalStack.length - 1] === id;
}

export function PropertyInspectorModal({
  open,
  title,
  breadcrumb,
  children,
  onOk,
  onCancel,
  okDisabled = false,
  okLabel = "OK",
  nested = false,
}: PropertyInspectorModalProps) {
  const titleId = useId();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    openModalStack.push(titleId);
    return () => {
      const idx = openModalStack.lastIndexOf(titleId);
      if (idx >= 0) openModalStack.splice(idx, 1);
    };
  }, [open, titleId]);

  useEffect(() => {
    if (!open || typeof window === "undefined") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isTopmostInspectorModal(titleId)) {
        e.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onCancel, titleId]);

  if (!open || !mounted) return null;

  return (
    <div className="g-property-inspector-modal-backdrop" data-testid="property-inspector-backdrop">
      <button
        type="button"
        className="g-schema-dialog-backdrop__hit"
        aria-label="Close"
        onClick={onCancel}
      />
      <div
        className="g-property-inspector-modal"
        data-testid="property-inspector-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        {breadcrumb && breadcrumb.length > 1 ? (
          <nav className="g-property-inspector-modal__breadcrumb" aria-label="Property path">
            <ol className="g-property-inspector-modal__crumbs" data-depth={breadcrumb.length - 1}>
              {breadcrumb.map((segment, index) => {
                const last = index === breadcrumb.length - 1;
                return (
                  <li key={`${index}:${segment}`} aria-current={last ? "location" : undefined}>
                    {segment}
                  </li>
                );
              })}
            </ol>
          </nav>
        ) : null}
        <h3 id={titleId} className="g-property-inspector-modal__title">
          {title}
        </h3>
        <div className="g-property-inspector-modal__body">{children}</div>
        <div className="g-property-inspector-modal__actions">
          <button
            type="button"
            className="g-host-button g-host-button--primary"
            data-testid="property-inspector-ok"
            disabled={okDisabled}
            onClick={onOk}
          >
            {okLabel}
          </button>
          <button
            type="button"
            className="g-host-button"
            data-testid="property-inspector-cancel"
            onClick={onCancel}
          >
            {nested && breadcrumb && breadcrumb.length > 1
              ? `Back to ${breadcrumb[breadcrumb.length - 2]}`
              : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
