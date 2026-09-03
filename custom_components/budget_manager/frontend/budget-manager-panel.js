class BudgetManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._state = null;
    this._assignees = [];
    this._year = new Date().getFullYear();
    this._month = null;
    this._loading = false;
    this._error = null;
    this._initialized = false;
    this._defaultViewApplied = false;
    this._currentMonthRequested = false;
    this._hasConnected = false;
    this._listeningForNavigation = false;
    this._stickyFirstColumn = this._loadStickyFirstColumnPreference();
    this._showPastMonths = this._loadShowPastMonthsPreference();
    this._matrixEditMode = false;
    this._handleLocationChanged = () => {
      if (this._isBudgetRoute()) this._showCurrentMonth();
    };
  }

  set hass(value) {
    const previousLocale = this._hass ? JSON.stringify([
      this._hass.locale?.language, this._hass.locale?.date_format,
      this._hass.locale?.time_format, this._hass.locale?.time_zone,
      this._hass.config?.time_zone,
    ]) : null;
    this._hass = value;
    if (!this._initialized && value) {
      this._year = this._currentDateParts().year;
      this._initialized = true;
      this._load();
    } else if (value && previousLocale !== JSON.stringify([
      value.locale?.language, value.locale?.date_format,
      value.locale?.time_format, value.locale?.time_zone,
      value.config?.time_zone,
    ])) {
      this._render();
    }
  }

  set narrow(value) {
    const changed = this._narrow !== Boolean(value);
    this._narrow = Boolean(value);
    if (changed && this._initialized) this._render();
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

  _loadStickyFirstColumnPreference() {
    try {
      const stored = window.localStorage.getItem("budget-manager-sticky-first-column");
      if (stored !== null) return stored === "true";
    } catch (_err) {
      // Storage can be unavailable in restricted browser contexts.
    }
    return !window.matchMedia?.("(max-width: 700px)").matches;
  }

  _toggleStickyFirstColumn() {
    this._stickyFirstColumn = !this._stickyFirstColumn;
    try {
      window.localStorage.setItem("budget-manager-sticky-first-column", String(this._stickyFirstColumn));
    } catch (_err) {
      // Keep the preference for this session when storage is unavailable.
    }
    this._render();
  }

  _loadShowPastMonthsPreference() {
    try {
      const stored = window.localStorage.getItem("budget-manager-show-past-months");
      if (stored !== null) return stored === "true";
    } catch (_err) {
      // Storage can be unavailable in restricted browser contexts.
    }
    return true;
  }

  _togglePastMonths() {
    this._showPastMonths = !this._showPastMonths;
    try {
      window.localStorage.setItem("budget-manager-show-past-months", String(this._showPastMonths));
    } catch (_err) {
      // Keep the preference for this session when storage is unavailable.
    }
    this._render();
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
      const [state, assignees] = await Promise.all([
        this._hass.callWS({ type: "budget_manager/get_state", year }),
        this._canEdit
          ? this._hass.callWS({ type: "budget_manager/notification_assignees" }).catch(() => [])
          : Promise.resolve([]),
      ]);
      this._state = state;
      this._assignees = assignees;
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

  _localeLanguage() {
    return this._hass?.locale?.language
      || this._hass?.language
      || this._state?.settings?.locale
      || window.navigator?.language
      || "en-GB";
  }

  _resolvedTimeZone() {
    if (this._hass?.locale?.time_zone === "local") {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    }
    return this._hass?.config?.time_zone
      || Intl.DateTimeFormat().resolvedOptions().timeZone
      || "UTC";
  }

  _currentDateParts() {
    const parts = new Intl.DateTimeFormat("en-CA", {
      year: "numeric", month: "2-digit", day: "2-digit",
      timeZone: this._resolvedTimeZone(),
    }).formatToParts(new Date());
    const value = (type) => Number(parts.find((part) => part.type === type)?.value || 0);
    return { year: value("year"), month: value("month"), day: value("day") };
  }

  _dateOnly(value) {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12));
  }

  _formatDate(value) {
    const date = this._dateOnly(value);
    if (!date) return String(value || "");
    const locale = this._hass?.locale || {};
    const language = locale.date_format === "system" ? undefined : this._localeLanguage();
    const formatter = new Intl.DateTimeFormat(language, {
      year: "numeric", month: "numeric", day: "numeric", timeZone: "UTC",
    });
    if (!["DMY", "MDY", "YMD"].includes(locale.date_format)) return formatter.format(date);
    const parts = formatter.formatToParts(date);
    const literal = parts.find((part) => part.type === "literal")?.value || "/";
    const values = Object.fromEntries(parts.filter((part) => ["day", "month", "year"].includes(part.type)).map((part) => [part.type, part.value]));
    const order = { DMY: ["day", "month", "year"], MDY: ["month", "day", "year"], YMD: ["year", "month", "day"] }[locale.date_format];
    return order.map((part) => values[part]).join(literal);
  }

  _formatDateRange(start, end) {
    if (!start) return "";
    if (!end || start === end) return this._formatDate(start);
    return `${this._formatDate(start)} – ${this._formatDate(end)}`;
  }

  _formatDateTime(value) {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return String(value || "");
    const locale = this._hass?.locale || {};
    const hourCycle = locale.time_format === "12" ? "h12" : locale.time_format === "24" ? "h23" : undefined;
    const timeZone = this._resolvedTimeZone();
    const dateParts = new Intl.DateTimeFormat("en-CA", {
      year: "numeric", month: "2-digit", day: "2-digit", timeZone,
    }).formatToParts(date);
    const part = (type) => dateParts.find((entry) => entry.type === type)?.value || "";
    const localDate = `${part("year")}-${part("month")}-${part("day")}`;
    const time = new Intl.DateTimeFormat(locale.time_format === "system" ? undefined : this._localeLanguage(), {
      hour: "numeric", minute: "2-digit", hourCycle, timeZone,
    }).format(date);
    return `${this._formatDate(localDate)} ${time}`;
  }

  _formatClockTime(value) {
    const match = String(value || "").match(/^([01]\d|2[0-3]):([0-5]\d)$/);
    if (!match) return String(value || "");
    const locale = this._hass?.locale || {};
    const hourCycle = locale.time_format === "12" ? "h12" : locale.time_format === "24" ? "h23" : undefined;
    return new Intl.DateTimeFormat(locale.time_format === "system" ? undefined : this._localeLanguage(), {
      hour: "numeric", minute: "2-digit", hourCycle, timeZone: "UTC",
    }).format(new Date(Date.UTC(2000, 0, 1, Number(match[1]), Number(match[2]))));
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
    return new Intl.DateTimeFormat(this._localeLanguage(), {
      month: "long", year: "numeric", timeZone: "UTC",
    }).format(new Date(Date.UTC(year, month - 1, 1, 12)));
  }

  _monthName(key, width = "long") {
    const [year, month] = key.split("-").map(Number);
    return new Intl.DateTimeFormat(this._localeLanguage(), {
      month: width, timeZone: "UTC",
    }).format(new Date(Date.UTC(year, month - 1, 1, 12)));
  }

  _incomeWorkingMonth(budgetMonth, workPeriod) {
    if (workPeriod !== "previous_month") return budgetMonth;
    const [year, month] = budgetMonth.split("-").map(Number);
    const previousYear = month === 1 ? year - 1 : year;
    const previousMonth = month === 1 ? 12 : month - 1;
    return `${previousYear}-${String(previousMonth).padStart(2, "0")}`;
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
        <ha-top-app-bar-fixed ${this._narrow ? "narrow" : ""}>
          ${this._renderHeader()}
          <main>${body}</main>
        </ha-top-app-bar-fixed>
        <div id="modal-root"></div>
        <div id="toast" role="status"></div>
      </div>`;
    this._bindEvents();
  }

  _renderHeader() {
    if (!this._state) {
      return `<div slot="title" class="native-title"><strong>Budget Manager</strong><small>Local Home Assistant budget</small></div>`;
    }
    return `
      <div slot="title" class="native-title">
        <strong>Budget Manager</strong>
        <small>${this._month ? this._monthLabel(this._month) : `Plan ${this._year}–${this._year + 1}`}</small>
      </div>
      <div slot="actionItems" class="header-actions ${this._month ? "month-header" : "plan-header"}">
          ${this._month ? `<button class="app-bar-button" data-action="back-year">← Plan</button>` : ""}
          ${this._canEdit ? `<button class="app-bar-button settings-action" data-action="settings">Settings</button>` : ""}
          ${!this._canEdit ? `<span class="read-only">Read only</span>` : ""}
          <button class="app-bar-button refresh-action" data-action="refresh" title="Refresh" aria-label="Refresh">↻</button>
      </div>`;
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
        ${this._canEdit ? `<div class="toolbar-actions"><button class="quiet" data-action="create-month">＋ Month</button>
          <button class="primary" data-action="create-year">Copy / create year</button></div>` : ""}
      </section>

      ${!(this._state.available_months || []).length ? `<section class="empty-plan"><div><span class="eyebrow">Start here</span><h2>No budget data yet</h2><p>Create a month, create a full year, or import a Budget Manager JSON backup from Settings.</p></div>${this._canEdit ? `<button class="primary" data-action="settings">Open settings</button>` : ""}</section>` : ""}

      <section class="month-grid">
        ${yearState.months.map((month) => this._renderMonthCard(month)).join("")}
      </section>

      ${this._renderYearMatrix()}`;
  }

  _metric(label, value, tone = "") {
    return `<article class="metric ${tone}"><span>${label}</span><strong>${this._money(value)}</strong></article>`;
  }

  _renderMonthCard(month) {
    if (!month.exists) {
      return `<button class="month-card missing" data-action="create-specific-month" data-month="${month.month}">
        <span class="month-name">${this._esc(this._monthName(month.month))}</span>
        <span class="plus">＋</span><small>Create month</small>
      </button>`;
    }
    return `<button class="month-card" data-action="open-month" data-month="${month.month}">
      <div class="month-card-title"><span class="month-name">${this._esc(this._monthName(month.month))}</span><span>→</span></div>
      <dl>
        <div><dt>Income</dt><dd>${this._money(month.expected_income)}</dd></div>
        <div><dt>Expenses</dt><dd>${this._money(month.unpaid_expenses)}</dd></div>
      </dl>
      <div class="month-card-footer">
        <span class="item-count">${month.pending_count} open · ${month.paid_count} complete</span>
        <span class="rag-status ${month.rag}" aria-label="Daily allowance ${this._money(month.daily_allowance)} per day">${this._money(month.daily_allowance)}/day</span>
      </div>
    </button>`;
  }

  _renderYearMatrix() {
    const years = [this._year, this._year + 1];
    const allMonths = years.flatMap((year) => Array.from({ length: 12 }, (_, index) => `${year}-${String(index + 1).padStart(2, "0")}`));
    const currentMonth = this._state.current_month;
    const months = this._showPastMonths || !currentMonth
      ? allMonths
      : allMonths.filter((monthKey) => monthKey >= currentMonth);
    const visibleYears = years
      .map((year) => ({ year, count: months.filter((monthKey) => monthKey.startsWith(`${year}-`)).length }))
      .filter(({ count }) => count > 0);
    const matrixActions = `<div class="matrix-title-actions">
      <button class="quiet past-months-toggle ${this._showPastMonths ? "" : "active"}" data-action="toggle-past-months" aria-pressed="${!this._showPastMonths}">${this._showPastMonths ? "Hide past months" : "Show past months"}</button>
      ${this._canEdit ? `<button class="quiet matrix-edit-toggle ${this._matrixEditMode ? "active" : ""}" data-action="toggle-matrix-edit" aria-pressed="${this._matrixEditMode}">${this._matrixEditMode ? "Done editing" : "Edit values"}</button>` : ""}
    </div>`;
    const sectionTitle = `<div class="section-title"><div><h2>Plan ${years[0]}–${years[1]}</h2><p>Current year followed by next year, left to right</p></div>${matrixActions}</div>`;
    const rows = new Map();
    for (const monthKey of months) {
      const month = this._state.months[monthKey];
      for (const item of month?.items || []) {
        if (item.expense_type === "child_care_leave") continue;
        if (!this._itemHasMonthlyValue(item) && !this._matrixEditMode) continue;
        const generatedPeriod = item.generated_type === "tervisekassa_care_benefit"
          ? this._formatDateRange(item.generated?.period_start, item.generated?.period_end)
          : "";
        const rowName = generatedPeriod ? `Tervisekassa care benefit · ${generatedPeriod}` : item.name;
        const key = `${item.kind}:${rowName}`;
        if (!rows.has(key)) rows.set(key, { name: rowName, kind: item.kind, months: {} });
        rows.get(key).months[monthKey] = item;
      }
    }
    const groups = [
      { kind: "income", label: "Expected money in" },
      { kind: "expense", label: "Expenditures" },
      { kind: "savings", label: "Savings" },
    ];
    const ordered = [...rows.values()].sort((a, b) => a.name.localeCompare(b.name));
    if (!ordered.length) {
      if (this._showPastMonths) return "";
      return `<section class="matrix-section ${this._stickyFirstColumn ? "sticky-first-column" : ""}">${sectionTitle}<div class="empty">No planned items in the visible months.</div></section>`;
    }
    const renderGroup = (group) => {
      const groupRows = ordered.filter((row) => row.kind === group.kind);
      if (!groupRows.length) return "";
      return `<tr class="matrix-group ${group.kind}"><th colspan="${months.length + 1}"><span class="kind-dot"></span>${group.label}</th></tr>${groupRows.map((row) => `<tr class="${row.kind}">
        <th title="${this._esc(row.name)}"><span class="kind-dot"></span><span>${this._esc(row.name)}</span></th>
        ${months.map((key) => this._matrixCell(row, row.months[key], key)).join("")}
      </tr>`).join("")}`;
    };
    return `
      <section class="matrix-section ${this._stickyFirstColumn ? "sticky-first-column" : ""}">
        ${sectionTitle}
        <div class="matrix-wrap">
          <table class="matrix" style="min-width:${205 + months.length * 74}px">
            <colgroup><col class="item-column">${months.map(() => `<col class="month-column">`).join("")}</colgroup>
            <thead>
              <tr class="matrix-years"><th>Year</th>${visibleYears.map(({ year, count }) => `<th colspan="${count}">${year}</th>`).join("")}</tr>
              <tr><th><div class="item-heading"><span>Item</span><button class="column-pin-toggle ${this._stickyFirstColumn ? "on" : ""}" data-action="toggle-sticky-column" aria-pressed="${this._stickyFirstColumn}" title="${this._stickyFirstColumn ? "Unpin first column" : "Pin first column"}"><span class="toggle-track" aria-hidden="true"><span class="toggle-thumb"></span></span><span>Sticky</span></button></div></th>${months.map((key) => `<th>${this._esc(this._monthName(key, "short"))}</th>`).join("")}</tr>
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

  _matrixCell(row, item, monthKey) {
    if (this._matrixEditMode && this._canEdit) {
      if (row.kind === "savings" && this._state.settings.automatic_savings_enabled) {
        if (!item) return `<td class="blank" title="Create this budget month to calculate savings">—</td>`;
        const effective = Number(item.effective_amount ?? item.amount);
        return `<td class="matrix-edit-cell automatic-savings-cell" data-action="open-month" data-month="${monthKey}" title="Automatic savings is managed from Settings">${item.automatic_savings ? "Auto" : "Fixed"}<small>${this._money(effective)}</small></td>`;
      }
      const value = item ? Number(item.amount).toFixed(2) : "";
      return `<td class="matrix-edit-cell ${item?.needs_review ? "needs-review" : ""}"><input class="matrix-amount-input" type="number" min="0" step="0.01" inputmode="decimal" value="${value}" data-action="edit-matrix-value" data-month="${monthKey}" data-item-id="${item?.id || ""}" data-name="${this._esc(row.name)}" data-kind="${row.kind}" data-original="${value}" aria-label="${this._esc(row.name)}, ${this._monthLabel(monthKey)} amount"></td>`;
    }
    if (!item) return `<td class="blank">—</td>`;
    const complete = item.status === "paid" || item.status === "received";
    const effective = Number(item.effective_amount ?? item.amount);
    const adjusted = item.kind === "savings" && item.dynamic && !item.automatic_savings && effective !== Number(item.amount);
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
    const expenses = month.items.filter((item) => item.kind === "expense" && (item.expense_type === "child_care_leave" || this._itemHasMonthlyValue(item)));
    const savings = month.items.filter((item) => item.kind === "savings");
    return `
      <section class="month-toolbar">
        <div>
          <span class="eyebrow">Manual account balance</span>
          ${this._canEdit ? `<button class="balance-value" data-action="edit-balance">${this._money(month.account_balance)} <small>edit</small></button>` : `<strong class="balance-value">${this._money(month.account_balance)}</strong>`}
        </div>
        ${this._canEdit ? `<div class="toolbar-actions"><button class="primary" data-action="add-item">＋ Add item</button></div>` : ""}
      </section>
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
      <div class="section-title"><div><h2>${title}</h2><p>${items.filter((item) => item.status === "pending" && item.expense_type !== "child_care_leave").length} still open</p></div></div>
      <div class="items-list">
        ${items.length ? items.map((item) => this._renderItem(item, kind)).join("") : `<div class="empty-row">No items</div>`}
      </div>
    </section>`;
  }

  _itemHasMonthlyValue(item) {
    if (item.needs_review) return true;
    if (item.kind === "savings" && item.dynamic) return true;
    return Number(item.effective_amount ?? item.amount ?? 0) > 0;
  }

  _assigneeName(userId) {
    return this._assignees.find((user) => user.id === userId)?.name || "Unavailable user";
  }

  _renderItem(item, kind) {
    if (item.expense_type === "child_care_leave") {
      const care = item.care_leave || {};
      const periods = care.periods || [];
      const totalBenefit = periods.reduce((total, period) => total + Number(period.calculation?.estimated_net_benefit || 0), 0);
      const totalHours = periods.reduce((total, period) => total + Number(period.calculation?.missed_working_hours || 0), 0);
      return `<article class="item care-leave-item">
        <span class="status-placeholder" aria-hidden="true"></span>
        <div class="item-main">
          <div class="item-title">${this._esc(item.name)} <span class="badge care-badge">Care leave</span></div>
          <div class="item-meta">${periods.length} ${periods.length === 1 ? "period" : "periods"} · ${this._esc(totalHours)} missed work hours · linked to ${this._esc(care.linked_income_name || "hourly income")} in ${this._monthLabel(care.income_month)}</div>
        </div>
        <strong class="item-amount care-benefit-total"><small>Est. benefit</small>${this._money(totalBenefit)}</strong>
        ${this._canEdit ? `<button class="more-button" data-action="edit-item" data-id="${item.id}" title="Manage periods">•••</button>` : ""}
      </article>`;
    }
    const complete = item.status === "paid" || item.status === "received";
    const actionLabel = kind === "income" ? (complete ? "Received" : "Mark received") : (complete ? "Paid" : "Mark paid");
    const amount = item.effective_amount ?? item.amount;
    const adjusted = kind === "savings" && item.dynamic && !item.automatic_savings && Number(amount) !== Number(item.amount);
    const generatedPeriod = item.generated_type === "tervisekassa_care_benefit"
      ? this._formatDateRange(item.generated?.period_start, item.generated?.period_end)
      : "";
    const displayName = generatedPeriod ? `Tervisekassa care benefit · ${generatedPeriod}` : item.name;
    return `<article class="item ${complete ? "complete" : ""} ${item.needs_review ? "needs-review" : ""}">
      <button class="status-button ${complete ? "done" : ""}" data-action="toggle-status" data-id="${item.id}" data-kind="${kind}" title="${actionLabel}">${complete ? "✓" : ""}</button>
      <div class="item-main">
        <div class="item-title">${this._esc(displayName)} ${item.needs_review ? `<span class="badge review-badge">Needs review</span>` : ""} ${item.automatic_savings ? `<span class="badge savings-badge">Calculated</span>` : item.dynamic && kind === "savings" ? `<span class="badge savings-badge">Adjusted</span>` : ""} ${item.generated_type === "tervisekassa_care_benefit" ? `<span class="badge care-badge">Estimated</span>` : ""} ${item.special ? `<span class="badge">${this._esc(item.special_label || "Renewal")}</span>` : ""}</div>
        <div class="item-meta">
          ${item.due_day ? `Day ${item.due_day}` : "No due day"}
          ${item.category ? ` · ${this._esc(item.category)}` : ""}
          ${item.assignee_user_id ? ` · assigned to ${this._esc(this._assigneeName(item.assignee_user_id))} · reminders from ${this._esc(this._formatClockTime(item.reminder_time || "09:00"))}` : ""}
          ${item.recurrence !== "single" ? ` · ${this._esc(item.recurrence)} until ${this._esc(this._formatDate(item.recurrence_end))}` : " · one-time"}
          ${item.income_calculation ? ` · Estonian hourly ${this._money(item.income_calculation.hourly_gross)}/h × ${this._esc(item.income_calculation.working_hours)} h · ${this._monthLabel(item.income_calculation.working_time_month || this._incomeWorkingMonth(this._month, item.income_calculation.work_period))} work period` : ""}
          ${Number(item.income_calculation?.care_leave_hours || 0) > 0 ? ` · ${this._esc(item.income_calculation.care_leave_hours)} care-leave hours deducted · approx. net reduction ${this._money(item.income_calculation.care_leave_net_salary_reduction || 0)}` : ""}
          ${generatedPeriod ? ` · Tervisekassa approximation for ${this._esc(generatedPeriod)}` : ""}
          ${item.automatic_savings ? ` · calculated to leave ${this._money(this._state.settings.savings_target_threshold ?? 45)}/day` : item.dynamic && kind === "savings" ? ` · target range ${this._money(this._state.settings.savings_floor_threshold ?? 40)}–${this._money(this._state.settings.savings_target_threshold ?? 45)}/day` : ""}
        </div>
      </div>
      <strong class="item-amount">${this._money(amount)}${adjusted ? `<small>planned ${this._money(item.amount)}</small>` : ""}</strong>
      ${this._canEdit && item.generated_type !== "tervisekassa_care_benefit" && !(kind === "savings" && this._state.settings.automatic_savings_enabled) ? `<button class="more-button" data-action="edit-item" data-id="${item.id}" title="Edit">•••</button>` : ""}
    </article>`;
  }

  _bindEvents() {
    this.shadowRoot.querySelectorAll('[data-action]:not([data-action="edit-matrix-value"])').forEach((node) => {
      node.addEventListener("click", (event) => this._handleAction(event));
    });
    this.shadowRoot.querySelectorAll('[data-action="edit-matrix-value"]').forEach((input) => {
      input.addEventListener("change", (event) => this._saveMatrixValue(event.currentTarget));
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); }
        if (event.key === "Escape") { event.currentTarget.value = event.currentTarget.dataset.original; event.currentTarget.blur(); }
      });
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
    if (action === "toggle-sticky-column") return this._toggleStickyFirstColumn();
    if (action === "toggle-past-months") return this._togglePastMonths();
    if (action === "toggle-matrix-edit") { this._matrixEditMode = !this._matrixEditMode; return this._render(); }
    if (action === "settings") return this._openSettings();
    if (action === "open-month") { this._month = button.dataset.month; return this._render(); }
    if (action === "create-month") return this._openCreateMonth();
    if (action === "create-specific-month") return this._openCreateMonth(button.dataset.month);
    if (action === "create-year") return this._openCreateYear();
    if (action === "edit-balance") return this._openBalanceEditor();
    if (action === "add-item") return this._openItemEditor();
    if (action === "edit-item") return this._openItemEditor(button.dataset.id);
    if (action === "toggle-status") return this._toggleStatus(button.dataset.id, button.dataset.kind);
    if (action === "delete-month") return this._deleteMonth();
  }

  async _saveMatrixValue(input) {
    if (input.dataset.saving === "true") return;
    const rawValue = input.value.trim();
    const original = input.dataset.original;
    if (!input.dataset.itemId && rawValue === "") return;
    const amount = rawValue === "" ? 0 : Number(rawValue);
    if (!Number.isFinite(amount) || amount < 0) {
      input.value = original;
      return this._showError(new Error("Amount must be a non-negative number."));
    }
    if ((original === "" && amount === 0) || (original !== "" && amount === Number(original))) return;

    const monthKey = input.dataset.month;
    const month = this._state.months[monthKey];
    const existing = input.dataset.itemId
      ? month?.items.find((item) => item.id === input.dataset.itemId)
      : null;
    const wrap = this.shadowRoot.querySelector(".matrix-wrap");
    const scrollLeft = wrap?.scrollLeft || 0;
    const scrollTop = wrap?.scrollTop || 0;
    input.dataset.saving = "true";
    input.disabled = true;
    try {
      if (!month) {
        await this._hass.callWS({
          type: "budget_manager/create_month",
          target: monthKey,
          source: null,
          overwrite: false,
        });
      }
      await this._hass.callWS({
        type: "budget_manager/upsert_item",
        month: monthKey,
        scope: "this",
        item: existing ? {
          ...existing,
          amount,
          income_calculation: existing.kind === "income" ? null : existing.income_calculation,
          needs_review: true,
        } : {
          name: input.dataset.name,
          kind: input.dataset.kind,
          amount,
          due_day: null,
          status: "pending",
          category: "",
          special: false,
          special_label: "",
          notes: "",
          sort_order: 0,
          recurrence: "single",
          recurrence_end: null,
          dynamic: input.dataset.kind === "savings",
          needs_review: true,
        },
      });
      await this._load(this._year);
      const updatedWrap = this.shadowRoot.querySelector(".matrix-wrap");
      if (updatedWrap) {
        updatedWrap.scrollLeft = scrollLeft;
        updatedWrap.scrollTop = scrollTop;
      }
      this._showMessage("Value saved. Review its details in the month view.");
    } catch (err) {
      input.disabled = false;
      input.dataset.saving = "false";
      input.value = original;
      this._showError(err);
    }
  }

  _openSettings() {
    const settings = this._state.settings;
    const fields = `<fieldset class="settings-group"><legend>Budget cycle</legend><p class="form-help">Each budget month runs through this day of the following calendar month. Shorter months are clamped to their last day.</p>
      ${this._field("Cycle end day", "cycle_end_day", settings.cycle_end_day ?? 2, "number", "min=1 max=31 step=1 required")}
    </fieldset>
    <fieldset class="settings-group"><legend>Daily-money RAG colors</legend><p class="form-help">These values control only the green, yellow, and red display.</p><div class="two-col">
      ${this._field("Green from, EUR/day", "daily_green_threshold", settings.daily_green_threshold ?? 45, "number", "min=0 step=0.01 required")}
      ${this._field("Yellow from, EUR/day", "daily_yellow_threshold", settings.daily_yellow_threshold ?? 40, "number", "min=0 step=0.01 required")}
    </div></fieldset>
    <fieldset class="settings-group"><legend>Automatic savings calculation</legend>
      <label class="check"><input type="checkbox" name="automatic_savings_enabled" ${settings.automatic_savings_enabled ? "checked" : ""}><span>Calculate and create the monthly Savings transfer automatically</span></label>
      <p class="form-help">When enabled, every budget month has one system-managed Savings entry. Its value is calculated to leave the target amount per cycle day. An existing Savings entry is reused where possible. Check it after transferring the money from the main account; it then stops affecting daily money. Turn this off before managing savings values manually.</p><div class="two-col">
      ${this._field("Target, EUR/day", "savings_target_threshold", settings.savings_target_threshold ?? 45, "number", "min=0 step=0.01 required")}
      ${this._field("Floor, EUR/day", "savings_floor_threshold", settings.savings_floor_threshold ?? 40, "number", "min=0 step=0.01 required")}
    </div></fieldset>
    <section class="data-settings"><div><h3>Import and export</h3><p class="form-help">Export a complete portable backup, or replace this budget with a Budget Manager JSON file.</p></div><div class="data-actions"><button type="button" class="quiet" id="export-json">Export JSON</button><button type="button" class="quiet" id="import-json">Import JSON</button><input type="file" id="import-file" accept="application/json,.json" hidden></div></section>`;
    const modal = this._openModal("Budget settings", fields, "Save settings", async (form) => {
      const cycleEndDay = Number(form.get("cycle_end_day"));
      const green = Number(form.get("daily_green_threshold"));
      const yellow = Number(form.get("daily_yellow_threshold"));
      const savingsTarget = Number(form.get("savings_target_threshold"));
      const savingsFloor = Number(form.get("savings_floor_threshold"));
      if (yellow > green) throw new Error("Yellow threshold cannot exceed green threshold.");
      if (savingsFloor > savingsTarget) throw new Error("Savings floor cannot exceed savings target.");
      if (!Number.isInteger(cycleEndDay) || cycleEndDay < 1 || cycleEndDay > 31) throw new Error("Cycle end day must be a whole number from 1 to 31.");
      await this._hass.callWS({
        type: "budget_manager/update_settings",
        changes: {
          cycle_end_day: cycleEndDay,
          daily_green_threshold: green,
          daily_yellow_threshold: yellow,
          automatic_savings_enabled: form.has("automatic_savings_enabled"),
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
      const today = this._currentDateParts();
      link.download = `budget-manager-${today.year}-${String(today.month).padStart(2, "0")}-${String(today.day).padStart(2, "0")}.json`;
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
      this._year = this._currentDateParts().year;
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
      <div class="modal-head"><h2>${title}</h2><button type="button" class="close" id="modal-close" aria-label="Close" title="Close"></button></div>
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

  _openCreateMonth(target = `${this._year}-${String(this._currentDateParts().month).padStart(2, "0")}`) {
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

  _careIncomeOptions(workMonth = this._month) {
    const options = [];
    for (const [incomeMonth, month] of Object.entries(this._state.months || {})) {
      for (const item of month.items || []) {
        const calculation = item.income_calculation;
        if (item.kind !== "income" || item.generated_type || !calculation || calculation.working_hours_mode !== "automatic") continue;
        const calculatedWorkMonth = calculation.working_time_month || this._incomeWorkingMonth(incomeMonth, calculation.work_period || "budget_month");
        if (calculatedWorkMonth !== workMonth) continue;
        options.push({ incomeMonth, item });
      }
    }
    return options.sort((left, right) => `${left.incomeMonth}${left.item.name}`.localeCompare(`${right.incomeMonth}${right.item.name}`));
  }

  _careIncomeOptionValue(incomeMonth, itemId) {
    return `${incomeMonth}::${itemId}`;
  }

  _careMonthBounds(monthKey) {
    const [year, month] = monthKey.split("-").map(Number);
    const lastDay = new Date(year, month, 0).getDate();
    return { min: `${monthKey}-01`, max: `${monthKey}-${String(lastDay).padStart(2, "0")}` };
  }

  _openItemEditor(itemId = null) {
    const month = this._state.months[this._month];
    const item = itemId ? month.items.find((entry) => entry.id === itemId) : null;
    if (item?.automatic_savings) return;
    if (item?.expense_type === "child_care_leave") return this._openCareLeaveEditor(item);
    if (item?.generated_type === "tervisekassa_care_benefit") return;
    const incomeCalculation = item?.income_calculation || null;
    const automaticWorkingHours = (incomeCalculation?.working_hours_mode || "automatic") === "automatic";
    const fundedPensionRate = Number(incomeCalculation?.funded_pension_rate || 0);
    const fundedPensionIsJoined = incomeCalculation?.funded_pension_joined ?? (fundedPensionRate > 0);
    const workPeriod = incomeCalculation?.work_period || "budget_month";
    const endDefault = `${Number(this._month.slice(0, 4)) + 1}-${this._month.slice(5)}-01`;
    const careIncomeOptions = this._careIncomeOptions();
    const unavailableAssignee = item?.assignee_user_id && !this._assignees.some((user) => user.id === item.assignee_user_id)
      ? `<option value="${this._esc(item.assignee_user_id)}" selected>Unavailable user</option>`
      : "";
    const assigneeOptions = this._assignees.map((user) => `<option value="${this._esc(user.id)}" ${item?.assignee_user_id === user.id ? "selected" : ""}>${this._esc(user.name)} · ${user.device_count} ${user.device_count === 1 ? "device" : "devices"}</option>`).join("");
    const fields = `
      ${item?.needs_review ? `<div class="review-notice"><strong>Review required</strong><span>This value was entered in the plan table. Check its details; saving this form clears the review flag.</span></div>` : ""}
      <div class="two-col">
        <label><span>Type</span><select name="kind" id="item-kind"><option value="expense" ${!item || item?.kind === "expense" ? "selected" : ""}>Expenditure</option><option value="income" ${item?.kind === "income" ? "selected" : ""}>Expected income</option>${!this._state.settings.automatic_savings_enabled || item?.kind === "savings" ? `<option value="savings" ${item?.kind === "savings" ? "selected" : ""}>Savings</option>` : ""}<option value="care_leave">Child-care sick leave</option></select></label>
        ${this._field("Amount", "amount", item?.amount ?? "", "number", "min=0 step=0.01 required")}
      </div>
      ${this._field("Name", "name", item?.name ?? "", "text", "required")}
      <fieldset class="settings-group care-leave-settings" id="care-leave-settings" hidden>
        <legend>Child-care sick leave</legend>
        ${careIncomeOptions.length ? `<label><span>Salary affected by this leave</span><select name="care_income_link" id="care-income-link" required>${careIncomeOptions.map(({ incomeMonth, item: income }) => `<option value="${this._careIncomeOptionValue(incomeMonth, income.id)}">${this._esc(income.name)} · paid in ${this._monthLabel(incomeMonth)}</option>`).join("")}</select></label>` : `<div class="review-notice"><strong>No eligible income found</strong><span>Create an expected income using automatic Estonian hourly calculation for this work month. If salary is paid afterward, set its work period to the previous month.</span></div>`}
        <label><span>Tervisekassa benefit income basis</span><select name="benefit_basis_mode" id="benefit-basis-mode"><option value="estimated_hourly">Estimate from the selected hourly income</option><option value="actual_previous_year_income">Use actual previous-year social-taxable income</option></select></label>
        <label id="actual-income-field" hidden><span>Previous-year social-taxable income, EUR</span><input type="number" name="actual_previous_year_income" min="0.01" step="0.01" value=""></label>
        <p class="form-help" id="care-basis-help"></p>
        <p class="form-help">After this item is created, open it to add separate care-leave periods with calendar dates. Budget Manager will reduce scheduled working hours only and add one estimated Tervisekassa income per period.</p>
      </fieldset>
      <fieldset class="settings-group income-calculation" id="income-calculation" hidden>
        <legend>Estonian hourly income</legend>
        <label class="check"><input type="checkbox" name="estonian_hourly" id="estonian-hourly" ${incomeCalculation ? "checked" : ""}><span>Calculate monthly net income from an hourly gross rate</span></label>
        <div id="estonian-payroll-fields" hidden>
          <label><span>Working hours are earned in</span><select name="work_period" id="income-work-period"><option value="budget_month" ${workPeriod === "budget_month" ? "selected" : ""}>The same month as this budget</option><option value="previous_month" ${workPeriod === "previous_month" ? "selected" : ""}>The previous month (salary paid afterward)</option></select></label>
          <div class="two-col">
            ${this._field("Hourly gross, EUR", "hourly_gross", incomeCalculation?.hourly_gross ?? "", "number", "min=0.01 step=0.01")}
            ${this._field("Working hours", "working_hours", incomeCalculation?.working_hours ?? "", "number", "min=0.01 step=0.01")}
          </div>
          <label class="check"><input type="checkbox" name="automatic_working_hours" id="automatic-working-hours" ${automaticWorkingHours ? "checked" : ""}><span>Use Estonia's standard monthly working hours automatically</span></label>
          <div class="calendar-source"><span id="working-hours-status">${incomeCalculation ? `${this._monthLabel(incomeCalculation.working_time_month || this._incomeWorkingMonth(this._month, workPeriod))} · ${this._esc(incomeCalculation.working_days || 0)} working days · ${this._esc(incomeCalculation.calendar_source || "stored")}` : "Working hours are loaded when enabled."}</span><button type="button" class="quiet" id="refresh-working-hours">Refresh hours</button></div>
          <label class="check"><input type="checkbox" name="apply_social_tax_minimum" ${incomeCalculation?.apply_social_tax_minimum !== false ? "checked" : ""}><span>Apply the social-tax minimum monthly base (€886)</span></label>
          <div class="tax-free-setting">
            <label class="check"><input type="checkbox" name="apply_tax_free_income" ${incomeCalculation?.apply_tax_free_income !== false ? "checked" : ""}><span>Apply tax-free income</span></label>
            ${this._field("Tax-free income, EUR", "tax_free_income", incomeCalculation?.tax_free_income ?? 700, "number", "min=0 step=0.01")}
          </div>
          <label class="check"><input type="checkbox" name="employee_unemployment" ${incomeCalculation?.employee_unemployment !== false ? "checked" : ""}><span>Employee unemployment insurance (1.6%)</span></label>
          <label class="check"><input type="checkbox" name="employer_unemployment" ${incomeCalculation?.employer_unemployment !== false ? "checked" : ""}><span>Employer unemployment insurance (0.8%)</span></label>
          <label class="check"><input type="checkbox" name="funded_pension_joined" id="funded-pension-joined" ${fundedPensionIsJoined ? "checked" : ""}><span>Joined the funded pension</span></label>
          <div class="pension-rates" role="radiogroup" aria-label="Funded pension contribution rate">
            ${[0, 2, 4, 6].map((rate) => `<label><input type="radio" name="funded_pension_rate" value="${rate}" ${rate === fundedPensionRate ? "checked" : ""}><span>${rate}%</span></label>`).join("")}
          </div>
          <div class="payroll-preview" id="payroll-preview"></div>
          <p class="form-help">Tax calculation uses the latest built-in Estonian rules: 2026 income tax 22%, social tax 33%, and the options above. Future years continue using these known rates until Budget Manager is updated.</p>
        </div>
      </fieldset>
      <label class="check" id="dynamic-savings"><input type="checkbox" name="dynamic" ${!item || item?.dynamic ? "checked" : ""}><span>Adjust automatically when the daily allowance leaves the acceptable RAG range</span></label>
      <p class="form-help" id="dynamic-savings-help">The amount is the monthly savings plan. It is preserved inside the automatic savings range from Settings and adjusted outside that range. The transfer is frozen when marked paid.</p>
      <div class="two-col">
        ${this._field("Due day", "due_day", item?.due_day ?? "", "number", "min=1 max=31")}
        ${this._field("Category", "category", item?.category ?? "")}
      </div>
      <fieldset class="settings-group" id="assignment-settings">
        <legend>Assignment and reminders</legend>
        <div class="two-col">
          <label><span>Assignee</span><select name="assignee_user_id" id="item-assignee"><option value="">Unassigned</option>${unavailableAssignee}${assigneeOptions}</select></label>
          ${this._field("First reminder", "reminder_time", item?.reminder_time || "09:00", "time", "step=60")}
        </div>
        <p class="form-help">Only Home Assistant users with an active Mobile App notification device are listed. A notification is repeated hourly until the item is completed or the due day ends.</p>
      </fieldset>
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
      const selectedKind = form.get("kind");
      const isCareLeave = selectedKind === "care_leave";
      const kind = isCareLeave ? "expense" : selectedKind;
      const useEstonianHourly = kind === "income" && form.has("estonian_hourly");
      const hourlyGross = Number(form.get("hourly_gross"));
      const workingHours = Number(form.get("working_hours"));
      if (useEstonianHourly && (!Number.isFinite(hourlyGross) || hourlyGross <= 0)) throw new Error("Hourly gross must be greater than zero.");
      if (useEstonianHourly && (!Number.isFinite(workingHours) || workingHours <= 0)) throw new Error("Working hours must be greater than zero.");
      const careLink = String(form.get("care_income_link") || "").split("::");
      if (isCareLeave && careLink.length !== 2) throw new Error("Create an automatic Estonian hourly income for this work month before adding care leave.");
      const linkedIncome = isCareLeave ? this._state.months[careLink[0]]?.items.find((entry) => entry.id === careLink[1]) : null;
      const basisMode = String(form.get("benefit_basis_mode") || "estimated_hourly");
      const actualPreviousYearIncome = Number(form.get("actual_previous_year_income") || 0);
      const assigneeUserId = isCareLeave ? "" : String(form.get("assignee_user_id") || "");
      const dueDay = isCareLeave ? null : (form.get("due_day") ? Number(form.get("due_day")) : null);
      if (assigneeUserId && !dueDay) throw new Error("Choose a due day for assigned reminders.");
      if (isCareLeave && basisMode === "actual_previous_year_income" && (!Number.isFinite(actualPreviousYearIncome) || actualPreviousYearIncome <= 0)) throw new Error("Enter the previous calendar year's total social-taxable income.");
      await this._hass.callWS({
        type: "budget_manager/upsert_item",
        month: this._month,
        scope: form.get("scope") || "this",
        item: {
          ...(item || {}),
          name: form.get("name"), kind, amount: isCareLeave ? 0 : Number(form.get("amount")),
          due_day: dueDay,
          assignee_user_id: assigneeUserId || null,
          reminder_time: assigneeUserId ? String(form.get("reminder_time") || "09:00") : null,
          category: isCareLeave ? "Care leave" : form.get("category"), recurrence: isCareLeave ? "single" : recurrence,
          recurrence_end: isCareLeave || recurrence === "single" ? null : form.get("recurrence_end"),
          expense_type: isCareLeave ? "child_care_leave" : "standard",
          care_leave: isCareLeave ? {
            linked_income_item_id: careLink[1],
            linked_income_series_id: linkedIncome?.series_id || "",
            linked_income_name: linkedIncome?.name || "",
            work_month: this._month,
            income_month: careLink[0],
            periods: [],
            benefit_basis_mode: basisMode,
            actual_previous_year_income: basisMode === "actual_previous_year_income" ? actualPreviousYearIncome : 0,
          } : null,
          income_calculation: useEstonianHourly ? {
            mode: "estonian_hourly",
            hourly_gross: hourlyGross,
            working_hours_mode: form.has("automatic_working_hours") ? "automatic" : "manual",
            work_period: form.get("work_period"),
            working_hours: workingHours,
            working_days: Number(modal.root.querySelector("#working-hours-status").dataset.workingDays || 0),
            working_time_month: modal.root.querySelector("#working-hours-status").dataset.workingTimeMonth || this._incomeWorkingMonth(this._month, form.get("work_period")),
            calendar_source: modal.root.querySelector("#working-hours-status").dataset.calendarSource || (form.has("automatic_working_hours") ? "pending" : "manual"),
            apply_social_tax_minimum: form.has("apply_social_tax_minimum"),
            apply_tax_free_income: form.has("apply_tax_free_income"),
            tax_free_income: Number(form.get("tax_free_income")),
            employee_unemployment: form.has("employee_unemployment"),
            employer_unemployment: form.has("employer_unemployment"),
            funded_pension_joined: form.has("funded_pension_joined"),
            funded_pension_rate: form.has("funded_pension_joined") ? Number(form.get("funded_pension_rate")) : 0,
          } : null,
          dynamic: !isCareLeave && form.has("dynamic"),
          needs_review: false,
          special: !isCareLeave && form.has("special"), special_label: form.get("special_label"), notes: form.get("notes"),
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
    const amountLabel = amountInput.closest("label").querySelector("span");
    const nameInput = modal.root.querySelector('[name="name"]');
    const careLeaveSection = modal.root.querySelector("#care-leave-settings");
    const careIncomeLink = modal.root.querySelector("#care-income-link");
    const benefitBasisMode = modal.root.querySelector("#benefit-basis-mode");
    const actualIncomeField = modal.root.querySelector("#actual-income-field");
    const actualIncomeInput = modal.root.querySelector('[name="actual_previous_year_income"]');
    const careBasisHelp = modal.root.querySelector("#care-basis-help");
    const incomeSection = modal.root.querySelector("#income-calculation");
    const estonianHourly = modal.root.querySelector("#estonian-hourly");
    const payrollFields = modal.root.querySelector("#estonian-payroll-fields");
    const automaticHours = modal.root.querySelector("#automatic-working-hours");
    const workPeriodSelect = modal.root.querySelector("#income-work-period");
    const hourlyGrossInput = modal.root.querySelector('[name="hourly_gross"]');
    const workingHoursInput = modal.root.querySelector('[name="working_hours"]');
    const workingHoursStatus = modal.root.querySelector("#working-hours-status");
    const refreshWorkingHours = modal.root.querySelector("#refresh-working-hours");
    const fundedPensionJoined = modal.root.querySelector("#funded-pension-joined");
    const payrollPreview = modal.root.querySelector("#payroll-preview");
    const assignmentSettings = modal.root.querySelector("#assignment-settings");
    const assigneeSelect = modal.root.querySelector("#item-assignee");
    const reminderTimeInput = modal.root.querySelector('[name="reminder_time"]');
    const dueDayInput = modal.root.querySelector('[name="due_day"]');
    const updateAssignment = () => {
      const enabled = kindSelect.value !== "care_leave" && Boolean(assigneeSelect.value);
      reminderTimeInput.disabled = !enabled;
      reminderTimeInput.required = enabled;
      dueDayInput.required = enabled;
    };
    assigneeSelect.onchange = updateAssignment;
    workingHoursStatus.dataset.workingDays = String(incomeCalculation?.working_days || 0);
    workingHoursStatus.dataset.calendarSource = incomeCalculation?.calendar_source || (automaticWorkingHours ? "pending" : "manual");
    workingHoursStatus.dataset.workingTimeMonth = incomeCalculation?.working_time_month || this._incomeWorkingMonth(this._month, workPeriod);
    const roundMoney = (value) => Math.round((Number(value) + Number.EPSILON) * 100) / 100;
    const updatePayrollPreview = () => {
      if (kindSelect.value !== "income" || !estonianHourly.checked) return;
      const hourlyGross = Number(hourlyGrossInput.value);
      const workingHours = Number(workingHoursInput.value);
      if (!Number.isFinite(hourlyGross) || hourlyGross <= 0 || !Number.isFinite(workingHours) || workingHours <= 0) {
        payrollPreview.innerHTML = `<span>Enter an hourly gross rate and working hours to calculate net income.</span>`;
        return;
      }
      const gross = roundMoney(hourlyGross * workingHours);
      const employeeUnemployment = modal.root.querySelector('[name="employee_unemployment"]').checked ? roundMoney(gross * 0.016) : 0;
      const pensionRate = fundedPensionJoined.checked ? Number(modal.root.querySelector('[name="funded_pension_rate"]:checked')?.value || 0) : 0;
      const pension = roundMoney(gross * pensionRate / 100);
      const applyTaxFree = modal.root.querySelector('[name="apply_tax_free_income"]').checked;
      const taxFree = applyTaxFree ? Math.min(gross, Number(modal.root.querySelector('[name="tax_free_income"]').value || 0)) : 0;
      const taxable = Math.max(0, gross - employeeUnemployment - pension - taxFree);
      const incomeTax = roundMoney(taxable * 0.22);
      const net = roundMoney(gross - employeeUnemployment - pension - incomeTax);
      const socialBase = modal.root.querySelector('[name="apply_social_tax_minimum"]').checked ? Math.max(gross, 886) : gross;
      const socialTax = roundMoney(socialBase * 0.33);
      const employerUnemployment = modal.root.querySelector('[name="employer_unemployment"]').checked ? roundMoney(gross * 0.008) : 0;
      const employerCost = roundMoney(gross + socialTax + employerUnemployment);
      amountInput.value = net.toFixed(2);
      payrollPreview.innerHTML = `<div><span>Gross</span><strong>${this._money(gross)}</strong></div><div><span>Net income</span><strong>${this._money(net)}</strong></div><div><span>Income tax</span><strong>${this._money(incomeTax)}</strong></div><div><span>Employer cost</span><strong>${this._money(employerCost)}</strong></div>`;
    };
    const updatePayrollControls = () => {
      const enabled = kindSelect.value === "income" && estonianHourly.checked;
      payrollFields.hidden = !enabled;
      amountInput.readOnly = enabled || kindSelect.value === "care_leave";
      workingHoursInput.readOnly = enabled && automaticHours.checked;
      refreshWorkingHours.hidden = !enabled || !automaticHours.checked;
      fundedPensionJoined.closest("label").classList.toggle("muted", !fundedPensionJoined.checked);
      modal.root.querySelectorAll('[name="funded_pension_rate"]').forEach((radio) => { radio.disabled = !fundedPensionJoined.checked; });
      updatePayrollPreview();
    };
    const loadWorkingHours = async () => {
      if (kindSelect.value !== "income" || !estonianHourly.checked || !automaticHours.checked) return;
      refreshWorkingHours.disabled = true;
      workingHoursStatus.textContent = "Loading Estonia working hours…";
      try {
        const workingTimeMonth = this._incomeWorkingMonth(this._month, workPeriodSelect.value);
        const result = await this._hass.callWS({ type: "budget_manager/estonian_working_hours", month: workingTimeMonth });
        workingHoursInput.value = Number(result.working_hours).toFixed(2);
        workingHoursStatus.dataset.workingDays = String(result.working_days);
        workingHoursStatus.dataset.calendarSource = result.calendar_source;
        workingHoursStatus.dataset.workingTimeMonth = workingTimeMonth;
        const source = result.calendar_source === "nager_date" ? "Nager.Date" : "statutory offline fallback";
        workingHoursStatus.textContent = `${this._monthLabel(workingTimeMonth)} · ${result.working_days} working days · ${result.working_hours} hours · ${source}`;
        updatePayrollPreview();
      } catch (err) {
        workingHoursStatus.textContent = "Working hours could not be refreshed; the server will use its statutory fallback when saving.";
        this._showError(err);
      } finally {
        refreshWorkingHours.disabled = false;
      }
    };
    const updateKind = () => {
      const savingsVisible = kindSelect.value === "savings";
      const careVisible = kindSelect.value === "care_leave";
      dynamicSavings.hidden = !savingsVisible;
      dynamicSavingsHelp.hidden = !savingsVisible;
      incomeSection.hidden = kindSelect.value !== "income";
      careLeaveSection.hidden = !careVisible;
      assignmentSettings.hidden = careVisible;
      assignmentSettings.querySelectorAll("input,select").forEach((control) => { control.disabled = careVisible; });
      careLeaveSection.querySelectorAll("input,select").forEach((control) => { control.disabled = !careVisible; });
      if (careIncomeLink) careIncomeLink.required = careVisible;
      recurrenceSelect.closest(".two-col").hidden = careVisible;
      modal.root.querySelector('[name="due_day"]').closest(".two-col").hidden = careVisible;
      modal.root.querySelector('[name="special"]').closest("label").hidden = careVisible;
      modal.root.querySelector('[name="special_label"]').closest("label").hidden = careVisible;
      if (careVisible) {
        recurrenceSelect.value = "single";
        if (amountInput.dataset.careDisabled !== "true") amountInput.dataset.previousValue = amountInput.value;
        amountInput.dataset.careDisabled = "true";
        amountInput.value = "";
        amountInput.placeholder = "Not applicable";
        amountInput.disabled = true;
        amountLabel.textContent = "Amount · not applicable";
        if (!nameInput.value.trim()) nameInput.value = "Child-care sick leave";
      } else if (amountInput.dataset.careDisabled === "true") {
        amountInput.value = amountInput.dataset.previousValue || "";
        amountInput.placeholder = "";
        amountInput.disabled = false;
        amountInput.dataset.careDisabled = "false";
        amountLabel.textContent = "Amount";
      }
      if (savingsVisible && amountInput.value === "") amountInput.value = "0";
      updateEnd();
      updatePayrollControls();
      updateCareBasis();
      updateAssignment();
    };
    const updateCareBasis = () => {
      const actual = benefitBasisMode.value === "actual_previous_year_income";
      actualIncomeField.hidden = !actual;
      actualIncomeInput.disabled = kindSelect.value !== "care_leave" || !actual;
      actualIncomeInput.required = kindSelect.value === "care_leave" && actual;
      careBasisHelp.textContent = actual
        ? "Enter the previous calendar year's total gross income on which social tax was paid, as reported to MTA. Do not enter net salary or one month's income. Tervisekassa normally divides this annual amount by 365; the result is still shown as an approximation."
        : "Budget Manager approximates the previous calendar year's income from the selected hourly gross rate and Estonia's standard working hours. This is useful for planning but can differ from Tervisekassa's actual source data.";
    };
    kindSelect.onchange = updateKind;
    benefitBasisMode.onchange = updateCareBasis;
    estonianHourly.onchange = () => {
      updatePayrollControls();
      if (estonianHourly.checked && automaticHours.checked && !workingHoursInput.value) loadWorkingHours();
    };
    automaticHours.onchange = () => {
      workingHoursStatus.dataset.calendarSource = automaticHours.checked ? "pending" : "manual";
      updatePayrollControls();
      if (automaticHours.checked) loadWorkingHours();
      else workingHoursStatus.textContent = "Manual working hours";
    };
    workPeriodSelect.onchange = () => {
      workingHoursStatus.dataset.workingTimeMonth = this._incomeWorkingMonth(this._month, workPeriodSelect.value);
      if (automaticHours.checked) loadWorkingHours();
      else workingHoursStatus.textContent = `${this._monthLabel(workingHoursStatus.dataset.workingTimeMonth)} · manual working hours`;
    };
    fundedPensionJoined.onchange = () => {
      const selected = modal.root.querySelector('[name="funded_pension_rate"]:checked');
      if (fundedPensionJoined.checked && Number(selected?.value || 0) === 0) {
        modal.root.querySelector('[name="funded_pension_rate"][value="2"]').checked = true;
      } else if (!fundedPensionJoined.checked) {
        modal.root.querySelector('[name="funded_pension_rate"][value="0"]').checked = true;
      }
      updatePayrollControls();
    };
    refreshWorkingHours.onclick = loadWorkingHours;
    payrollFields.querySelectorAll("input").forEach((input) => {
      input.addEventListener("input", updatePayrollPreview);
      input.addEventListener("change", updatePayrollControls);
    });
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

  _openCareLeaveEditor(item) {
    const care = item.care_leave || {};
    const incomeOptions = this._careIncomeOptions(care.work_month || this._month);
    const selectedLink = this._careIncomeOptionValue(care.income_month, care.linked_income_item_id);
    const bounds = this._careMonthBounds(care.work_month || this._month);
    const periods = care.periods || [];
    const basisMode = care.benefit_basis_mode || "estimated_hourly";
    const periodRows = periods.length ? periods.map((period) => {
      const calculation = period.calculation || {};
      const dateLabel = this._formatDateRange(period.start, period.end);
      return `<article class="care-period" data-period-id="${period.id}">
        <div><strong>${this._esc(dateLabel)}</strong><span>${this._esc(calculation.calendar_days || 0)} calendar days · ${this._esc(calculation.missed_working_hours || 0)} missed work hours</span><span>Estimated Tervisekassa net benefit ${this._money(calculation.estimated_net_benefit || 0)}</span></div>
        <div class="care-period-actions"><button type="button" class="quiet edit-care-period" data-period-id="${period.id}">Edit</button><button type="button" class="danger-button delete-care-period" data-period-id="${period.id}">Remove</button></div>
      </article>`;
    }).join("") : `<div class="empty-row">No care-leave periods recorded yet.</div>`;
    const fields = `
      <div class="review-notice care-estimate-notice" role="note"><strong>Planning approximation</strong><span>Budget Manager estimates the salary reduction and Tervisekassa payment. The final payment can differ because Tervisekassa uses official income and eligibility data.</span></div>
      ${this._field("Name", "name", item.name, "text", "required")}
      <label><span>Salary affected by this leave</span><select name="care_income_link" required>${incomeOptions.map(({ incomeMonth, item: income }) => `<option value="${this._careIncomeOptionValue(incomeMonth, income.id)}" ${this._careIncomeOptionValue(incomeMonth, income.id) === selectedLink ? "selected" : ""}>${this._esc(income.name)} · paid in ${this._monthLabel(incomeMonth)}</option>`).join("")}</select></label>
      <label><span>Tervisekassa benefit income basis</span><select name="benefit_basis_mode" id="care-editor-basis"><option value="estimated_hourly" ${basisMode === "estimated_hourly" ? "selected" : ""}>Estimate from the selected hourly income</option><option value="actual_previous_year_income" ${basisMode === "actual_previous_year_income" ? "selected" : ""}>Use actual previous-year social-taxable income</option></select></label>
      <label id="care-editor-actual-field"><span>Previous-year social-taxable income, EUR</span><input type="number" name="actual_previous_year_income" min="0.01" step="0.01" value="${this._esc(care.actual_previous_year_income || "")}"></label>
      <p class="form-help" id="care-editor-basis-help"></p>
      <section class="care-periods"><div class="care-periods-head"><div><strong>Recorded periods</strong><span>Each period produces a separate estimated income in ${this._monthLabel(care.income_month)}.</span></div><button type="button" class="quiet" id="new-care-period">＋ Add period</button></div>${periodRows}</section>
      <fieldset class="settings-group" id="care-period-form" hidden>
        <legend id="care-period-form-title">Add period</legend>
        <input type="hidden" id="care-period-id">
        <div class="two-col">${this._field("Start date", "care_period_start", bounds.min, "date", `min="${bounds.min}" max="${bounds.max}"`)}${this._field("End date", "care_period_end", bounds.min, "date", `min="${bounds.min}" max="${bounds.max}"`)}</div>
        <div class="inline-actions"><button type="button" class="quiet" id="cancel-care-period">Cancel</button><button type="button" class="primary" id="save-care-period">Save period</button></div>
      </fieldset>`;
    const modal = this._openModal("Child-care sick leave", fields, "Save settings", async (form) => {
      const link = String(form.get("care_income_link") || "").split("::");
      if (link.length !== 2) throw new Error("Select an eligible automatic hourly income.");
      const linkedIncome = this._state.months[link[0]]?.items.find((entry) => entry.id === link[1]);
      const selectedBasis = String(form.get("benefit_basis_mode"));
      const actualIncome = Number(form.get("actual_previous_year_income") || 0);
      if (selectedBasis === "actual_previous_year_income" && (!Number.isFinite(actualIncome) || actualIncome <= 0)) throw new Error("Enter the previous calendar year's total social-taxable income.");
      await this._hass.callWS({
        type: "budget_manager/upsert_item", month: this._month, scope: "this",
        item: { ...item, name: form.get("name"), expense_type: "child_care_leave", care_leave: {
          ...care,
          linked_income_item_id: link[1], linked_income_series_id: linkedIncome?.series_id || "", linked_income_name: linkedIncome?.name || "",
          income_month: link[0], work_month: this._month, benefit_basis_mode: selectedBasis,
          actual_previous_year_income: selectedBasis === "actual_previous_year_income" ? actualIncome : 0,
        } },
      });
    }, `<button type="button" class="danger-button" id="delete-care-item">Delete care leave</button>`);

    const basisSelect = modal.root.querySelector("#care-editor-basis");
    const actualField = modal.root.querySelector("#care-editor-actual-field");
    const actualInput = actualField.querySelector("input");
    const basisHelp = modal.root.querySelector("#care-editor-basis-help");
    const updateBasis = () => {
      const actual = basisSelect.value === "actual_previous_year_income";
      actualField.hidden = !actual;
      actualInput.required = actual;
      basisHelp.textContent = actual
        ? "Enter the previous calendar year's total gross income on which social tax was paid, as reported to MTA. Do not enter net salary or one month's income. Tervisekassa normally divides the annual amount by 365. This remains an estimate because official exceptions and eligibility data are not available to Budget Manager."
        : "The prior-year basis is approximated from this salary's hourly gross rate and Estonia's standard working hours. Use the actual-income option when you know the annual social-taxable amount reported to MTA.";
    };
    basisSelect.onchange = updateBasis;
    updateBasis();

    const periodForm = modal.root.querySelector("#care-period-form");
    const periodId = modal.root.querySelector("#care-period-id");
    const periodStart = modal.root.querySelector('[name="care_period_start"]');
    const periodEnd = modal.root.querySelector('[name="care_period_end"]');
    const openPeriodForm = (period = null) => {
      periodForm.hidden = false;
      periodId.value = period?.id || "";
      periodStart.value = period?.start || bounds.min;
      periodEnd.value = period?.end || period?.start || bounds.min;
      modal.root.querySelector("#care-period-form-title").textContent = period ? "Edit period" : "Add period";
      periodStart.focus();
      requestAnimationFrame(() => periodForm.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    };
    modal.root.querySelector("#new-care-period").onclick = () => openPeriodForm();
    modal.root.querySelector("#cancel-care-period").onclick = () => { periodForm.hidden = true; };
    modal.root.querySelectorAll(".edit-care-period").forEach((button) => {
      button.onclick = () => openPeriodForm(periods.find((period) => period.id === button.dataset.periodId));
    });
    modal.root.querySelector("#save-care-period").onclick = async () => {
      try {
        if (!periodStart.value || !periodEnd.value) throw new Error("Select both the start and end dates.");
        const savedPeriod = await this._hass.callWS({ type: "budget_manager/upsert_care_leave_period", month: this._month, item_id: item.id, period: { id: periodId.value || undefined, start: periodStart.value, end: periodEnd.value } });
        modal.close();
        await this._load(this._year);
        const refreshed = this._state.months[this._month]?.items.find((entry) => entry.id === item.id);
        if (refreshed) {
          this._carePeriodToReveal = savedPeriod.id;
          this._openCareLeaveEditor(refreshed);
        }
      } catch (err) { this._showError(err); }
    };
    modal.root.querySelectorAll(".delete-care-period").forEach((button) => {
      button.onclick = async () => {
        if (!window.confirm("Remove this care-leave period and its generated Tervisekassa income?")) return;
        try {
          await this._hass.callWS({ type: "budget_manager/delete_care_leave_period", month: this._month, item_id: item.id, period_id: button.dataset.periodId });
          modal.close();
          await this._load(this._year);
          const refreshed = this._state.months[this._month]?.items.find((entry) => entry.id === item.id);
          if (refreshed) this._openCareLeaveEditor(refreshed);
        } catch (err) { this._showError(err); }
      };
    });
    modal.root.querySelector("#delete-care-item").onclick = async () => {
      if (!window.confirm("Delete this care-leave item, restore the salary estimate, and remove its generated Tervisekassa income?")) return;
      try {
        await this._hass.callWS({ type: "budget_manager/delete_item", month: this._month, item_id: item.id, scope: "this" });
        modal.close();
        await this._load(this._year);
      } catch (err) { this._showError(err); }
    };
    if (this._carePeriodToReveal) {
      const revealId = this._carePeriodToReveal;
      this._carePeriodToReveal = null;
      requestAnimationFrame(() => {
        modal.root.querySelector(`[data-period-id="${CSS.escape(revealId)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
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
      :host { --ink: var(--primary-text-color, #18211d); --muted: var(--secondary-text-color, #6d7872); --surface: var(--card-background-color, #fff); --page: var(--primary-background-color, #f4f6f3); --line: rgba(100,120,108,.18); --green: #34785a; --green-soft: #dceee3; --blue: #3976a8; --red: #a64a42; --amber: #a36d00; display:block; height:100vh; height:100dvh; overflow:hidden; color:var(--ink); background:var(--page); font-family:var(--paper-font-body1_-_font-family, system-ui, sans-serif); }
      * { box-sizing:border-box; } [hidden] { display:none !important; } button, input, select, textarea { font:inherit; } button { color:inherit; }
      .app,ha-top-app-bar-fixed { height:100%; overflow:hidden; } .app.is-loading { cursor:progress; }
      .native-title { min-width:0; display:grid; gap:2px; line-height:1.1; }.native-title strong,.native-title small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.native-title strong { font-size:17px; }.native-title small { font-size:11px; font-weight:400; opacity:.78; }
      h1,h2,p { margin:0; } h1 { font-size:20px; line-height:1.1; } .section-title p, .updated { color:var(--muted); font-size:12px; margin-top:4px; }
      .header-actions,.toolbar-actions { display:flex; align-items:center; gap:3px; }.app-bar-button { min-height:40px; padding:0 12px; border-radius:var(--ha-border-radius-button,10px); background:transparent; color:inherit; font-weight:650; }.app-bar-button:hover { background:rgba(255,255,255,.12); }.refresh-action { min-width:40px; padding:0; font-size:20px; }.read-only { padding:7px 10px; border-radius:999px; background:rgba(255,255,255,.14); color:inherit; font-size:12px; }
      main { max-width:1500px; margin:0 auto; padding:28px clamp(16px,4vw,54px) 70px; }
      button { border:0; cursor:pointer; }.quiet,.primary,.danger-button { border-radius:10px; padding:10px 14px; font-weight:650; }.quiet { background:var(--surface); border:1px solid var(--line); }.quiet:hover { border-color:var(--green); }.primary { background:var(--green); color:#fff; box-shadow:0 5px 14px rgba(52,120,90,.2); }.danger-button { color:var(--red); background:transparent; border:1px solid color-mix(in srgb, var(--red) 35%, transparent); }
      .year-toolbar,.month-toolbar { display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:22px; }.year-switcher { display:flex; align-items:center; gap:8px; }.icon-button,.year-button { height:46px; border-radius:12px; background:var(--surface); border:1px solid var(--line); }.icon-button { width:46px; font-size:26px; }.year-button { min-width:150px; padding:0 22px; font-size:20px; font-weight:750; }
      .empty-plan { display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:22px; padding:20px; border:1px dashed color-mix(in srgb,var(--green) 45%,var(--line)); border-radius:15px; background:var(--surface); }.empty-plan h2 { margin:5px 0; font-size:18px; }.empty-plan p { color:var(--muted); font-size:12px; }
      .matrix-title-actions { display:flex; align-items:center; justify-content:flex-end; gap:8px; flex-wrap:wrap; }.matrix-edit-toggle.active,.past-months-toggle.active { color:var(--green); border-color:var(--green); background:var(--green-soft); }
      .metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:13px; margin-bottom:25px; }.metric { padding:18px; border:1px solid var(--line); border-radius:15px; background:var(--surface); }.metric span { display:block; color:var(--muted); font-size:12px; margin-bottom:9px; }.metric strong { font-size:clamp(18px,2vw,26px); letter-spacing:-.03em; }.metric.income,.metric.good,.metric.green { border-top:3px solid var(--green); }.metric.expense,.metric.danger,.metric.red { border-top:3px solid var(--red); }.metric.warning,.metric.yellow { border-top:3px solid #d19a2e; }.metric.savings { border-top:3px solid #3976a8; }
      .month-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:13px; margin-bottom:34px; }.month-card { text-align:left; min-height:170px; padding:18px; border-radius:16px; border:1px solid var(--line); background:var(--surface); transition:.16s ease; }.month-card:hover { transform:translateY(-2px); border-color:var(--green); box-shadow:0 10px 26px rgba(30,60,44,.08); }.month-card-title { display:flex; justify-content:space-between; font-weight:700; }.negative { color:var(--red); }.month-card dl { margin:20px 0 0; display:grid; gap:6px; }.month-card dl div { display:flex; justify-content:space-between; gap:12px; font-size:12px; }.month-card dt { color:var(--muted); }.month-card dd { margin:0; }.month-card-footer { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:9px; margin-top:14px; padding-top:11px; border-top:1px solid var(--line); }.item-count { color:var(--muted); font-size:11px; }.rag-status { display:inline-block; padding:4px 8px; border-radius:999px; font-size:10px; font-weight:750; }.rag-status.green,.rag-cell.green { background:#d7eee1; color:#185d3d; }.rag-status.yellow,.rag-cell.yellow { background:#ffedbd; color:#765300; }.rag-status.red,.rag-cell.red { background:#f7d8d4; color:#8e312a; }.month-card.missing { display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; border-style:dashed; color:var(--muted); }.missing .month-name { align-self:flex-start; color:var(--ink); }.missing .plus { font-size:28px; margin-top:auto; }.missing small { margin-bottom:auto; }
      .matrix-section,.items-section { background:var(--surface); border:1px solid var(--line); border-radius:17px; overflow:hidden; margin-top:20px; }.section-title { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding:19px 21px; border-bottom:1px solid var(--line); }.section-title h2 { font-size:17px; }.matrix-wrap { overflow:auto; max-height:70vh; }.matrix { border-collapse:separate; border-spacing:0; table-layout:fixed; width:100%; font-size:11px; }.matrix .item-column { width:205px; }.matrix th,.matrix td { padding:9px 6px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; text-align:right; }.matrix thead th { position:sticky; top:0; z-index:2; background:color-mix(in srgb,var(--surface) 92%,var(--green-soft)); color:var(--muted); }.matrix thead .matrix-years th { top:0; background:color-mix(in srgb,var(--green-soft) 68%,var(--surface)); color:var(--ink); text-align:center; font-size:13px; font-weight:800; }.matrix thead .matrix-years + tr th { top:35px; }.matrix th:first-child { text-align:left; background:var(--surface); }.sticky-first-column .matrix th:first-child { position:sticky; left:0; z-index:3; }.sticky-first-column .matrix thead th:first-child { z-index:4; }.item-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; }.column-pin-toggle { display:inline-flex; align-items:center; gap:5px; padding:2px; border-radius:999px; background:transparent; color:var(--muted); font-size:9px; font-weight:700; }.column-pin-toggle:hover { color:var(--ink); }.toggle-track { position:relative; width:28px; height:16px; flex:0 0 auto; border-radius:999px; background:var(--line); transition:background .16s ease; }.toggle-thumb { position:absolute; top:2px; left:2px; width:12px; height:12px; border-radius:50%; background:var(--surface); box-shadow:0 1px 3px rgba(0,0,0,.25); transition:transform .16s ease; }.column-pin-toggle.on .toggle-track { background:var(--green); }.column-pin-toggle.on .toggle-thumb { transform:translateX(12px); }.matrix td { cursor:pointer; }.matrix td:hover { outline:2px solid var(--green); outline-offset:-2px; }.matrix-edit-cell { padding:3px !important; background:color-mix(in srgb,var(--green-soft) 18%,var(--surface)); }.matrix-edit-cell.needs-review { background:color-mix(in srgb,#ffedbd 55%,var(--surface)); }.matrix-amount-input { width:100%; min-width:0; padding:6px 4px; border:1px solid var(--line); border-radius:6px; outline:none; color:var(--ink); background:var(--surface); text-align:right; font-size:11px; }.matrix-amount-input:focus { border-color:var(--green); box-shadow:0 0 0 2px color-mix(in srgb,var(--green) 16%,transparent); }.matrix-amount-input:disabled { opacity:.55; cursor:progress; }.automatic-savings-cell { color:var(--blue); font-weight:700; cursor:pointer; }.matrix .blank { color:var(--muted); }.matrix .special { background:#fff3be; color:#624900; font-weight:700; }.matrix .complete { opacity:.58; text-decoration:line-through; }.matrix td small { display:block; font-size:9px; text-decoration:none; }.kind-dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:8px; background:var(--red); }.income .kind-dot { background:var(--green); }.savings .kind-dot { background:#3976a8; }.matrix-group th { position:static !important; padding:7px 10px; background:color-mix(in srgb,var(--surface) 90%,var(--page)) !important; color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.07em; }.matrix-group.summary th { background:color-mix(in srgb,var(--green-soft) 55%,var(--surface)) !important; color:var(--ink); }.summary-row th,.summary-row td { font-weight:700; }.summary-row.savings td { color:#2d6798; }
      .eyebrow { display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.08em; }.balance-value { margin-top:5px; padding:0; background:transparent; font-size:32px; font-weight:760; letter-spacing:-.04em; }.balance-value small { font-size:11px; color:var(--green); margin-left:7px; }.items-list { display:grid; }.item { min-height:70px; display:grid; grid-template-columns:36px minmax(0,1fr) auto 34px; gap:13px; align-items:center; padding:12px 17px; border-bottom:1px solid var(--line); }.item:last-child { border-bottom:0; }.item.needs-review { padding-left:14px; border-left:3px solid #d19a2e; background:color-mix(in srgb,#ffedbd 22%,var(--surface)); }.item.complete { opacity:.58; }.status-button { width:31px; height:31px; border:2px solid var(--line); border-radius:10px; background:transparent; color:white; font-weight:800; }.status-button.done { background:var(--green); border-color:var(--green); }.status-placeholder { width:31px; height:31px; display:block; }.item-title { font-weight:680; }.item-meta { color:var(--muted); font-size:11px; margin-top:4px; }.item-amount { font-size:16px; text-align:right; }.item-amount small { display:block; margin-top:3px; color:var(--muted); font-size:9px; font-weight:500; }.more-button { width:34px; height:34px; border-radius:9px; background:transparent; color:var(--muted); }.more-button:hover { background:var(--line); }.badge { display:inline-block; padding:3px 7px; margin-left:7px; border-radius:999px; background:#ffe894; color:#6e5100; font-size:9px; text-transform:uppercase; letter-spacing:.04em; }.badge.review-badge { background:#ffedbd; color:#765300; }.badge.savings-badge { background:#dbeaf7; color:#245c88; }.badge.care-badge { background:#e2dcfa; color:#51418e; }.empty-row,.empty { padding:34px; text-align:center; color:var(--muted); }.empty.error { color:var(--red); }.danger-zone { display:flex; justify-content:flex-end; margin-top:26px; }
      .form-help { color:var(--muted); line-height:1.55; }
      .balance-value { display:block; }
      .modal-backdrop { position:fixed; inset:0; z-index:100; display:grid; place-items:center; padding:18px; background:rgba(10,18,14,.54); backdrop-filter:blur(4px); }.modal { width:min(590px,100%); max-height:90vh; display:flex; flex-direction:column; background:var(--surface); border-radius:18px; box-shadow:0 30px 90px rgba(0,0,0,.3); overflow:hidden; }.modal-head,.modal-actions { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:17px 20px; border-bottom:1px solid var(--line); }.modal-head h2 { font-size:18px; }.close { position:relative; width:35px; height:35px; flex:0 0 35px; padding:0; border-radius:50%; background:var(--line); }.close::before,.close::after { content:""; position:absolute; top:50%; left:50%; width:17px; height:2px; border-radius:999px; background:currentColor; }.close::before { transform:translate(-50%,-50%) rotate(45deg); }.close::after { transform:translate(-50%,-50%) rotate(-45deg); }.modal-body { min-height:0; padding:20px; overflow:auto; overscroll-behavior:contain; scrollbar-gutter:stable; display:grid; gap:15px; }.modal-actions { border-top:1px solid var(--line); border-bottom:0; justify-content:flex-end; }.modal-actions .danger-button { margin-right:auto; }.modal label { display:grid; gap:7px; color:var(--muted); font-size:12px; }.modal input,.modal select,.modal textarea { width:100%; padding:11px 12px; color:var(--ink); background:var(--page); border:1px solid var(--line); border-radius:10px; outline:none; }.modal input:disabled { color:var(--muted); opacity:.72; cursor:not-allowed; }.modal input:focus,.modal select:focus,.modal textarea:focus { border-color:var(--green); box-shadow:0 0 0 3px color-mix(in srgb,var(--green) 15%,transparent); }.two-col { display:grid; grid-template-columns:1fr 1fr; gap:13px; }.modal .check { display:flex; flex-direction:row; align-items:center; }.modal .check input { width:auto; }
      .settings-group { min-width:0; display:grid; gap:11px; margin:0; padding:16px; border:1px solid var(--line); border-radius:14px; }.settings-group legend { padding:0 6px; font-size:13px; font-weight:750; }.settings-group .form-help { font-size:11px; }.data-settings { display:flex; align-items:center; justify-content:space-between; gap:14px; padding:16px; border:1px solid var(--line); border-radius:14px; }.data-settings h3 { margin:0 0 5px; font-size:13px; }.data-settings .form-help { font-size:11px; }.data-actions { display:flex; flex:0 0 auto; gap:8px; }.care-periods { max-height:min(42vh,420px); display:grid; gap:0; overflow:auto; overscroll-behavior:contain; border:1px solid var(--line); border-radius:14px; }.care-periods-head,.care-period { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:13px 15px; }.care-periods-head { position:sticky; top:0; z-index:1; background:var(--page); }.care-periods-head div,.care-period > div:first-child { display:grid; gap:3px; }.care-periods-head span,.care-period span { color:var(--muted); font-size:11px; }.care-period { border-top:1px solid var(--line); }.care-period-actions,.inline-actions { display:flex; justify-content:flex-end; gap:8px; }.care-period-actions .danger-button { padding:8px 10px; }.care-benefit-total { color:var(--blue); }
      #estonian-payroll-fields { display:grid; gap:12px; margin-top:5px; }.calendar-source { display:flex; align-items:center; justify-content:space-between; gap:10px; color:var(--muted); font-size:11px; }.calendar-source .quiet { flex:0 0 auto; padding:7px 10px; }.tax-free-setting { display:grid; grid-template-columns:minmax(0,1fr) minmax(150px,.7fr); align-items:end; gap:12px; }.pension-rates { display:flex; flex-wrap:wrap; gap:10px; }.pension-rates label { display:flex; grid-template-columns:none; flex-direction:row; align-items:center; gap:5px; padding:7px 10px; border:1px solid var(--line); border-radius:999px; color:var(--ink); }.pension-rates input { width:auto; margin:0; }.muted { opacity:.7; }.payroll-preview { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; padding:12px; border-radius:11px; background:color-mix(in srgb,var(--green-soft) 42%,var(--surface)); }.payroll-preview > span { grid-column:1/-1; color:var(--muted); font-size:11px; }.payroll-preview div { display:grid; gap:3px; }.payroll-preview span { color:var(--muted); font-size:10px; }.payroll-preview strong { font-size:14px; }
      .review-notice { display:grid; gap:4px; padding:12px 14px; border:1px solid #d19a2e; border-radius:11px; background:color-mix(in srgb,#ffedbd 38%,var(--surface)); color:#765300; }.review-notice strong { font-size:12px; }.review-notice span { font-size:11px; line-height:1.45; }.review-notice.care-estimate-notice { border-color:color-mix(in srgb,var(--blue) 62%,var(--line)); background:color-mix(in srgb,var(--blue) 13%,var(--surface)); color:var(--ink); }.review-notice.care-estimate-notice span { color:var(--muted); }
      #toast { position:fixed; right:20px; bottom:20px; z-index:200; max-width:420px; padding:13px 16px; border-radius:11px; background:#8d332d; color:white; opacity:0; visibility:hidden; pointer-events:none; transform:translateY(calc(100% + 40px)); transition:transform .2s ease,opacity .2s ease,visibility 0s linear .2s; box-shadow:0 10px 30px rgba(0,0,0,.25); }#toast.success { background:var(--green); }#toast.show { opacity:1; visibility:visible; pointer-events:auto; transform:translateY(0); transition-delay:0s; }
      @media (max-width:1000px) { .month-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }.metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } }
      @media (max-width:700px) { h1 { font-size:17px; } main { padding:18px 12px 50px; }.year-toolbar,.month-toolbar,.empty-plan { align-items:flex-start; flex-direction:column; }.toolbar-actions { width:100%; }.toolbar-actions button { flex:1; }.month-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.metrics { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }.metric { padding:14px; }.month-card { min-height:190px; padding:14px; }.item { grid-template-columns:34px minmax(0,1fr) auto; }.more-button { grid-column:3; grid-row:1; }.item-amount { grid-column:3; grid-row:2; }.two-col,.tax-free-setting { grid-template-columns:1fr; }.section-title { flex-direction:column; }.data-settings { align-items:flex-start; flex-direction:column; }.data-actions { width:100%; }.data-actions button { flex:1; }.care-periods-head,.care-period { align-items:flex-start; flex-direction:column; }.care-period-actions { width:100%; }.care-period-actions button { flex:1; } }
      @media (max-width:430px) { .month-grid { grid-template-columns:1fr; }.metrics { grid-template-columns:1fr 1fr; }.metric strong { font-size:17px; }.month-header .settings-action,.refresh-action { display:none; } }
    `;
  }
}

const PANEL_MODULE_VERSION = new URL(import.meta.url).searchParams.get("v") || "dev";
const PANEL_ELEMENT_NAME = `budget-manager-panel-${PANEL_MODULE_VERSION.toLowerCase().replace(/[^a-z0-9._-]/g, "-")}`;
if (!customElements.get(PANEL_ELEMENT_NAME)) {
  customElements.define(PANEL_ELEMENT_NAME, BudgetManagerPanel);
}
