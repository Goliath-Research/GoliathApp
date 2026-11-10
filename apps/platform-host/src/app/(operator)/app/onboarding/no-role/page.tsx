import { SignOutButton } from "./SignOutButton";

export default function NoRoleAssignedPage() {
  return (
    <>
      <h1 className="g-onboarding__title">No role assigned</h1>
      <p className="g-onboarding__lead">
        Your account is signed in, but there is no active role grant for this organization scope. Ask a
        platform administrator to assign a role, then sign in again.
      </p>
      <p className="g-onboarding__actions">
        <SignOutButton />
      </p>
    </>
  );
}
