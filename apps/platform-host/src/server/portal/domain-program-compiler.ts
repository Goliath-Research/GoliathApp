import "server-only";

import { type ChildProcessWithoutNullStreams, spawn } from "node:child_process";

/**
 * Runs the generic DomainProgram compiler (workflow_engine/domain/compile_service.py) on the
 * server. The platform host image ships the compiler under GOLIATH_COMPILER_ROOT (/app/py).
 * Input and output are JSON over stdin/stdout; nothing application-specific lives here.
 */
export class DomainProgramCompileError extends Error {}

const TIMEOUT_MS = 30_000;
const MAX_OUTPUT_BYTES = 4_000_000;

export function compilerCommand(env: NodeJS.ProcessEnv = process.env): {
  command: string;
  args: string[];
  env: Record<string, string>;
} {
  const root = env.GOLIATH_COMPILER_ROOT || "/app/py";
  return {
    command: env.GOLIATH_COMPILER_PYTHON || "python3",
    args: ["-m", "domain.compile_service"],
    env: {
      PATH: env.PATH ?? "/usr/local/bin:/usr/bin:/bin",
      PYTHONPATH: `${root}/workflow_engine:${root}`,
      PYTHONDONTWRITEBYTECODE: "1",
      PYTHONNOUSERSITE: "1",
    },
  };
}

export async function compileDomainProgram(input: Record<string, unknown>): Promise<Record<string, unknown>> {
  const { command, args, env } = compilerCommand();
  return new Promise((resolve, reject) => {
    const child: ChildProcessWithoutNullStreams = spawn(command, args, { env: env as unknown as NodeJS.ProcessEnv });
    let out = "";
    let size = 0;
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new DomainProgramCompileError("the compiler timed out"));
    }, TIMEOUT_MS);
    child.stdout.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_OUTPUT_BYTES) {
        child.kill("SIGKILL");
        return;
      }
      out += chunk.toString("utf8");
    });
    child.stderr.resume();
    child.on("error", () => {
      clearTimeout(timer);
      reject(new DomainProgramCompileError("the compiler is not available on this host"));
    });
    child.on("close", () => {
      clearTimeout(timer);
      let parsed: { ok?: boolean; spec?: Record<string, unknown>; error?: string };
      try {
        parsed = JSON.parse(out.trim().split("\n").pop() || "{}");
      } catch {
        reject(new DomainProgramCompileError("the compiler returned no result"));
        return;
      }
      if (!parsed.ok || !parsed.spec) {
        reject(new DomainProgramCompileError(`compile failed: ${parsed.error ?? "unknown error"}`));
        return;
      }
      resolve(parsed.spec);
    });
    child.stdin.end(JSON.stringify(input));
  });
}
