import { PlatformFixtureDemo } from "@goliath/platform-ui/fixture";

export default function FixturePage() {
  return (
    <>
      <p className="kicker">[Fixture data only]</p>
      <p>
        Rows and navigation below are <strong>static examples</strong> from <code>@goliath/platform-ui</code>. They are
        not schema editors, workflow controls, or live semantic/admin data.
      </p>
      <PlatformFixtureDemo />
    </>
  );
}
