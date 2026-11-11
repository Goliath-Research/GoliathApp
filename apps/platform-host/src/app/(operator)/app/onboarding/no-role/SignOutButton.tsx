"use client";

import { useRouter } from "next/navigation";

export function SignOutButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      className="g-host-button"
      onClick={() => {
        void (async () => {
          await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
          router.push("/login");
          router.refresh();
        })();
      }}
    >
      Sign out
    </button>
  );
}
