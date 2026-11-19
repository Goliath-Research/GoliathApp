import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import { compilerCommand } from "./domain-program-compiler";

describe("domain program compiler command", () => {
  it("runs the generic compile service with a minimal environment", () => {
    const cmd = compilerCommand({ PATH: "/bin", SECRET_VALUE: "x", GOLIATH_COMPILER_ROOT: "/opt/c" } as never);
    expect(cmd.command).toBe("python3");
    expect(cmd.args).toEqual(["-m", "domain.compile_service"]);
    expect(cmd.env.PYTHONPATH).toBe("/opt/c/workflow_engine:/opt/c");
    expect(Object.keys(cmd.env)).not.toContain("SECRET_VALUE");
  });
});
