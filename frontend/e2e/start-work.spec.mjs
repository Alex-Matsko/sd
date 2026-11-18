import { test, expect } from "@playwright/test";

async function workspace(page, timerFailure = false) {
  const user = { id: 3, full_name: "Тестовый инженер", email: "engineer@example.test", role: "engineer", is_active: true };
  const ticket = {
    id: 15, number: 15, display_number: "OH-000015", subject: "Требуется доступ к 1С Бухгалтерии",
    status: "assigned", channel: "portal", type: "service_request", priority: "P3",
    organization_id: 1, contact_id: 1, tariff_id: 1, contract_id: null, has_no_active_contract: true,
    assigned_engineer_id: 3, team_id: null, category_id: null, asset_id: null,
    planned_due_at: "2020-01-01T10:00:00Z", estimated_minutes: 60,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(), sla: null,
    accepted_at: null, resolution_message_id: null, csat_rating: null,
  };
  let timer = { running: false };
  let submitted = null;
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("sd_access_token", "mock-session"));
  await page.routeWebSocket("**/api/ws/notifications**", () => {});
  await page.route("http://127.0.0.1:4173/api/**", async route => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    const json = (body, status = 200) => route.fulfill({ status, headers: { "Content-Type": "application/json", "X-Total-Count": "1" }, body: JSON.stringify(body) });
    if (path === "/auth/me") return json(user);
    if (path === "/users") return json([user]);
    if (path === "/organizations") return json([{ id: 1, name: "Тестовая организация" }]);
    if (path === "/contacts/1") return json({ id: 1, organization_id: 1, full_name: "Клиент", phones: [], emails: [] });
    if (path === "/tickets/timer/active") return timerFailure ? json({ detail: "Таймер временно недоступен" }, 503) : json(timer);
    if (path === "/tickets/15/timer/start") {
      expect(route.request().method()).toBe("POST");
      submitted = route.request().postDataJSON();
      Object.assign(ticket, submitted, { status: "in_progress" });
      timerFailure = false;
      timer = { running: true, ticket_id: 15, display_number: ticket.display_number, started_at: new Date().toISOString() };
      return json(timer);
    }
    if (path === "/tickets") return json([ticket]);
    if (path === "/tickets/15") return json(ticket);
    if (path === "/tickets/15/reply-options") return json({ preferred_channel: "portal", options: [{ channel: "portal", available: true, destination: "Клиент" }] });
    if (route.request().method() !== "GET") throw new Error("Unexpected mutation: " + path);
    return json([]);
  });
  await page.goto("/tickets?view=kanban");
  await page.locator(".kanban-card-link").click();
  await expect(page.getByRole("dialog", { name: "Карточка заявки" })).toBeVisible();
  return { get submitted() { return submitted; }, errors };
}

test("start work from the kanban drawer accepts a plan and keeps the ticket open", async ({ page }) => {
  const model = await workspace(page);
  await page.getByRole("button", { name: "Начать работу", exact: true }).click();
  const plan = page.getByRole("dialog", { name: "План перед началом работы" });
  await expect(plan).toBeVisible();
  await expect(page.locator("dialog:modal")).toHaveCount(2);
  const due = plan.getByLabel("Выполнить до *", { exact: true });
  await expect(due).toHaveValue("");
  await expect(plan.getByText("Предыдущий срок истёк.", { exact: false })).toBeVisible();
  const future = new Date(Date.now() + 2 * 86400000);
  const local = `${future.getFullYear()}-${String(future.getMonth() + 1).padStart(2, "0")}-${String(future.getDate()).padStart(2, "0")}T16:30`;
  await due.click();
  await due.fill(local);
  await plan.getByLabel("Примерные трудозатраты, ч *", { exact: true }).fill("1.5");
  await plan.getByRole("button", { name: "Подтвердить и начать", exact: true }).click();
  await expect(plan).not.toBeVisible();
  await expect(page.getByRole("dialog", { name: "Карточка заявки" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Остановить таймер", exact: true })).toBeEnabled();
  expect(model.submitted).toEqual({ planned_due_at: new Date(local).toISOString(), estimated_minutes: 90 });
  expect(model.errors).toEqual([]);
});

test("Escape closes only the plan and leaves the kanban ticket unchanged", async ({ page }) => {
  const model = await workspace(page);
  await page.getByRole("button", { name: "Начать работу", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "План перед началом работы" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "План перед началом работы" })).not.toBeVisible();
  await expect(page.getByRole("dialog", { name: "Карточка заявки" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Начать работу", exact: true })).toBeEnabled();
  expect(model.submitted).toBeNull();
  expect(model.errors).toEqual([]);
});

test("a timer polling failure does not disable starting work", async ({ page }) => {
  await workspace(page, true);
  await expect(page.getByText("Не удалось проверить таймер.", { exact: false })).toBeVisible();
  const start = page.getByRole("button", { name: "Начать работу", exact: true });
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByRole("dialog", { name: "План перед началом работы" })).toBeVisible();
});
