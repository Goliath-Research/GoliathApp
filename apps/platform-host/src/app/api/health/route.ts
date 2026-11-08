import { platformHostRevision, platformHostVersion } from "@/lib/build-info";

export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json({
    status: "ok",
    service: "goliath-platform-host",
    version: platformHostVersion(),
    revision: platformHostRevision(),
    mode: "fixture-static",
    packages: ["@goliath/ui", "@goliath/platform-ui", "@goliath/client"],
    notes: "No database, authentication, or privileged operations.",
  });
}
