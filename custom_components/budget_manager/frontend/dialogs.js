import { nothing, render } from "lit";
import { FamilyFlowController, renderFamilyDialog } from "@bitosome/ha-card-ui";

// Budget-specific DOM forms live here; navigation, native focus and dismissal
// belong to the shared library. Retain parent forms so Back never rebuilds a draft.
export class BudgetDialogs {
  constructor(panel) {
    this.panel = panel;
    this.pages = new Map();
    this.sequence = 0;
    this.flow = new FamilyFlowController({ requestUpdate: () => this.render() }, {
      guard: (intent) => {
        if (panel._pendingWrite && intent !== "close") return { pending: true, message: "Saving budget changes…" };
        if (intent === "navigate") return undefined; // Parent DOM is retained.
        const pages = intent === "close" ? [...this.pages.values()] : [this.pages.get(this.flow.current)];
        const dirty = pages.some(page => page && page.guard && page.baseline !== this.snapshot(page.form));
        return { dirty: !panel._pendingWrite && dirty,
          message: "Discard unsaved changes in this budget form?", discard: () => {
            pages.forEach(page => { if (page) page.baseline = this.snapshot(page.form); });
          } };
      },
      onChange: (_route, previous) => {
        const old = this.pages.get(previous);
        const scroller = panel.shadowRoot.querySelector(".family-dialog-body");
        if (old && scroller) old.scroll = scroller.scrollTop;
        for (const [id, page] of this.pages) {
          if (!this.flow.stack.includes(id)) { page.resolve?.(null); this.pages.delete(id); }
        }
      },
      onClose: () => {
        this.pages.clear();
        panel._restoreDialogFocus?.();
      },
    });
  }

  snapshot(form) {
    return JSON.stringify([...form.querySelectorAll("input, select, textarea")]
      .filter(input => input.type !== "file")
      .map(input => [input.name, input.type, input.type === "checkbox" || input.type === "radio" ? input.checked : input.value]));
  }

  open(title, fields, submitLabel, onSubmit, extraButtons = "", submitClass = "primary", options = {}) {
    const id = `budget-form-${++this.sequence}`;
    const form = document.createElement("form");
    form.id = id; form.className = "budget-form";
    form.innerHTML = `<div class="budget-form-fields">${fields}</div><p class="form-status" role="status" aria-live="polite" hidden></p>`;
    const footer = document.createElement("div"); footer.className = "budget-form-actions";
    footer.innerHTML = `${extraButtons}<button type="button" class="quiet" data-budget-cancel>Cancel</button>${submitLabel ? `<button class="${submitClass}" type="submit" form="${id}">${this.panel._esc(submitLabel)}</button>` : ""}`;
    const roots = [form, footer];
    const root = {
      querySelector: selector => roots.find(node => node.matches(selector)) || roots.map(node => node.querySelector(selector)).find(Boolean) || null,
      querySelectorAll: selector => roots.flatMap(node => [...node.querySelectorAll(selector)]),
    };
    const page = { id, title, form, footer, root, baseline: this.snapshot(form), guard: options.guard !== false, scroll: 0, submitting: false };
    this.pages.set(id, page);
    const wasActive = this.flow.active;
    if (!wasActive) this.panel._captureDialogFocus?.();
    const opened = wasActive ? (options.replace ? this.flow.replace(id) : this.flow.push(id)) : this.flow.open(id, this.panel.shadowRoot.activeElement);
    if (!opened) { this.pages.delete(id); return null; }
    if (this.panel._pendingWrite) this.pending(true);
    // Existing form setup synchronously updates conditional controls and calculated fields.
    queueMicrotask(() => { if (this.pages.has(id)) page.baseline = this.snapshot(form); });
    footer.querySelector("[data-budget-cancel]").onclick = () => this.flow.canBack ? this.flow.back() : this.flow.close();
    form.onsubmit = async event => {
      event.preventDefault();
      if (page.submitting || this.panel._pendingWrite || !this.pages.has(id)) return;
      const data = new FormData(form);
      page.submitting = true;
      this.lock(page, true, "submit");
      this.status(page, "Saving…");
      try {
        if (await onSubmit(data) === false) { this.status(page, ""); return; }
        page.baseline = this.snapshot(form);
        if (this.flow.current === id) this.flow.canBack ? this.flow.back() : this.flow.forceClose();
        await this.panel._load(this.panel._year, { preserveScroll: true });
      } catch (error) {
        this.status(page, error?.message || String(error), true);
        if (!this.pages.has(id)) this.panel._showError(error);
      } finally {
        page.submitting = false;
        this.lock(page, false, "submit");
      }
    };
    return { root, form, page,
      close: () => { if (this.pages.has(id)) this.flow.forceClose(); },
      isActive: () => this.flow.current === id,
      rebase: () => { page.baseline = this.snapshot(form); },
      status: (message, error = false) => this.status(page, message, error),
    };
  }

  lock(page, enabled, reason = "write") {
    page.locks ||= new Set();
    if (enabled) {
      if (!page.locks.size) {
        page.disabled = new Map(page.root.querySelectorAll("input, select, textarea, button").map(node => [node, node.disabled]));
        page.disabled.forEach((_previous, node) => { node.disabled = true; });
        page.footer.querySelector("[data-budget-cancel]").disabled = false;
      }
      page.locks.add(reason);
    } else {
      page.locks.delete(reason);
      if (!page.locks.size) {
        page.disabled?.forEach((previous, node) => { node.disabled = previous; });
        page.disabled = null;
      }
    }
    page.form.setAttribute("aria-busy", String(!!page.locks.size));
  }

  pending(enabled) {
    this.pages.forEach(page => this.lock(page, enabled));
    this.flow.notice = enabled ? "Saving budget changes…" : "";
    this.render();
  }

  reportError(error) {
    const page = this.pages.get(this.flow.current);
    if (page) this.status(page, error?.message || String(error), true);
    return Boolean(page);
  }

  status(page, message, error = false) {
    const node = page.form.querySelector(".form-status");
    node.textContent = message; node.hidden = !message;
    node.setAttribute("role", error ? "alert" : "status");
    node.classList.toggle("error", error);
  }

  choose(title, description, choices) {
    return new Promise(resolve => {
      const buttons = choices.map(choice => `<button type="button" class="${choice.destructive ? "danger-button" : "quiet"}" data-choice="${this.panel._esc(choice.value)}">${this.panel._esc(choice.label)}</button>`).join("");
      const modal = this.open(title, `<p class="form-help">${this.panel._esc(description)}</p><div class="choice-actions">${buttons}</div>`, null, () => {}, "", "primary", { guard: false });
      if (!modal) { resolve(null); return; }
      modal.page.resolve = resolve;
      modal.root.querySelectorAll("[data-choice]").forEach(button => {
        button.onclick = () => {
          modal.page.resolve = null;
          const value = button.dataset.choice;
          this.flow.canBack ? this.flow.back() : this.flow.forceClose();
          resolve(value);
        };
      });
    });
  }

  render() {
    const host = this.panel.shadowRoot.getElementById?.("modal-root");
    if (!host) return;
    const page = this.pages.get(this.flow.current);
    render(page ? renderFamilyDialog(this.flow, {
      title: page.title, content: page.form, footer: page.footer, wide: true,
      className: "budget-dialog", bodyClass: "budget-dialog-body",
    }) : nothing, host);
    this.flow.hostUpdated();
    if (page && this.lastPage !== page.id) {
      const body = host.querySelector(".family-dialog-body");
      if (body) body.scrollTop = page.scroll;
      this.lastPage = page.id;
    }
  }

  dispose() {
    this.flow.hostDisconnected();
    this.pages.forEach(page => page.resolve?.(null));
    this.pages.clear();
  }
}
