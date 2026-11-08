import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PLATFORM_OBJECT_KINDS } from "../kinds.js";
import { ObjectBadge } from "./ObjectBadge.js";

describe("ObjectBadge accessibility", () => {
  it("renders visible label and icon for every kind", () => {
    for (const kind of PLATFORM_OBJECT_KINDS) {
      const { unmount } = render(<ObjectBadge kind={kind} fixture />);
      expect(screen.getByText(/\[Fixture\]/)).toBeInTheDocument();
      expect(screen.getByRole("img")).toHaveAccessibleName();
      unmount();
    }
  });

  it("exposes subtitle without replacing primary label", () => {
    render(<ObjectBadge kind="semantic_request" label="List organizations" subtitle="core.list_organizations" />);
    expect(screen.getByText("List organizations")).toBeInTheDocument();
    expect(screen.getByText("core.list_organizations")).toBeInTheDocument();
  });
});
