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
  /**
   * Opened from another inspector. Informational: the Back label is derived from the open
   * modal stack, so a first-level inspector always offers Cancel.
   */
  nested?: boolean;
};

/**
 * Stack of open inspector modals (innermost last). Nested inspectors open on top of their
 * parent; Escape and the breadcrumb only act on the innermost modal so closing a child
 * returns to its parent instead of dismissing the whole chain.
 */
const openModalStack: { id: string; label: string }[] = [];

export function isTopmostInspectorModal(id: string): boolean {
  return openModalStack[openModalStack.length - 1]?.id === id;
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
}: PropertyInspectorModalProps) {
  const titleId = useId();
  const [mounted, setMounted] = useState(false);
  /** Label of the inspector this one was opened from (null for a first-level inspector). */
  const [parentLabel, setParentLabel] = useState<string | null>(null);
  const ownLabel = breadcrumb && breadcrumb.length > 0 ? breadcrumb[breadcrumb.length - 1] : title;

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    setParentLabel(openModalStack[openModalStack.length - 1]?.label ?? null);
    openModalStack.push({ id: titleId, label: ownLabel });
    return () => {
      const idx = openModalStack.findIndex((m) => m.id === titleId);
      if (idx >= 0) openModalStack.splice(idx, 1);
    };
    // ownLabel is captured when the modal opens; the stack entry does not need to follow renames.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
            {parentLabel ? `Back to ${parentLabel}` : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
