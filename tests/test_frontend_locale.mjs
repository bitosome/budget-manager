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
