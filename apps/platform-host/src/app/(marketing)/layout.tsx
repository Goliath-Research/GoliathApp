import { PlatformHostShell } from "@/components/PlatformHostShell";
import { EXAMPLE_CHILD_EXTENSION } from "@/lib/child-extension";
import { platformHostRevision, platformHostVersion } from "@/lib/build-info";

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  return (
    <PlatformHostShell
      revision={platformHostRevision()}
      version={platformHostVersion()}
      childNav={EXAMPLE_CHILD_EXTENSION.nav}
    >
      {children}
    </PlatformHostShell>
  );
}
