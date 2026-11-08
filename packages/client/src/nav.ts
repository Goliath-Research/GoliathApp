import type { PlatformObjectKind, PresentationKind } from "@goliath/ui";
import { PLATFORM_GENERIC_KIND, PLATFORM_OBJECT_KINDS } from "@goliath/ui";

/** Row from `portal.sp_session_operator_nav_tree` (via host BFF). */
export type OperatorNavNode = {
  nodeId: number;
  parentId: number | null;
  caption: string;
  seq: number;
  presentationKind: PresentationKind;
};

export function coercePresentationKind(raw: string): PresentationKind {
  if ((PLATFORM_OBJECT_KINDS as readonly string[]).includes(raw)) {
    return raw as PlatformObjectKind;
  }
  if (raw === PLATFORM_GENERIC_KIND) {
    return PLATFORM_GENERIC_KIND;
  }
  return PLATFORM_GENERIC_KIND;
}
