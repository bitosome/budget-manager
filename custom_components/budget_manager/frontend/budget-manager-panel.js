const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

class BudgetManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._state = null;
    this._year = new Date().getFullYear();
    this._month = null;
    this._loading = false;
    this._error = null;
    this._initialized = false;
    this._defaultViewApplied = false;
    this._currentMonthRequested = false;
    this._hasConnected = false;
    this._listeningForNavigation = false;
    this._handleLocationChanged = () => {
      if (this._isBudgetRoute()) this._showCurrentMonth();
    };
  }

  set hass(value) {
    this._hass = value;
    if (!this._initialized && value) {
      this._initialized = true;
      this._load();
    }
  }

  set narrow(value) {
    this._narrow = value;
  }

  set panel(value) {
    this._panel = value;
  }

  connectedCallback() {
    if (!this._listeningForNavigation) {
      window.addEventListener("location-changed", this._handleLocationChanged);
      window.addEventListener("popstate", this._handleLocationChanged);
      this._listeningForNavigation = true;
    }
    if (this._hasConnected) this._showCurrentMonth();
    this._hasConnected = true;
    this._render();
  }

  disconnectedCallback() {
    window.removeEventListener("location-changed", this._handleLocationChanged);
    window.removeEventListener("popstate", this._handleLocationChanged);
    this._listeningForNavigation = false;
  }

  _isBudgetRoute() {
    return window.location.pathname === "/budget-manager"
      || window.location.pathname.startsWith("/budget-manager/");
  }

  _showCurrentMonth() {
    this._defaultViewApplied = false;
    this._currentMonthRequested = true;
    this._month = null;
    const current = this._state?.current_month;
    if (!current) {
      this._currentMonthRequested = false;
      this._render();
      return;
    }
    const currentYear = Number(current.slice(0, 4));
    if (this._state.months[current]) {
      this._year = currentYear;
      this._month = current;
      this._defaultViewApplied = true;
      this._currentMonthRequested = false;
      this._render();
      return;
    }
    if (!this._loading) this._load(currentYear);
  }

  async _load(year = this._year) {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._error = null;
    this._render();
    try {
      const state = await this._hass.callWS({
        type: "budget_manager/get_state",
        year,
      });
      this._state = state;
      this._year = state.selected_year;
      if (this._month && !state.months[this._month]) this._month = null;
      if (!this._defaultViewApplied || this._currentMonthRequested) {
        if (state.current_month && state.months[state.current_month]) {
          this._month = state.current_month;
          this._year = Number(state.current_month.slice(0, 4));
          this._defaultViewApplied = true;
          this._currentMonthRequested = false;
        } else if (state.current_month) {
          this._currentMonthRequested = true;
        } else if (!state.current_month) {
          this._defaultViewApplied = true;
          this._currentMonthRequested = false;
        }
      }
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._loading = false;
      this._render();
      const current = this._state?.current_month;
      if (this._currentMonthRequested && current && !this._state.months[current]) {
        const currentYear = Number(current.slice(0, 4));
        if (currentYear !== this._year) this._load(currentYear);
      }
    }
  }

  get _canEdit() {
    return Boolean(this._hass?.user?.is_admin);
  }

  _money(value) {
    const currency = this._state?.settings?.currency || "EUR";
    return new Intl.NumberFormat(this._state?.settings?.locale || "en-GB", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
    }).format(Number(value || 0));
  }

  _esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _monthLabel(key) {
    const [year, month] = key.split("-").map(Number);
    return `${MONTH_NAMES[month - 1]} ${year}`;
  }

  _render() {
    if (!this.shadowRoot) return;
    const body = this._error
      ? `<div class="empty error">${this._esc(this._error)}</div>`
      : !this._state
        ? `<div class="empty">Loading budget…</div>`
        : this._month
          ? this._renderMonth(this._state.months[this._month])
          : this._renderYear();

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <div class="app ${this._loading ? "is-loading" : ""}">
        ${this._renderHeader()}
        <main>${body}</main>
        <div id="modal-root"></div>
        <div id="toast" role="status"></div>
      </div>`;
    this._bindEvents();
  }

  _renderHeader() {
    if (!this._state) {
      return `<header><div class="brand"><span class="logo">€</span><div><h1>Budget Manager</h1><p>Local Home Assistant budget</p></div></div></header>`;
    }
    return `
      <header>
        <div class="brand">
          <span class="logo">€</span>
          <div><h1>Budget Manager</h1><p>${this._month ? this._monthLabel(this._month) : `Plan ${this._year}–${this._year + 1}`}</p></div>
        </div>
        <div class="header-actions">
          ${this._month ? `<button class="quiet" data-action="back-year">← Plan view</button>` : ""}
          ${this._canEdit ? `<button class="quiet" data-action="settings">Settings</button>` : ""}
          ${!this._canEdit ? `<span class="read-only">Read only</span>` : ""}
          <button class="quiet" data-action="refresh" title="Refresh">↻</button>
        </div>
      </header>`;
  }

  _renderYear() {
    const yearState = this._state.year;
    return `
      <section class="year-toolbar">
        <div class="year-switcher">
          <button class="icon-button" data-action="prev-year">‹</button>
          <button class="year-button" data-action="choose-year">${this._year}–${this._year + 1}</button>
          <button class="icon-button" data-action="next-year">›</button>
        </div>
        ${this._canEdit ? `<div class="toolbar-actions">
          <button class="quiet" data-action="create-month">＋ Month</button>
          <button class="primary" data-action="create-year">Copy / create year</button>
        </div>` : ""}
      </section>

      ${this._renderThresholdSummary()}

      ${!(this._state.available_months || []).length ? `<section class="empty-plan"><div><span class="eyebrow">Start here</span><h2>No budget data yet</h2><p>Create a month, create a full year, or import a Budget Manager JSON backup from Settings.</p></div>${this._canEdit ? `<button class="primary" data-action="settings">Open settings</button>` : ""}</section>` : ""}

      <section class="month-grid">
        ${yearState.months.map((month) => this._renderMonthCard(month)).join("")}
      </section>

      ${this._renderYearMatrix()}`;
  }

  _metric(label, value, tone = "") {
    return `<article class="metric ${tone}"><span>${label}</span><strong>${this._money(value)}</strong></article>`;
  }

  _renderThresholdSummary() {
    const settings = this._state.settings;
    const green = settings.daily_green_threshold ?? 45;
    const yellow = settings.daily_yellow_threshold ?? 40;
    const savingsTarget = settings.savings_target_threshold ?? 45;
    const savingsFloor = settings.savings_floor_threshold ?? 40;
    return `<section class="threshold-summary">
      <div><span class="threshold-icon rag-icon">RAG</span><p><strong>Daily-money colors</strong><small>Green ≥ ${this._money(green)}/day · Yellow ≥ ${this._money(yellow)}/day · Red below</small></p></div>
      <div><span class="threshold-icon savings-icon">↗</span><p><strong>Automatic savings range</strong><small>${this._money(savingsFloor)}–${this._money(savingsTarget)}/day · planned savings stays unchanged inside the range</small></p>${this._canEdit ? `<button class="threshold-edit" data-action="settings">Adjust</button>` : ""}</div>
    </section>`;
  }

  _renderMonthCard(month) {
    const number = Number(month.month.slice(5));
    if (!month.exists) {
      return `<button class="month-card missing" data-action="create-specific-month" data-month="${month.month}">
        <span class="month-name">${MONTH_NAMES[number - 1]}</span>
        <span class="plus">＋</span><small>Create month</small>
      </button>`;
    }
    return `<button class="month-card" data-action="open-month" data-month="${month.month}">
      <div class="month-card-title"><span class="month-name">${MONTH_NAMES[number - 1]}</span><span>→</span></div>
      <strong class="month-remaining ${month.remaining < 0 ? "negative" : ""}">${this._money(month.remaining)}</strong>
      <dl>
        <div><dt>Income</dt><dd>${this._money(month.expected_income)}</dd></div>
        <div><dt>Expenses</dt><dd>${this._money(month.unpaid_expenses)}</dd></div>
        <div><dt>Per day</dt><dd>${this._money(month.daily_allowance)}</dd></div>
      </dl>
      <span class="item-count">${month.pending_count} open · ${month.paid_count} complete</span>
      <span class="rag-status ${month.rag}">${month.rag} · ${this._money(month.daily_allowance)}/day</span>
    </button>`;
  }

  _renderYearMatrix() {
    const years = [this._year, this._year + 1];
    const months = years.flatMap((year) => Array.from({ length: 12 }, (_, index) => `${year}-${String(index + 1).padStart(2, "0")}`));
    const rows = new Map();
    for (const monthKey of months) {
      const month = this._state.months[monthKey];
      for (const item of month?.items || []) {
        if (!this._itemHasMonthlyValue(item)) continue;
        const key = `${item.kind}:${item.name}`;
        if (!rows.has(key)) rows.set(key, { name: item.name, kind: item.kind, months: {} });
        rows.get(key).months[monthKey] = item;
      }
    }
    const groups = [
      { kind: "income", label: "Expected money in" },
      { kind: "expense", label: "Expenditures" },
      { kind: "savings", label: "Savings" },
    ];
    const ordered = [...rows.values()].sort((a, b) => a.name.localeCompare(b.name));
    if (!ordered.length) return "";
    const renderGroup = (group) => {
      const groupRows = ordered.filter((row) => row.kind === group.kind);
      if (!groupRows.length) return "";
      return `<tr class="matrix-group ${group.kind}"><th colspan="${months.length + 1}"><span class="kind-dot"></span>${group.label}</th></tr>${groupRows.map((row) => `<tr class="${row.kind}">
        <th title="${this._esc(row.name)}"><span class="kind-dot"></span><span>${this._esc(row.name)}</span></th>
        ${months.map((key) => this._matrixCell(row.months[key], key)).join("")}
      </tr>`).join("")}`;
    };
    return `
      <section class="matrix-section">
        <div class="section-title"><div><h2>Plan ${years[0]}–${years[1]}</h2><p>Current year followed by next year, left to right</p></div>
          <div class="rag-legend"><span class="green">≥ ${this._money(this._state.settings.daily_green_threshold)}/day</span><span class="yellow">≥ ${this._money(this._state.settings.daily_yellow_threshold)}/day</span><span class="red">below</span></div>
        </div>
        <div class="matrix-wrap">
          <table class="matrix">
            <colgroup><col class="item-column">${months.map(() => `<col class="month-column">`).join("")}</colgroup>
            <thead>
              <tr class="matrix-years"><th>Year</th>${years.map((year) => `<th colspan="12">${year}</th>`).join("")}</tr>
              <tr><th>Item</th>${months.map((key) => `<th>${MONTH_NAMES[Number(key.slice(5)) - 1].slice(0, 3)}</th>`).join("")}</tr>
            </thead>
            <tbody>
              ${groups.map(renderGroup).join("")}
              <tr class="matrix-group summary"><th colspan="${months.length + 1}">Plan overview</th></tr>
              ${this._matrixSummaryRow("Expected income", months, "expected_income")}
              ${this._matrixSummaryRow("Open expenses", months, "unpaid_expenses")}
              ${this._matrixSummaryRow("Open savings", months, "planned_savings", "savings")}
              ${this._matrixSummaryRow("Forecast remaining", months, "remaining")}
              ${this._matrixSummaryRow("EUR / day", months, "daily_allowance", "rag")}
            </tbody>
          </table>
        </div>
      </section>`;
  }

  _matrixSummaryRow(label, months, key, tone = "") {
    return `<tr class="summary-row ${tone}"><th>${label}</th>${months.map((monthKey) => {
      const summary = this._state.months[monthKey]?.summary;
      if (!summary) return `<td class="blank">—</td>`;
      return `<td class="${tone === "rag" ? `rag-cell ${summary.rag}` : ""}" data-action="open-month" data-month="${monthKey}">${this._money(summary[key])}</td>`;
    }).join("")}</tr>`;
  }

  _matrixCell(item, monthKey) {
    if (!item) return `<td class="blank">—</td>`;
    const complete = item.status === "paid" || item.status === "received";
    const effective = Number(item.effective_amount ?? item.amount);
    const adjusted = item.kind === "savings" && item.dynamic && effective !== Number(item.amount);
    return `<td class="${item.special ? "special" : ""} ${complete ? "complete" : ""}" data-action="open-month" data-month="${monthKey}">
      ${complete ? "✓ " : ""}${this._money(effective)}
      ${adjusted ? `<small>planned ${this._money(item.amount)}</small>` : ""}
      ${item.special ? `<small>${this._esc(item.special_label || "Renewal")}</small>` : ""}
    </td>`;
  }

  _renderMonth(month) {
    if (!month) return `<div class="empty">Month not found.</div>`;
    const summary = month.summary;
    const income = month.items.filter((item) => item.kind === "income" && this._itemHasMonthlyValue(item));
    const expenses = month.items.filter((item) => item.kind === "expense" && this._itemHasMonthlyValue(item));
    const savings = month.items.filter((item) => item.kind === "savings");
    return `
      <section class="month-toolbar">
        <div>
          <span class="eyebrow">Manual account balance</span>
          ${this._canEdit ? `<button class="balance-value" data-action="edit-balance">${this._money(month.account_balance)} <small>edit</small></button>` : `<strong class="balance-value">${this._money(month.account_balance)}</strong>`}
        </div>
        <div class="toolbar-actions">${this._canEdit ? `<button class="quiet" data-action="cycle-settings">Cycle ends ${this._esc(month.payday)}</button><button class="primary" data-action="add-item">＋ Add item</button>` : `<span class="read-only">Cycle ends ${this._esc(month.payday)}</span>`}</div>
      </section>
      ${this._renderThresholdSummary()}
      <section class="metrics">
        ${this._metric("Expected income", summary.expected_income, "income")}
        ${this._metric("Unpaid expenses", summary.unpaid_expenses, "expense")}
        ${this._metric("Open savings", summary.planned_savings, "savings")}
        ${this._metric("Forecast remaining", summary.remaining, summary.remaining < 0 ? "danger" : "good")}
        ${this._metric(`Per day · ${summary.days_divisor} days`, summary.daily_allowance, summary.rag)}
      </section>
      ${this._renderItems("Expected money in", income, "income")}
      ${this._renderItems("Expenditures", expenses, "expense")}
      ${this._renderItems("Savings", savings, "savings")}
      ${this._canEdit ? `<div class="danger-zone"><button class="danger-button" data-action="delete-month">Delete ${this._monthLabel(month.month)}</button></div>` : ""}`;
  }

  _renderItems(title, items, kind) {
    return `<section class="items-section">
      <div class="section-title"><div><h2>${title}</h2><p>${items.filter((item) => item.status === "pending").length} still open</p></div></div>
      <div class="items-list">
        ${items.length ? items.map((item) => this._renderItem(item, kind)).join("") : `<div class="empty-row">No items</div>`}
      </div>
    </section>`;
  }

  _itemHasMonthlyValue(item) {
    if (item.kind === "savings" && item.dynamic) return true;
    return Number(item.effective_amount ?? item.amount ?? 0) > 0;
  }

  _renderItem(item, kind) {
    const complete = item.status === "paid" || item.status === "received";
    const actionLabel = kind === "income" ? (complete ? "Received" : "Mark received") : (complete ? "Paid" : "Mark paid");
    const amount = item.effective_amount ?? item.amount;
    const adjusted = kind === "savings" && item.dynamic && Number(amount) !== Number(item.amount);
    return `<article class="item ${complete ? "complete" : ""}">
      <button class="status-button ${complete ? "done" : ""}" data-action="toggle-status" data-id="${item.id}" data-kind="${kind}" title="${actionLabel}">${complete ? "✓" : ""}</button>
      <div class="item-main">
        <div class="item-title">${this._esc(item.name)} ${item.dynamic && kind === "savings" ? `<span class="badge savings-badge">Auto</span>` : ""} ${item.special ? `<span class="badge">${this._esc(item.special_label || "Renewal")}</span>` : ""}</div>
        <div class="item-meta">
          ${item.due_day ? `Day ${item.due_day}` : "No due day"}
          ${item.category ? ` · ${this._esc(item.category)}` : ""}
          ${item.recurrence !== "single" ? ` · ${this._esc(item.recurrence)} until ${this._esc(item.recurrence_end)}` : " · one-time"}
          ${item.dynamic && kind === "savings" ? ` · target range ${this._money(this._state.settings.savings_floor_threshold ?? 40)}–${this._money(this._state.settings.savings_target_threshold ?? 45)}/day` : ""}
        </div>
      </div>
      <strong class="item-amount">${this._money(amount)}${adjusted ? `<small>planned ${this._money(item.amount)}</small>` : ""}</strong>
      ${this._canEdit ? `<button class="more-button" data-action="edit-item" data-id="${item.id}" title="Edit">•••</button>` : ""}
    </article>`;
  }

  _bindEvents() {
    this.shadowRoot.querySelectorAll("[data-action]").forEach((node) => {
      node.addEventListener("click", (event) => this._handleAction(event));
    });
  }

  async _handleAction(event) {
    const button = event.currentTarget;
    const action = button.dataset.action;
    if (action === "refresh") return this._load();
    if (action === "back-year") { this._month = null; return this._render(); }
    if (action === "prev-year") return this._load(this._year - 1);
    if (action === "next-year") return this._load(this._year + 1);
    if (action === "choose-year") return this._openYearPicker();
    if (action === "settings") return this._openSettings();
    if (action === "open-month") { this._month = button.dataset.month; return this._render(); }
    if (action === "create-month") return this._openCreateMonth();
    if (action === "create-specific-month") return this._openCreateMonth(button.dataset.month);
    if (action === "create-year") return this._openCreateYear();
    if (action === "edit-balance") return this._openBalanceEditor();
    if (action === "cycle-settings") return this._openCycleSettings();
    if (action === "add-item") return this._openItemEditor();
    if (action === "edit-item") return this._openItemEditor(button.dataset.id);
    if (action === "toggle-status") return this._toggleStatus(button.dataset.id, button.dataset.kind);
    if (action === "delete-month") return this._deleteMonth();
  }

  _openSettings() {
    const settings = this._state.settings;
    const fields = `<fieldset class="settings-group"><legend>Daily-money RAG colors</legend><p class="form-help">These values control only the green, yellow, and red display.</p><div class="two-col">
      ${this._field("Green from, EUR/day", "daily_green_threshold", settings.daily_green_threshold ?? 45, "number", "min=0 step=0.01 required")}
      ${this._field("Yellow from, EUR/day", "daily_yellow_threshold", settings.daily_yellow_threshold ?? 40, "number", "min=0 step=0.01 required")}
    </div></fieldset>
    <fieldset class="settings-group"><legend>Automatic savings calculation</legend><p class="form-help">Planned savings is preserved inside this range. Above the target, the excess is added to savings. Below the floor, savings is reduced as far as possible.</p><div class="two-col">
      ${this._field("Target, EUR/day", "savings_target_threshold", settings.savings_target_threshold ?? 45, "number", "min=0 step=0.01 required")}
      ${this._field("Floor, EUR/day", "savings_floor_threshold", settings.savings_floor_threshold ?? 40, "number", "min=0 step=0.01 required")}
    </div></fieldset>
    <section class="data-settings"><div><h3>Import and export</h3><p class="form-help">Export a complete portable backup, or replace this budget with a Budget Manager JSON file.</p></div><div class="data-actions"><button type="button" class="quiet" id="export-json">Export JSON</button><button type="button" class="quiet" id="import-json">Import JSON</button><input type="file" id="import-file" accept="application/json,.json" hidden></div></section>`;
    const modal = this._openModal("Budget settings", fields, "Save settings", async (form) => {
      const green = Number(form.get("daily_green_threshold"));
      const yellow = Number(form.get("daily_yellow_threshold"));
      const savingsTarget = Number(form.get("savings_target_threshold"));
      const savingsFloor = Number(form.get("savings_floor_threshold"));
      if (yellow > green) throw new Error("Yellow threshold cannot exceed green threshold.");
      if (savingsFloor > savingsTarget) throw new Error("Savings floor cannot exceed savings target.");
      await this._hass.callWS({
        type: "budget_manager/update_settings",
        changes: {
          daily_green_threshold: green,
          daily_yellow_threshold: yellow,
          savings_target_threshold: savingsTarget,
          savings_floor_threshold: savingsFloor,
        },
      });
    });
    modal.root.querySelector("#export-json").onclick = () => this._exportData();
    const fileInput = modal.root.querySelector("#import-file");
    modal.root.querySelector("#import-json").onclick = () => fileInput.click();
    fileInput.onchange = async () => {
      if (fileInput.files?.[0]) await this._importData(fileInput.files[0], modal.close);
      fileInput.value = "";
    };
  }

  async _exportData() {
    try {
      const data = await this._hass.callWS({ type: "budget_manager/export_data" });
      const blob = new Blob([`${JSON.stringify(data, null, 2)}\n`], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `budget-manager-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      this._showMessage("Budget export downloaded.");
    } catch (err) {
      this._showError(err);
    }
  }

  async _importData(file, closeModal) {
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error("Import file cannot exceed 10 MB.");
      const document = JSON.parse(await file.text());
      if (!window.confirm("Importing replaces all existing budget months and settings. Continue?")) return;
      await this._hass.callWS({ type: "budget_manager/import_data", document });
      closeModal();
      this._month = null;
      this._year = new Date().getFullYear();
      this._defaultViewApplied = false;
      this._currentMonthRequested = true;
      await this._load(this._year);
      this._showMessage("Budget imported successfully.");
    } catch (err) {
      this._showError(err instanceof SyntaxError ? new Error("The selected file is not valid JSON.") : err);
    }
  }

  _openModal(title, fields, submitLabel, onSubmit, extraButtons = "") {
    const root = this.shadowRoot.getElementById("modal-root");
    root.innerHTML = `<div class="modal-backdrop"><form class="modal" id="modal-form">
      <div class="modal-head"><h2>${title}</h2><button type="button" class="close" id="modal-close">×</button></div>
      <div class="modal-body">${fields}</div>
      <div class="modal-actions">${extraButtons}<button type="button" class="quiet" id="modal-cancel">Cancel</button><button class="primary" type="submit">${submitLabel}</button></div>
    </form></div>`;
    const close = () => { root.innerHTML = ""; };
    root.querySelector("#modal-close").onclick = close;
    root.querySelector("#modal-cancel").onclick = close;
    root.querySelector(".modal-backdrop").onclick = (event) => { if (event.target.classList.contains("modal-backdrop")) close(); };
    root.querySelector("#modal-form").onsubmit = async (event) => {
      event.preventDefault();
      try {
        await onSubmit(new FormData(event.currentTarget));
        close();
        await this._load(this._year);
      } catch (err) {
        this._showError(err);
      }
    };
    return { root, close };
  }

  _field(label, name, value = "", type = "text", attrs = "") {
    return `<label><span>${label}</span><input name="${name}" type="${type}" value="${this._esc(value)}" ${attrs}></label>`;
  }

  _openYearPicker() {
    const options = [...new Set([...(this._state.available_years || []), this._year])].sort();
    this._openModal("View year", `<label><span>Year</span><select name="year">${options.map((year) => `<option ${year === this._year ? "selected" : ""}>${year}</option>`).join("")}</select></label>`, "Open", async (form) => {
      this._month = null;
      await this._load(Number(form.get("year")));
    });
  }

  _openCreateMonth(target = `${this._year}-${String(new Date().getMonth() + 1).padStart(2, "0")}`) {
    const sources = this._state.available_months || Object.keys(this._state.months).sort();
    const fields = `${this._field("Target month", "target", target, "month", "required")}
      <label><span>Copy from</span><select name="source"><option value="">Blank month</option>${sources.map((key) => `<option value="${key}">${this._monthLabel(key)}</option>`).join("")}</select></label>
      <label class="check"><input type="checkbox" name="overwrite"><span>Overwrite target if it exists</span></label>`;
    this._openModal("Create month", fields, "Create month", async (form) => {
      await this._hass.callWS({ type: "budget_manager/create_month", target: form.get("target"), source: form.get("source") || null, overwrite: form.has("overwrite") });
    });
  }

  _openCreateYear() {
    const sourceYears = this._state.available_years || [];
    const fields = `${this._field("Target year", "target_year", this._year + 1, "number", "min=2000 max=2200 required")}
      <label><span>Copy from</span><select name="source_year"><option value="">Blank year</option>${sourceYears.map((year) => `<option value="${year}" ${year === this._year ? "selected" : ""}>${year}</option>`).join("")}</select></label>
      <label class="check"><input type="checkbox" name="overwrite"><span>Overwrite existing target months</span></label>`;
    this._openModal("Create full year", fields, "Create year", async (form) => {
      const targetYear = Number(form.get("target_year"));
      await this._hass.callWS({ type: "budget_manager/create_year", target_year: targetYear, source_year: form.get("source_year") ? Number(form.get("source_year")) : null, overwrite: form.has("overwrite") });
      this._month = null;
      this._year = targetYear;
    });
  }

  _openBalanceEditor() {
    const month = this._state.months[this._month];
    const fields = this._field("Account balance", "account_balance", month.account_balance, "number", "min=0 step=0.01 required");
    this._openModal("Manual account balance", fields, "Save balance", async (form) => {
      await this._hass.callWS({ type: "budget_manager/update_month", month: this._month, changes: { account_balance: Number(form.get("account_balance")) } });
    });
  }

  _openCycleSettings() {
    const month = this._state.months[this._month];
    const fields = `${this._field("Payday / cycle end", "payday", month.payday, "date", "required")}<p class="form-help">The daily allowance uses the inclusive number of days until this date, capped at the number of days in the month.</p>`;
    this._openModal(`${this._monthLabel(this._month)} cycle`, fields, "Save cycle", async (form) => {
      await this._hass.callWS({ type: "budget_manager/update_month", month: this._month, changes: { payday: form.get("payday") } });
    });
  }

  _openItemEditor(itemId = null) {
    const month = this._state.months[this._month];
    const item = itemId ? month.items.find((entry) => entry.id === itemId) : null;
    const endDefault = `${Number(this._month.slice(0, 4)) + 1}-${this._month.slice(5)}-01`;
    const fields = `
      <div class="two-col">
        <label><span>Type</span><select name="kind" id="item-kind"><option value="expense" ${!item || item?.kind === "expense" ? "selected" : ""}>Expenditure</option><option value="income" ${item?.kind === "income" ? "selected" : ""}>Expected income</option><option value="savings" ${item?.kind === "savings" ? "selected" : ""}>Savings</option></select></label>
        ${this._field("Amount", "amount", item?.amount ?? "", "number", "min=0 step=0.01 required")}
      </div>
      ${this._field("Name", "name", item?.name ?? "", "text", "required")}
      <label class="check" id="dynamic-savings"><input type="checkbox" name="dynamic" ${!item || item?.dynamic ? "checked" : ""}><span>Adjust automatically when the daily allowance leaves the acceptable RAG range</span></label>
      <p class="form-help" id="dynamic-savings-help">The amount is the monthly savings plan. It is preserved inside the automatic savings range from Settings and adjusted outside that range. The transfer is frozen when marked paid.</p>
      <div class="two-col">
        ${this._field("Due day", "due_day", item?.due_day ?? "", "number", "min=1 max=31")}
        ${this._field("Category", "category", item?.category ?? "")}
      </div>
      <div class="two-col">
        <label><span>Recurrence</span><select name="recurrence" id="recurrence"><option value="single" ${!item || item.recurrence === "single" ? "selected" : ""}>One-time</option><option value="monthly" ${item?.recurrence === "monthly" ? "selected" : ""}>Every month</option><option value="yearly" ${item?.recurrence === "yearly" ? "selected" : ""}>Every year</option></select></label>
        ${this._field("Recurrence end", "recurrence_end", item?.recurrence_end || endDefault, "date", "")}
      </div>
      ${item?.series_id ? `<label><span>Edit scope</span><select name="scope"><option value="this">Only ${this._monthLabel(this._month)}</option><option value="future">This and future unpaid occurrences</option></select></label>` : ""}
      <label class="check"><input type="checkbox" name="special" ${item?.special ? "checked" : ""}><span>Highlight as renewal / special month</span></label>
      ${this._field("Special label", "special_label", item?.special_label || "Renewal")}
      <label><span>Notes</span><textarea name="notes" rows="3">${this._esc(item?.notes || "")}</textarea></label>`;
    const extra = item ? `<button type="button" class="danger-button" id="delete-item">Delete</button>` : "";
    const modal = this._openModal(item ? "Edit item" : "Add item", fields, item ? "Save" : "Add", async (form) => {
      const recurrence = form.get("recurrence");
      await this._hass.callWS({
        type: "budget_manager/upsert_item",
        month: this._month,
        scope: form.get("scope") || "this",
        item: {
          ...(item || {}),
          name: form.get("name"), kind: form.get("kind"), amount: Number(form.get("amount")),
          due_day: form.get("due_day") ? Number(form.get("due_day")) : null,
          category: form.get("category"), recurrence,
          recurrence_end: recurrence === "single" ? null : form.get("recurrence_end"),
          dynamic: form.has("dynamic"),
          special: form.has("special"), special_label: form.get("special_label"), notes: form.get("notes"),
        },
      });
    }, extra);
    const recurrenceSelect = modal.root.querySelector("#recurrence");
    const endInput = modal.root.querySelector('[name="recurrence_end"]');
    const updateEnd = () => { endInput.disabled = recurrenceSelect.value === "single"; endInput.required = recurrenceSelect.value !== "single"; };
    recurrenceSelect.onchange = updateEnd;
    updateEnd();
    const kindSelect = modal.root.querySelector("#item-kind");
    const dynamicSavings = modal.root.querySelector("#dynamic-savings");
    const dynamicSavingsHelp = modal.root.querySelector("#dynamic-savings-help");
    const amountInput = modal.root.querySelector('[name="amount"]');
    const updateKind = () => {
      const visible = kindSelect.value === "savings";
      dynamicSavings.hidden = !visible;
      dynamicSavingsHelp.hidden = !visible;
      if (visible && amountInput.value === "") amountInput.value = "0";
    };
    kindSelect.onchange = updateKind;
    updateKind();
    if (item) modal.root.querySelector("#delete-item").onclick = async () => {
      const scope = item.series_id && window.confirm("Delete this and all future unpaid occurrences?\n\nOK = future series, Cancel = only this occurrence") ? "future" : "this";
      try {
        await this._hass.callWS({ type: "budget_manager/delete_item", month: this._month, item_id: item.id, scope });
        modal.close();
        await this._load(this._year);
      } catch (err) { this._showError(err); }
    };
  }

  async _toggleStatus(itemId, kind) {
    const item = this._state.months[this._month].items.find((entry) => entry.id === itemId);
    const complete = item.status === "paid" || item.status === "received";
    const status = complete ? "pending" : kind === "income" ? "received" : "paid";
    try {
      await this._hass.callWS({ type: "budget_manager/set_item_status", month: this._month, item_id: itemId, status });
      await this._load(this._year);
    } catch (err) { this._showError(err); }
  }

  async _deleteMonth() {
    if (!window.confirm(`Delete ${this._monthLabel(this._month)} and all of its occurrences?`)) return;
    try {
      await this._hass.callWS({ type: "budget_manager/delete_month", month: this._month });
      this._month = null;
      await this._load(this._year);
    } catch (err) { this._showError(err); }
  }

  _showError(err) {
    this._showToast(err?.message || String(err), false);
  }

  _showMessage(message) {
    this._showToast(message, true);
  }

  _showToast(message, success) {
    const toast = this.shadowRoot.getElementById("toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle("success", success);
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 5000);
  }

  _styles() {
    return `
      :host { --ink: var(--primary-text-color, #18211d); --muted: var(--secondary-text-color, #6d7872); --surface: var(--card-background-color, #fff); --page: var(--primary-background-color, #f4f6f3); --line: rgba(100,120,108,.18); --green: #34785a; --green-soft: #dceee3; --red: #a64a42; --amber: #a36d00; display:block; min-height:100%; color:var(--ink); background:var(--page); font-family:var(--paper-font-body1_-_font-family, system-ui, sans-serif); }
      * { box-sizing:border-box; } button, input, select, textarea { font:inherit; } button { color:inherit; }
      .app { min-height:100vh; } .app.is-loading { cursor:progress; }
      header { position:sticky; top:0; z-index:10; display:flex; align-items:center; justify-content:space-between; gap:20px; padding:18px clamp(18px,4vw,54px); background:color-mix(in srgb, var(--surface) 94%, transparent); border-bottom:1px solid var(--line); backdrop-filter:blur(16px); }
      .brand { display:flex; align-items:center; gap:13px; }.logo { width:43px; height:43px; display:grid; place-items:center; border-radius:13px; background:var(--green); color:white; font-size:24px; font-weight:700; box-shadow:0 8px 18px rgba(52,120,90,.24); }
      h1,h2,p { margin:0; } h1 { font-size:20px; line-height:1.1; } .brand p, .section-title p, .updated { color:var(--muted); font-size:12px; margin-top:4px; }
      .header-actions,.toolbar-actions { display:flex; align-items:center; gap:9px; }.read-only { padding:7px 10px; border-radius:999px; background:var(--line); color:var(--muted); font-size:12px; }
      main { max-width:1500px; margin:0 auto; padding:28px clamp(16px,4vw,54px) 70px; }
      button { border:0; cursor:pointer; }.quiet,.primary,.danger-button { border-radius:10px; padding:10px 14px; font-weight:650; }.quiet { background:var(--surface); border:1px solid var(--line); }.quiet:hover { border-color:var(--green); }.primary { background:var(--green); color:#fff; box-shadow:0 5px 14px rgba(52,120,90,.2); }.danger-button { color:var(--red); background:transparent; border:1px solid color-mix(in srgb, var(--red) 35%, transparent); }
      .year-toolbar,.month-toolbar { display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:22px; }.year-switcher { display:flex; align-items:center; gap:8px; }.icon-button,.year-button { height:46px; border-radius:12px; background:var(--surface); border:1px solid var(--line); }.icon-button { width:46px; font-size:26px; }.year-button { min-width:150px; padding:0 22px; font-size:20px; font-weight:750; }
      .empty-plan { display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:22px; padding:20px; border:1px dashed color-mix(in srgb,var(--green) 45%,var(--line)); border-radius:15px; background:var(--surface); }.empty-plan h2 { margin:5px 0; font-size:18px; }.empty-plan p { color:var(--muted); font-size:12px; }
      .threshold-summary { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:-8px 0 22px; }.threshold-summary > div { display:flex; align-items:center; gap:12px; min-height:66px; padding:12px 14px; border:1px solid var(--line); border-radius:13px; background:var(--surface); }.threshold-summary p { display:grid; gap:4px; }.threshold-summary strong { font-size:12px; }.threshold-summary small { color:var(--muted); font-size:11px; line-height:1.4; }.threshold-icon { flex:0 0 auto; min-width:37px; height:37px; display:grid; place-items:center; padding:0 5px; border-radius:10px; font-size:9px; font-weight:800; }.rag-icon { background:linear-gradient(135deg,#d7eee1 0 33%,#ffedbd 33% 66%,#f7d8d4 66%); color:#31483c; }.savings-icon { background:#dbeaf7; color:#245c88; font-size:18px; }
      .threshold-edit { flex:0 0 auto; margin-left:auto; padding:7px 9px; border-radius:8px; background:var(--page); border:1px solid var(--line); color:var(--green); font-size:10px; font-weight:750; }.threshold-edit:hover { border-color:var(--green); }
      .metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:13px; margin-bottom:25px; }.metric { padding:18px; border:1px solid var(--line); border-radius:15px; background:var(--surface); }.metric span { display:block; color:var(--muted); font-size:12px; margin-bottom:9px; }.metric strong { font-size:clamp(18px,2vw,26px); letter-spacing:-.03em; }.metric.income,.metric.good,.metric.green { border-top:3px solid var(--green); }.metric.expense,.metric.danger,.metric.red { border-top:3px solid var(--red); }.metric.warning,.metric.yellow { border-top:3px solid #d19a2e; }.metric.savings { border-top:3px solid #3976a8; }
      .month-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:13px; margin-bottom:34px; }.month-card { text-align:left; min-height:210px; padding:18px; border-radius:16px; border:1px solid var(--line); background:var(--surface); transition:.16s ease; }.month-card:hover { transform:translateY(-2px); border-color:var(--green); box-shadow:0 10px 26px rgba(30,60,44,.08); }.month-card-title { display:flex; justify-content:space-between; font-weight:700; }.month-remaining { display:block; margin:17px 0; font-size:24px; }.negative { color:var(--red); }.month-card dl { margin:0; display:grid; gap:6px; }.month-card dl div { display:flex; justify-content:space-between; font-size:12px; }.month-card dt { color:var(--muted); }.month-card dd { margin:0; }.item-count { display:block; margin-top:13px; padding-top:10px; border-top:1px solid var(--line); color:var(--muted); font-size:11px; }.rag-status { display:inline-block; margin-top:9px; padding:4px 8px; border-radius:999px; font-size:10px; font-weight:750; text-transform:uppercase; }.rag-status.green,.rag-pill.green,.rag-cell.green { background:#d7eee1; color:#185d3d; }.rag-status.yellow,.rag-pill.yellow,.rag-cell.yellow { background:#ffedbd; color:#765300; }.rag-status.red,.rag-pill.red,.rag-cell.red { background:#f7d8d4; color:#8e312a; }.month-card.missing { display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; border-style:dashed; color:var(--muted); }.missing .month-name { align-self:flex-start; color:var(--ink); }.missing .plus { font-size:28px; margin-top:auto; }.missing small { margin-bottom:auto; }
      .matrix-section,.items-section { background:var(--surface); border:1px solid var(--line); border-radius:17px; overflow:hidden; margin-top:20px; }.section-title { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding:19px 21px; border-bottom:1px solid var(--line); }.section-title h2 { font-size:17px; }.rag-legend { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:6px; }.rag-legend span,.rag-pill { padding:5px 8px; border-radius:999px; font-size:10px; font-weight:700; }.matrix-wrap { overflow:auto; max-height:70vh; }.matrix { border-collapse:separate; border-spacing:0; table-layout:fixed; width:100%; min-width:1980px; font-size:11px; }.matrix .item-column { width:205px; }.matrix th,.matrix td { padding:9px 6px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; text-align:right; }.matrix thead th { position:sticky; top:0; z-index:2; background:color-mix(in srgb,var(--surface) 92%,var(--green-soft)); color:var(--muted); }.matrix thead .matrix-years th { top:0; background:color-mix(in srgb,var(--green-soft) 68%,var(--surface)); color:var(--ink); text-align:center; font-size:13px; font-weight:800; }.matrix thead .matrix-years + tr th { top:35px; }.matrix th:first-child { position:sticky; left:0; z-index:3; text-align:left; background:var(--surface); }.matrix thead th:first-child { z-index:4; }.matrix td { cursor:pointer; }.matrix td:hover { outline:2px solid var(--green); outline-offset:-2px; }.matrix .blank { color:var(--muted); }.matrix .special { background:#fff3be; color:#624900; font-weight:700; }.matrix .complete { opacity:.58; text-decoration:line-through; }.matrix td small { display:block; font-size:9px; text-decoration:none; }.kind-dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:8px; background:var(--red); }.income .kind-dot { background:var(--green); }.savings .kind-dot { background:#3976a8; }.matrix-group th { position:static !important; padding:7px 10px; background:color-mix(in srgb,var(--surface) 90%,var(--page)) !important; color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.07em; }.matrix-group.summary th { background:color-mix(in srgb,var(--green-soft) 55%,var(--surface)) !important; color:var(--ink); }.summary-row th,.summary-row td { font-weight:700; }.summary-row.savings td { color:#2d6798; }
      .eyebrow { display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.08em; }.balance-value { margin-top:5px; padding:0; background:transparent; font-size:32px; font-weight:760; letter-spacing:-.04em; }.balance-value small { font-size:11px; color:var(--green); margin-left:7px; }.items-list { display:grid; }.item { min-height:70px; display:grid; grid-template-columns:36px minmax(0,1fr) auto 34px; gap:13px; align-items:center; padding:12px 17px; border-bottom:1px solid var(--line); }.item:last-child { border-bottom:0; }.item.complete { opacity:.58; }.status-button { width:31px; height:31px; border:2px solid var(--line); border-radius:10px; background:transparent; color:white; font-weight:800; }.status-button.done { background:var(--green); border-color:var(--green); }.item-title { font-weight:680; }.item-meta { color:var(--muted); font-size:11px; margin-top:4px; }.item-amount { font-size:16px; text-align:right; }.item-amount small { display:block; margin-top:3px; color:var(--muted); font-size:9px; font-weight:500; }.more-button { width:34px; height:34px; border-radius:9px; background:transparent; color:var(--muted); }.more-button:hover { background:var(--line); }.badge { display:inline-block; padding:3px 7px; margin-left:7px; border-radius:999px; background:#ffe894; color:#6e5100; font-size:9px; text-transform:uppercase; letter-spacing:.04em; }.badge.savings-badge { background:#dbeaf7; color:#245c88; }.empty-row,.empty { padding:34px; text-align:center; color:var(--muted); }.empty.error { color:var(--red); }.danger-zone { display:flex; justify-content:flex-end; margin-top:26px; }
      .form-help { color:var(--muted); line-height:1.55; }
      .balance-value { display:block; }
      .modal-backdrop { position:fixed; inset:0; z-index:100; display:grid; place-items:center; padding:18px; background:rgba(10,18,14,.54); backdrop-filter:blur(4px); }.modal { width:min(590px,100%); max-height:90vh; display:flex; flex-direction:column; background:var(--surface); border-radius:18px; box-shadow:0 30px 90px rgba(0,0,0,.3); overflow:hidden; }.modal-head,.modal-actions { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:17px 20px; border-bottom:1px solid var(--line); }.modal-head h2 { font-size:18px; }.close { width:35px; height:35px; border-radius:50%; background:var(--line); font-size:24px; }.modal-body { padding:20px; overflow:auto; display:grid; gap:15px; }.modal-actions { border-top:1px solid var(--line); border-bottom:0; justify-content:flex-end; }.modal-actions .danger-button { margin-right:auto; }.modal label { display:grid; gap:7px; color:var(--muted); font-size:12px; }.modal input,.modal select,.modal textarea { width:100%; padding:11px 12px; color:var(--ink); background:var(--page); border:1px solid var(--line); border-radius:10px; outline:none; }.modal input:focus,.modal select:focus,.modal textarea:focus { border-color:var(--green); box-shadow:0 0 0 3px color-mix(in srgb,var(--green) 15%,transparent); }.two-col { display:grid; grid-template-columns:1fr 1fr; gap:13px; }.modal .check { display:flex; flex-direction:row; align-items:center; }.modal .check input { width:auto; }
      .settings-group { min-width:0; display:grid; gap:11px; margin:0; padding:16px; border:1px solid var(--line); border-radius:14px; }.settings-group legend { padding:0 6px; font-size:13px; font-weight:750; }.settings-group .form-help { font-size:11px; }.data-settings { display:flex; align-items:center; justify-content:space-between; gap:14px; padding:16px; border:1px solid var(--line); border-radius:14px; }.data-settings h3 { margin:0 0 5px; font-size:13px; }.data-settings .form-help { font-size:11px; }.data-actions { display:flex; flex:0 0 auto; gap:8px; }
      #toast { position:fixed; right:20px; bottom:20px; z-index:200; max-width:420px; padding:13px 16px; border-radius:11px; background:#8d332d; color:white; transform:translateY(130%); transition:.2s ease; box-shadow:0 10px 30px rgba(0,0,0,.25); }#toast.success { background:var(--green); }#toast.show { transform:translateY(0); }
      @media (max-width:1000px) { .month-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }.metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } }
      @media (max-width:700px) { header { padding:13px 15px; }.brand p { display:none; } h1 { font-size:17px; } main { padding:18px 12px 50px; }.year-toolbar,.month-toolbar,.empty-plan { align-items:flex-start; flex-direction:column; }.toolbar-actions { width:100%; }.toolbar-actions button { flex:1; }.month-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.metrics { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }.metric { padding:14px; }.month-card { min-height:190px; padding:14px; }.item { grid-template-columns:34px minmax(0,1fr) auto; }.more-button { grid-column:3; grid-row:1; }.item-amount { grid-column:3; grid-row:2; }.two-col { grid-template-columns:1fr; }.section-title { flex-direction:column; }.rag-legend { justify-content:flex-start; }.threshold-summary { grid-template-columns:1fr; }.data-settings { align-items:flex-start; flex-direction:column; }.data-actions { width:100%; }.data-actions button { flex:1; } }
      @media (max-width:430px) { .month-grid { grid-template-columns:1fr; }.metrics { grid-template-columns:1fr 1fr; }.metric strong { font-size:17px; }.header-actions .quiet:not(:last-child) { display:none; } }
    `;
  }
}

customElements.define("budget-manager-panel", BudgetManagerPanel);
