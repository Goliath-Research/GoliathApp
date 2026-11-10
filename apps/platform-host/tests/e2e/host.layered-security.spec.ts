import { expect, test } from "@playwright/test";

test.describe("layered security (CI postgres)", () => {
  test.skip(
    () => process.env.PLAYWRIGHT_AUTH_E2E !== "1",
    "requires PG seed + dev login (CI frontend job)",
  );

  test("users admin workspace loads", async ({ page }) => {
    await page.goto("/app/admin/users");
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Create / update user" })).toBeVisible();
  });

  test("class grant enables restricted reader", async ({ request }) => {
    const suffix = `${Date.now()}`;
    const roleRes = await request.post("/api/portal/security", {
      data: { action: "create_role", name: `e2e_restricted_${suffix}` },
    });
    expect(roleRes.ok()).toBeTruthy();
    const { roleId } = (await roleRes.json()) as { roleId: number };

    const grantClass = await request.post("/api/portal/security", {
      data: {
        action: "upsert_class_access",
        className: "platform/Person",
        roleId,
        metaAction: "read",
        effect: "allow",
      },
    });
    expect(grantClass.ok()).toBeTruthy();

    const createUser = await request.post("/api/portal/security", {
      data: {
        action: "upsert_user",
        email: `restricted_${suffix}@test`,
        fullName: `Restricted ${suffix}`,
      },
    });
    expect(createUser.ok()).toBeTruthy();
    const { userId } = (await createUser.json()) as { userId: number };

    const grantRole = await request.post("/api/portal/security", {
      data: { action: "grant_user_role", targetUserId: userId, roleId },
    });
    expect(grantRole.ok()).toBeTruthy();

    const createObj = await request.post("/api/meta/classes/platform%2FPerson/objects", {
      data: { document: { Label: `Sec ${suffix}` } },
    });
    expect(createObj.status()).toBe(201);
    const { objId } = (await createObj.json()) as { objId: number };

    const check = await request.post("/api/portal/security", {
      data: {
        action: "effective_check",
        targetUserId: userId,
        className: "platform/Person",
        metaAction: "read",
      },
    });
    expect(check.ok()).toBeTruthy();
    const allowed = (await check.json()) as { allowed: boolean };
    expect(allowed.allowed).toBe(true);

    const denied = await request.post("/api/portal/security", {
      data: {
        action: "upsert_object_access",
        objId,
        userId,
        metaAction: "read",
        effect: "deny",
      },
    });
    expect(denied.ok()).toBeTruthy();
  });
});
