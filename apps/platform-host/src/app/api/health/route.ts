import { platformHostRevision, platformHostVersion } from "@/lib/build-info";

export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json({
    status: "ok",
    service: "goliath-platform-host",
    version: platformHostVersion(),
    revision: platformHostRevision(),
    mode: "p1-bff",
    packages: ["@goliath/ui", "@goliath/platform-ui", "@goliath/client"],
    notes:
      "Public fixture routes; session/nav BFF calls portal SQL when GOLIATH_PORTAL_* is configured. No secrets in this response.",
  });
}
