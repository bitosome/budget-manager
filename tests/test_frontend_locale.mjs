import assert from "node:assert/strict";

globalThis.window = {
  localStorage: { getItem: () => null, setItem: () => {} },
  matchMedia: () => ({ matches: false }),
  navigator: { language: "en-GB" },
  addEventListener: () => {},
  removeEventListener: () => {},
  location: { pathname: "/" },
};
globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = {};
  }
};

let Panel;
globalThis.customElements = {
  get: () => null,
  define: (_name, constructor) => {
    Panel = constructor;
  },
};

await import(
  `../custom_components/budget_manager/frontend/budget-manager-panel.js?locale-test=${Date.now()}`
);

const panel = new Panel();
panel._hass = {
  locale: {
    language: "et",
    date_format: "language",
    time_format: "24",
    time_zone: "server",
  },
  config: { time_zone: "Europe/Tallinn" },
};

assert.equal(panel._formatDate("2026-08-29"), "29.8.2026");
assert.equal(
  panel._formatDateRange("2026-08-29", "2026-08-31"),
  "29.8.2026 – 31.8.2026",
);
assert.match(panel._formatDateTime("2026-01-01T22:30:00Z"), /2\.1\.2026/);
assert.match(panel._formatClockTime("09:30"), /^0?9:30$/);
assert.match(panel._monthLabel("2026-08"), /august 2026/i);

panel._hass.locale = {
  language: "en",
  date_format: "DMY",
  time_format: "12",
  time_zone: "server",
};
assert.equal(panel._formatDate("2026-08-29"), "29/8/2026");
assert.match(panel._formatClockTime("21:30"), /^9:30\s?PM$/i);

panel._matrixEditMode = true;
panel._month = null;
let renderCount = 0;
panel._render = () => { renderCount += 1; };
await panel._handleAction({
  currentTarget: {
    dataset: { action: "open-month", month: "2026-09" },
    closest: (selector) => selector === ".matrix" ? {} : null,
  },
});
assert.equal(panel._month, null);
assert.equal(renderCount, 0);

const existingItem = {
  id: "item-1", name: "Water", kind: "expense", amount: 100,
  income_calculation: null,
};
const refreshedState = {
  selected_year: 2026,
  months: { "2026-09": { items: [{ ...existingItem, amount: 125.5 }] } },
};
const calls = [];
panel._year = 2026;
panel._state = {
  selected_year: 2026,
  months: { "2026-09": { items: [existingItem] } },
};
panel._hass.callWS = async (message) => {
  calls.push(message.type);
  return message.type === "budget_manager/upsert_item"
    ? { ...existingItem, amount: 125.5 }
    : refreshedState;
};
panel._load = () => { throw new Error("Matrix edits must not reload the panel"); };
panel._showMessage = () => {};
const input = {
  value: "125.50",
  disabled: false,
  dataset: {
    saving: "false", original: "100.00", itemId: "item-1",
    month: "2026-09", name: "Water", kind: "expense",
  },
};
await panel._saveMatrixValue(input);
assert.deepEqual(calls, ["budget_manager/upsert_item", "budget_manager/get_state"]);
assert.equal(input.disabled, false);
assert.equal(input.dataset.saving, "false");
assert.equal(input.dataset.original, "125.50");
assert.equal(panel._state, refreshedState);

panel._hass.user = { is_admin: true };
panel._matrixEditMode = true;
panel._showPastMonths = true;
panel._state = {
  current_month: "2026-09",
  settings: {
    currency: "EUR", locale: "en-GB", automatic_savings_enabled: false,
    plan_item_order: { income: [], expense: ["Zulu", "Alpha"] },
  },
  months: {
    "2026-09": {
      items: [
        { id: "alpha", name: "Alpha", kind: "expense", amount: 10, status: "pending" },
        { id: "zulu", name: "Zulu", kind: "expense", amount: 20, status: "pending" },
      ],
    },
  },
};
const matrix = panel._renderYearMatrix();
assert.ok(matrix.indexOf('data-plan-order-name="Zulu"') < matrix.indexOf('data-plan-order-name="Alpha"'));
assert.match(matrix, /data-action="drag-plan-row"/);
assert.match(matrix, /data-action="edit-plan-name"/);
assert.match(matrix, /data-original-name="Zulu"/);
assert.match(matrix, /aria-label="Reorder Zulu"/);
assert.match(matrix, /mdi:drag-horizontal-variant/);
assert.match(matrix, /data-action="open-plan-month" data-month="2026-09"/);
assert.doesNotMatch(matrix, /data-action="open-month"/);
assert.doesNotMatch(panel._renderYear(), /class="month-(card|grid)"/);
assert.match(panel._recurrenceLabel({ recurrence: "custom", recurrence_interval: 3 }), /every 3 months · no end date/);
await panel._handleAction({ currentTarget: {
  dataset: { action: "open-plan-month", month: "2026-09" },
} });
assert.equal(panel._month, "2026-09");
panel._month = null;
panel._matrixEditMode = false;
assert.doesNotMatch(panel._renderYearMatrix(), /<td[^>]+data-action=/);
panel._matrixEditMode = true;

const renameCalls = [];
const renamedPlanState = {
  ...panel._state,
  selected_year: 2026,
  settings: {
    ...panel._state.settings,
    plan_item_order: { income: [], expense: ["Utilities", "Alpha"] },
  },
};
panel._hass.callWS = async (message) => {
  renameCalls.push(message);
  return message.type === "budget_manager/rename_plan_item"
    ? { updated_count: 2 }
    : renamedPlanState;
};
let renameMessage;
panel._showMessage = (message) => { renameMessage = message; };
const nameInput = {
  value: " Utilities ",
  disabled: false,
  dataset: { saving: "false", originalName: "Zulu", kind: "expense" },
};
await panel._savePlanName(nameInput);
assert.deepEqual(renameCalls, [
  {
    type: "budget_manager/rename_plan_item",
    kind: "expense",
    old_name: "Zulu",
    new_name: "Utilities",
  },
  { type: "budget_manager/get_state", year: 2026 },
]);
assert.equal(panel._state, renamedPlanState);
assert.equal(renameMessage, "Renamed 2 occurrences.");

const dragHandles = [{ disabled: false }, { disabled: false }];
let dragRows = ["Zulu", "Alpha"].map((name, index) => ({
  dataset: { planKind: "expense", planOrderName: name },
  querySelector: () => dragHandles[index],
}));
panel.shadowRoot.querySelectorAll = (selector) => selector.includes('data-plan-kind="expense"') ? dragRows : [];
const savedOrders = [];
panel._hass.callWS = async (message) => {
  savedOrders.push(message);
  return { income: [], expense: message.names };
};
panel._showMessage = () => {};
await panel._savePlanRowOrder("expense", ["Alpha", "Zulu"]);
assert.deepEqual(savedOrders[0], {
  type: "budget_manager/update_plan_item_order",
  kind: "expense",
  names: ["Zulu", "Alpha"],
});
assert.deepEqual(panel._state.settings.plan_item_order.expense, ["Zulu", "Alpha"]);
assert.ok(dragHandles.every((handle) => handle.disabled === false));

dragRows = [dragRows[1], dragRows[0]];
await panel._savePlanRowOrder("expense", ["Zulu", "Alpha"]);
assert.deepEqual(savedOrders[1], {
  type: "budget_manager/update_plan_item_order",
  kind: "expense",
  names: ["Alpha", "Zulu"],
});
assert.deepEqual(panel._state.settings.plan_item_order.expense, ["Alpha", "Zulu"]);
assert.ok(dragHandles.every((handle) => handle.disabled === false));

let sortableDestroyed = false;
panel._planSortable = { destroy: () => { sortableDestroyed = true; } };
panel._sortablePlanDrag = { kind: "expense", originalOrder: ["Zulu", "Alpha"] };
panel._destroyPlanSortable();
assert.equal(sortableDestroyed, true);
assert.equal(panel._planSortable, null);
assert.equal(panel._sortablePlanDrag, null);

const styles = panel._styles();
assert.doesNotMatch(styles, /\.care-periods\s*\{[^}]*max-height/);
assert.doesNotMatch(styles, /\.care-periods-head\s*\{[^}]*position:sticky/);
assert.match(styles, /\.care-period-list\s*\{[^}]*flex-direction:column/);

const electricItem = {id:"electric", name:"Electricity",kind:"expense",expense_type:"electricity",amount:120,status:"pending",electricity:{status:"measured",consumption_month:"2026-08"}};
assert.equal(panel._itemHasMonthlyValue({...electricItem, amount:0}), true);
panel._matrixEditMode = true;
const electricCell = panel._matrixCell({months:{"2026-09":electricItem}},electricItem,"2026-09");
assert.match(electricCell, /Measured/);
assert.doesNotMatch(electricCell, /<input|data-action=/);
assert.doesNotMatch(panel._matrixCell({months:{"2026-09":electricItem}},null,"2026-10"), /<input/);

const actionStatus = {textContent:"",setAttribute:()=>{}}, modelStatus = {innerHTML:""};
const actionButtons = [{disabled:false},{disabled:false}];
const actionModal = {root:{querySelector:selector=>selector==='#electricity-action-status'?actionStatus:modelStatus,querySelectorAll:()=>actionButtons},close:()=>assert.fail("Training must not close the dialog")};
panel._load=()=>assert.fail("Training must not reload/scroll the page");
panel._hass.callWS=async()=>({electricity:{model:{samples:3},training:{status:"trained",samples:3,message:"Training completed using 3 completed months",finished_at:"2026-09-06T14:00:00Z",duration_ms:1.25}}});
await panel._runElectricityAction(actionModal,"retrain");
assert.match(actionStatus.textContent,/3 completed months/);
assert.match(modelStatus.innerHTML,/1.25 ms/);
assert.ok(actionButtons.every(button=>!button.disabled));
panel._hass.callWS=async()=>{throw new Error("Recorder unavailable")};
await panel._runElectricityAction(actionModal,"refresh");
assert.equal(actionStatus.textContent,"Failed: Recorder unavailable");
assert.ok(actionButtons.every(button=>!button.disabled));
