import type { ReactNode } from "react";

export default function OnboardingLayout({ children }: { children: ReactNode }) {
  return (
    <main className="g-onboarding">
      <div className="g-onboarding__card">{children}</div>
    </main>
  );
}
