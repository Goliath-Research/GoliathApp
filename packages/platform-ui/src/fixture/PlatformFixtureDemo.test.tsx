import "@goliath/ui/styles.css";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FIXTURE_PLATFORM_ROWS } from "./sample-rows.js";
import { PlatformFixtureDemo } from "./PlatformFixtureDemo.js";

describe("PlatformFixtureDemo", () => {
  it("renders fixture table and tree with icons for every row kind", () => {
    render(<PlatformFixtureDemo />);
    expect(screen.getByText(/Platform presentation fixture/)).toBeInTheDocument();
    expect(screen.getAllByRole("img").length).toBeGreaterThanOrEqual(FIXTURE_PLATFORM_ROWS.length);
  });
});
