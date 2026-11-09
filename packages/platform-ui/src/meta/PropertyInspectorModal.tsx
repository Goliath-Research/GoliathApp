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
};

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

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

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
            {breadcrumb.join(" › ")}
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
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
