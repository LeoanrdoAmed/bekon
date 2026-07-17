(() => {
  const pageKey = document.body.dataset.page || "";
  const csrfToken = document
    .querySelector('meta[name="csrf-token"]')
    ?.getAttribute("content") || "";
  const setupMessages = document.getElementById("setup-messages");
  const setupField = document.querySelector(".setup-answer-form [data-select-filter], .setup-answer-form input, .setup-answer-form select");

  const setupWindowScrollKey = "fin-na-mao-setup-window-scroll";
  const setupMessagesScrollKey = "fin-na-mao-setup-messages-scroll";

  const persistSetupScroll = () => {
    if (pageKey !== "setup") return;
    sessionStorage.setItem(setupWindowScrollKey, String(window.scrollY || 0));
    if (setupMessages) {
      sessionStorage.setItem(setupMessagesScrollKey, String(setupMessages.scrollTop || 0));
    }
  };

  const restoreSetupScroll = () => {
    if (pageKey !== "setup") return;
    const savedWindowScroll = sessionStorage.getItem(setupWindowScrollKey);
    const savedMessagesScroll = sessionStorage.getItem(setupMessagesScrollKey);

    if (savedMessagesScroll !== null && setupMessages) {
      setupMessages.scrollTop = Number(savedMessagesScroll) || 0;
      sessionStorage.removeItem(setupMessagesScrollKey);
    } else if (setupMessages) {
      setupMessages.scrollTop = setupMessages.scrollHeight;
    }

    if (savedWindowScroll !== null) {
      window.scrollTo(0, Number(savedWindowScroll) || 0);
      sessionStorage.removeItem(setupWindowScrollKey);
    }
  };

  const setupForms = Array.from(document.querySelectorAll("form[data-preserve-scroll]"));
  setupForms.forEach((form) => {
    form.addEventListener("submit", persistSetupScroll);
  });

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-confirm]");
    if (!form) return;
    const message = form.getAttribute("data-confirm") || "Confirmar esta acao?";
    if (!window.confirm(message)) {
      event.preventDefault();
    }
  });

  const bindFilterableSelect = (select) => {
    const wrapper = select.closest(".setup-select-stack, .edit-bank-select");
    const filter = wrapper?.querySelector("[data-select-filter]");
    if (!filter) return;

    const sourceOptions = Array.from(select.options).map((option) => ({
      value: option.value,
      label: option.textContent || "",
    }));
    const placeholder = select.dataset.placeholder || "";

    const renderOptions = (term = "") => {
      const normalizedTerm = String(term || "").trim().toLowerCase();
      const currentValue = String(select.dataset.currentValue || select.value || "").trim();
      const filtered = sourceOptions.filter((option) =>
        !normalizedTerm || option.label.toLowerCase().includes(normalizedTerm)
      );

      const optionMarkup = filtered
        .map((option) => `<option value="${option.value}">${option.label}</option>`)
        .join("");
      const placeholderMarkup = placeholder
        ? `<option value="" disabled selected>${placeholder}</option>`
        : "";

      select.innerHTML = filtered.length
        ? `${placeholderMarkup}${optionMarkup}`
        : '<option value="" disabled selected>Nenhum banco encontrado</option>';

      select.size = Math.min(8, Math.max(4, filtered.length || 1));
      if (currentValue && filtered.some((option) => option.value === currentValue)) {
        select.value = currentValue;
      } else if (!placeholder && filtered.length) {
        select.selectedIndex = 0;
      }
    };

    filter.addEventListener("input", () => renderOptions(filter.value));
    renderOptions(filter.value);
  };

  Array.from(document.querySelectorAll("[data-filterable-select]")).forEach(bindFilterableSelect);

  const bindManualBankInput = (wrapper) => {
    const toggle = wrapper.querySelector("[data-manual-bank-toggle]");
    const manualInput = wrapper.querySelector("[data-manual-bank-input]");
    const select = wrapper.querySelector("[data-filterable-select]");
    const filter = wrapper.querySelector("[data-select-filter]");
    if (!toggle || !manualInput || !select) return;

    const syncManualMode = () => {
      const manualMode = toggle.checked;
      manualInput.classList.toggle("is-hidden", !manualMode);
      manualInput.disabled = !manualMode;
      manualInput.required = manualMode;
      select.disabled = manualMode;
      if (filter) filter.disabled = manualMode;
      if (manualMode) {
        select.required = false;
        select.selectedIndex = 0;
      }
    };

    toggle.addEventListener("change", syncManualMode);
    syncManualMode();
  };

  Array.from(document.querySelectorAll(".setup-select-stack, .edit-bank-select")).forEach(bindManualBankInput);

  Array.from(document.querySelectorAll("[data-edit-field-select]")).forEach((fieldSelect) => {
    const form = fieldSelect.closest("form");
    const bankWrapper = form?.querySelector("[data-edit-bank-wrapper]");
    const textWrapper = form?.querySelector("[data-edit-text-wrapper]");
    const bankSelect = bankWrapper?.querySelector("select[name='field_value_bank']");
    const bankManualInput = bankWrapper?.querySelector("[data-manual-bank-input]");
    const bankManualToggle = bankWrapper?.querySelector("[data-manual-bank-toggle]");
    const textInput = textWrapper?.querySelector("input[name='field_value']");

    const syncFieldMode = () => {
      const isBank = fieldSelect.value === "banco";
      bankWrapper?.classList.toggle("is-hidden", !isBank);
      textWrapper?.classList.toggle("is-hidden", isBank);
      if (bankSelect) {
        bankSelect.required = isBank && !bankManualToggle?.checked;
        bankSelect.disabled = !isBank || !!bankManualToggle?.checked;
      }
      if (bankManualInput) {
        bankManualInput.required = isBank && !!bankManualToggle?.checked;
        bankManualInput.disabled = !isBank || !bankManualToggle?.checked;
      }
      if (textInput) textInput.required = false;
    };

    fieldSelect.addEventListener("change", syncFieldMode);
    syncFieldMode();
  });

  Array.from(document.querySelectorAll("[data-card-ref-select]")).forEach((select) => {
    const form = select.closest("form");
    const accountInput = form?.querySelector("input[name='account_id']");
    const cardInput = form?.querySelector("input[name='card_number']");

    const syncCardRef = () => {
      const [accountId, cardNumber] = String(select.value || "::").split("::");
      if (accountInput) accountInput.value = accountId || "";
      if (cardInput) cardInput.value = cardNumber || "";
    };

    select.addEventListener("change", syncCardRef);
    syncCardRef();
  });

  const brandMenu = document.querySelector("[data-brand-menu]");
  const brandSummary = brandMenu?.querySelector(".brand-summary");

  if (brandMenu && brandSummary) {
    document.addEventListener("click", (event) => {
      if (!brandMenu.open) return;
      if (brandMenu.contains(event.target)) return;
      brandMenu.open = false;
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && brandMenu.open) {
        brandMenu.open = false;
        brandSummary.focus();
      }
    });
  }

  const openNativeDatePicker = (input) => {
    if (!input) return;
    input.focus({ preventScroll: true });
    if (typeof input.showPicker === "function") {
      try {
        input.showPicker();
        return;
      } catch (error) {
        // Fallback for browsers that block showPicker outside specific contexts.
      }
    }
    input.click();
  };

  Array.from(document.querySelectorAll("[data-date-input]")).forEach((wrapper) => {
    const input = wrapper.querySelector("[data-date-picker]");
    const trigger = wrapper.querySelector("[data-open-date-picker]");
    if (!input) return;

    wrapper.addEventListener("click", (event) => {
      if (event.target.closest("[data-open-date-picker]")) return;
      openNativeDatePicker(input);
    });

    trigger?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openNativeDatePicker(input);
    });
  });

  restoreSetupScroll();
  setupField?.focus();

  const registerFlow = document.querySelector("[data-register-flow]");
  if (registerFlow) {
    const steps = Array.from(registerFlow.querySelectorAll("[data-register-step]"));
    const messages = document.getElementById("register-chat-messages");
    const composerBox = registerFlow.querySelector("[data-register-composer-box]");
    const composerInput = document.getElementById("register-chat-input");
    const prevButton = registerFlow.querySelector("[data-register-prev]");
    const skipButton = registerFlow.querySelector("[data-register-skip]");
    const nextButton = registerFlow.querySelector("[data-register-next]");
    const submitButton = registerFlow.querySelector("[data-register-submit]");
    const fallbackSubmit = registerFlow.querySelector("[data-register-fallback-submit]");
    const progressChip = registerFlow.querySelector("[data-register-progress]");
    const note = registerFlow.querySelector("[data-register-note]");
    if (steps.length && messages && composerInput && nextButton && submitButton) {
      const escapeHtml = (text) =>
        String(text || "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");

      const getInput = (step) => step?.querySelector("input, select, textarea");
      const isRequiredStep = (step) => step?.getAttribute("data-step-required") === "1";
      const stepKey = (step) => step?.getAttribute("data-step-key") || "";
      const stepLabel = (step) => step?.getAttribute("data-step-label") || stepKey(step);
      const stepQuestion = (step) => step?.getAttribute("data-step-question") || "Me envie a proxima informacao.";
      const stepDisplay = (step) => step?.getAttribute("data-step-display") || "";
      const stepPlaceholder = (step) => String(getInput(step)?.placeholder || "").trim();
      const rawStepValue = (step) => String(getInput(step)?.value || "");

      const normalizeStepValue = (step, value) => {
        const input = getInput(step);
        const inputType = String(input?.type || "text").toLowerCase();
        let normalized = String(value || "");
        if (inputType !== "password") {
          normalized = normalized.trim();
        }
        if (stepKey(step) === "estado") {
          normalized = normalized.toUpperCase().slice(0, 2);
        }
        return normalized;
      };

      const digitsOnly = (value) => String(value || "").replace(/\D+/g, "");

      const formatDocument = (value) => {
        const digits = digitsOnly(value);
        if (digits.length === 11) {
          return digits.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
        }
        if (digits.length === 14) {
          return digits.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, "$1.$2.$3/$4-$5");
        }
        return value;
      };

      const formatPhone = (value) => {
        const digits = digitsOnly(value);
        if (digits.length === 11) {
          return digits.replace(/(\d{2})(\d{5})(\d{4})/, "($1) $2-$3");
        }
        if (digits.length === 10) {
          return digits.replace(/(\d{2})(\d{4})(\d{4})/, "($1) $2-$3");
        }
        return value;
      };

      const formatCep = (value) => {
        const digits = digitsOnly(value);
        if (digits.length === 8) {
          return digits.replace(/(\d{5})(\d{3})/, "$1-$2");
        }
        return value;
      };

      const displayAnswer = (step, blankCopy = "Pular por enquanto") => {
        const normalized = normalizeStepValue(step, rawStepValue(step));
        if (!normalized) {
          return isRequiredStep(step) ? "Pendente" : blankCopy;
        }

        switch (stepDisplay(step)) {
          case "document":
            return formatDocument(normalized);
          case "telefone":
            return formatPhone(normalized);
          case "cep":
            return formatCep(normalized);
          case "estado":
            return normalized.toUpperCase();
          case "secret":
            return "Senha definida";
          case "secret-confirm":
            return "Confirmacao pronta";
          default:
            return normalized;
        }
      };

      const assistantBubble = (html) => `
        <article class="chat-bubble assistant register-chat-bubble">
          <div class="chat-text">${html}</div>
        </article>
      `;

      const userBubble = (text) => `
        <article class="chat-bubble user register-chat-bubble">
          <div class="chat-text">${escapeHtml(text)}</div>
        </article>
      `;

      const typingBubble = () =>
        assistantBubble(`
          <div class="register-chat-typing" aria-label="Digitando">
            <span></span>
            <span></span>
            <span></span>
          </div>
        `);

      const questionBubble = (step) => {
        return assistantBubble(`<strong>${escapeHtml(stepQuestion(step))}</strong>`);
      };

      const reviewBubble = () => {
        const rows = steps
          .map((step) => `
            <div class="register-chat-review-row">
              <span>${escapeHtml(stepLabel(step))}</span>
              <strong>${escapeHtml(displayAnswer(step, "Nao informado"))}</strong>
            </div>
          `)
          .join("");

        return assistantBubble(
          `<strong>Confere esses dados para mim?</strong><div class="register-chat-review">${rows}</div>`
        );
      };

      const resolveInitialStep = () => {
        const firstRequiredBlank = steps.findIndex((step) => isRequiredStep(step) && !normalizeStepValue(step, rawStepValue(step)));
        if (firstRequiredBlank >= 0) return firstRequiredBlank;

        const firstBlank = steps.findIndex((step) => !normalizeStepValue(step, rawStepValue(step)));
        if (firstBlank >= 0) return firstBlank;

        return Math.max(steps.length - 1, 0);
      };

      const renderConversation = () => {
        const answeredCount = currentMode === "confirm" ? steps.length : currentIndex;
        registerFlow.classList.toggle("is-chat-start", currentMode === "step" && answeredCount === 0);
        let markup = !isTyping || answeredCount > 0 ? questionBubble(steps[0]) : "";

        for (let index = 0; index < answeredCount; index += 1) {
          const step = steps[index];
          if (index > 0) {
            markup += questionBubble(step);
          }
          markup += userBubble(displayAnswer(step));
        }

        if (isTyping) {
          markup += typingBubble();
        } else if (currentMode === "confirm") {
          markup += reviewBubble();
        } else if (currentIndex > 0) {
          markup += questionBubble(steps[currentIndex]);
        }

        messages.innerHTML = markup;
        messages.scrollTop = messages.scrollHeight;
      };

      const syncCurrentHiddenValue = () => {
        const step = steps[currentIndex];
        const hiddenInput = getInput(step);
        const normalized = normalizeStepValue(step, composerInput.value);
        hiddenInput.value = normalized;
        if (stepKey(step) === "estado") {
          composerInput.value = normalized;
        }
        return normalized;
      };

      const resolveTypingDelay = () => {
        if (currentMode === "confirm") {
          return 700;
        }
        const step = steps[currentIndex];
        const promptLength = step ? stepQuestion(step).length : 24;
        return Math.min(880, Math.max(360, 180 + promptLength * 10));
      };

      const clearTypingTimer = () => {
        if (!typingTimer) return;
        window.clearTimeout(typingTimer);
        typingTimer = null;
      };

      const startTypingTransition = () => {
        if (!shouldAnimateTyping) {
          isTyping = false;
          renderRegisterConversation();
          return;
        }

        clearTypingTimer();
        isTyping = true;
        renderRegisterConversation();
        typingTimer = window.setTimeout(() => {
          typingTimer = null;
          isTyping = false;
          renderRegisterConversation();
        }, resolveTypingDelay());
      };

      const configureComposer = () => {
        if (isTyping) {
          registerFlow.classList.add("is-typing");
          registerFlow.classList.remove("is-confirming");
          composerBox?.classList.remove("is-confirming");
          composerInput.hidden = false;
          composerInput.disabled = true;
          composerInput.type = "text";
          composerInput.value = "";
          composerInput.placeholder = "Digitando...";
          composerInput.required = false;
          composerInput.removeAttribute("inputmode");
          composerInput.removeAttribute("maxlength");
          submitButton.hidden = true;
          submitButton.disabled = true;
          nextButton.hidden = false;
          nextButton.disabled = true;
          if (prevButton) {
            prevButton.disabled = true;
            prevButton.hidden = currentIndex === 0;
          }
          if (skipButton) {
            skipButton.disabled = true;
            skipButton.hidden = currentMode === "confirm" || isRequiredStep(steps[currentIndex]);
          }
          if (progressChip) {
            progressChip.textContent = currentMode === "confirm"
              ? "Revisao final"
              : `Etapa ${currentIndex + 1} de ${steps.length}`;
          }
          if (note) note.textContent = "Digitando...";
          if (fallbackSubmit) fallbackSubmit.hidden = true;
          return;
        }

        registerFlow.classList.remove("is-typing");
        if (currentMode === "confirm") {
          registerFlow.classList.add("is-confirming");
          composerBox?.classList.add("is-confirming");
          composerInput.hidden = true;
          composerInput.disabled = true;
          nextButton.hidden = true;
          nextButton.disabled = true;
          submitButton.hidden = false;
          submitButton.disabled = false;
          if (prevButton) prevButton.hidden = false;
          if (skipButton) skipButton.hidden = true;
          if (prevButton) prevButton.disabled = false;
          if (skipButton) skipButton.disabled = false;
          if (progressChip) progressChip.textContent = "Revisao final";
          if (note) note.textContent = "Confirmacao";
          if (fallbackSubmit) fallbackSubmit.hidden = true;
          window.requestAnimationFrame(() => submitButton.focus());
          return;
        }

        registerFlow.classList.remove("is-confirming");
        composerBox?.classList.remove("is-confirming");
        composerInput.hidden = false;
        composerInput.disabled = false;
        submitButton.hidden = true;
        submitButton.disabled = true;
        nextButton.hidden = false;
        nextButton.disabled = false;
        if (fallbackSubmit) fallbackSubmit.hidden = true;

        const step = steps[currentIndex];
        const hiddenInput = getInput(step);
        const inputType = String(hiddenInput?.type || "text").toLowerCase();
        const isLastStep = currentIndex === steps.length - 1;

        composerInput.type = inputType === "password" ? "password" : inputType === "email" ? "email" : "text";
        composerInput.value = rawStepValue(step);
        composerInput.placeholder = hiddenInput?.placeholder || "";
        composerInput.required = isRequiredStep(step);
        composerInput.minLength = hiddenInput?.minLength > 0 ? hiddenInput.minLength : 0;
        composerInput.autocomplete = hiddenInput?.autocomplete || "off";
        if (hiddenInput?.inputMode) {
          composerInput.setAttribute("inputmode", hiddenInput.inputMode);
        } else {
          composerInput.removeAttribute("inputmode");
        }
        if (hiddenInput?.maxLength > 0) {
          composerInput.maxLength = hiddenInput.maxLength;
        } else {
          composerInput.removeAttribute("maxlength");
        }

        nextButton.setAttribute("aria-label", isLastStep ? "Revisar" : "Enviar");
        nextButton.setAttribute("title", isLastStep ? "Revisar" : "Enviar");
        if (prevButton) prevButton.hidden = currentIndex === 0;
        if (skipButton) skipButton.hidden = isRequiredStep(step);
        if (prevButton) prevButton.disabled = false;
        if (skipButton) skipButton.disabled = false;
        if (progressChip) progressChip.textContent = `Etapa ${currentIndex + 1} de ${steps.length}`;
        if (note) {
          note.textContent = isRequiredStep(step) ? "Obrigatorio" : "Opcional";
        }

        window.requestAnimationFrame(() => {
          composerInput.focus();
          if (typeof composerInput.setSelectionRange === "function") {
            const caretPosition = composerInput.value.length;
            composerInput.setSelectionRange(caretPosition, caretPosition);
          }
        });
      };

      const validateCurrentStep = () => {
        const step = steps[currentIndex];
        const hiddenInput = getInput(step);
        const normalized = syncCurrentHiddenValue();

        if (!normalized && !isRequiredStep(step)) {
          hiddenInput.value = "";
          return true;
        }

        if (!composerInput.checkValidity()) {
          composerInput.reportValidity();
          return false;
        }

        hiddenInput.value = normalized;
        return true;
      };

      const renderRegisterConversation = () => {
        renderConversation();
        configureComposer();
      };

      let currentIndex = resolveInitialStep();
      let currentMode = "step";
      let isTyping = false;
      let typingTimer = null;
      const shouldAnimateTyping =
        !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
      registerFlow.classList.add("is-chat-ready");

      prevButton?.addEventListener("click", () => {
        clearTypingTimer();
        isTyping = false;
        if (currentMode === "confirm") {
          currentMode = "step";
          currentIndex = Math.max(steps.length - 1, 0);
          renderRegisterConversation();
          return;
        }
        currentIndex = Math.max(0, currentIndex - 1);
        renderRegisterConversation();
      });

      skipButton?.addEventListener("click", () => {
        clearTypingTimer();
        isTyping = false;
        const hiddenInput = getInput(steps[currentIndex]);
        hiddenInput.value = "";
        composerInput.value = "";
        if (currentIndex === steps.length - 1) {
          currentMode = "confirm";
        } else {
          currentIndex += 1;
        }
        startTypingTransition();
      });

      nextButton.addEventListener("click", () => {
        clearTypingTimer();
        isTyping = false;
        if (!validateCurrentStep()) return;
        if (currentIndex === steps.length - 1) {
          currentMode = "confirm";
        } else {
          currentIndex += 1;
        }
        startTypingTransition();
      });

      composerInput.addEventListener("input", () => {
        syncCurrentHiddenValue();
      });

      composerInput.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.shiftKey) return;
        event.preventDefault();
        nextButton.click();
      });

      startTypingTransition();
    }
  }

  const chatRoot = document.getElementById("chat-app");
  if (!chatRoot) return;

  const widgetToggle = document.getElementById("chat-widget-toggle");
  const widgetClose = document.getElementById("chat-widget-close");
  const sessionMenu = document.querySelector("[data-chat-sessions-menu]");
  const sessionList = document.getElementById("chat-session-list");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const submit = document.getElementById("chat-submit");
  const messages = document.getElementById("chat-messages");
  const sessionIdField = document.getElementById("chat-session-id");
  const newChatButton = document.getElementById("new-chat-button");
  const pendingBadge = document.getElementById("chat-pending-badge");
  const summaryBalance = document.getElementById("chat-summary-balance");

  const withCsrfHeaders = (headers = {}) =>
    csrfToken
      ? { ...headers, "X-CSRF-Token": csrfToken }
      : headers;

  const parseJsonResponse = async (response) => {
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401 && payload.login_url) {
      window.location.assign(payload.login_url);
      throw new Error("Sua sessao expirou. Entre novamente.");
    }
    return payload;
  };

  const escapeHtml = (text) =>
    String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

  const escapeAttr = (text) =>
    String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

  const bubbleHtml = (role, content, extraClass = "") => `
    <article class="${["chat-bubble", role, extraClass].filter(Boolean).join(" ")}">
      <div class="chat-text">${escapeHtml(content).replace(/\n/g, "<br>")}</div>
    </article>
  `;

  const activityHtml = (activity) => {
    if (!activity || !activity.title) return "";

    const actions = Array.isArray(activity.actions)
      ? activity.actions.map((action, index) => {
          const buttonClass = `chat-activity-option${index === 0 ? " is-primary" : ""}`;
          if (action.kind === "api") {
            return `
              <button
                class="${buttonClass}"
                type="button"
                data-chat-activity-action="${escapeAttr(action.action || "")}"
                data-chat-activity-account="${escapeAttr(action.account_id || "")}"
                data-chat-activity-card="${escapeAttr(action.card_number || "")}"
                data-chat-activity-field="${escapeAttr(action.field_key || "")}"
                data-chat-activity-value="${escapeAttr(action.value || "")}"
                data-chat-activity-label="${escapeAttr(action.label || "")}"
              >${escapeHtml(action.label || "Continuar")}</button>
            `;
          }
          const href = escapeAttr(action.href || "#");
          const target = String(action.href || "").startsWith("http") ? ' target="_blank" rel="noreferrer"' : "";
          return `<a class="${buttonClass}" href="${href}"${target}>${escapeHtml(action.label || "Abrir")}</a>`;
        }).join("")
      : "";

    return `
      <article class="chat-bubble assistant chat-bubble-activity" data-chat-activity>
        <div class="chat-text">
          <div class="chat-activity-card">
            <strong>${escapeHtml(activity.title || "")}</strong>
            <p>${escapeHtml(activity.content || "").replace(/\n/g, "<br>")}</p>
            <div class="chat-activity-actions">${actions}</div>
          </div>
        </div>
      </article>
    `;
  };

  const activitiesHtml = (activities) =>
    (Array.isArray(activities) ? activities : [])
      .map((activity) => activityHtml(activity))
      .join("");

  const sessionItemHtml = (session, currentSessionId) => `
    <button
      class="chat-session-item ${session.id === currentSessionId ? "is-active" : ""}"
      type="button"
      data-chat-session-target="${escapeAttr(session.id || "")}"
    >
      <strong>${escapeHtml(session.title || "Nova conversa")}</strong>
      <small>${escapeHtml(session.updated_at || session.created_at || "")}</small>
    </button>
  `;

  const emptyStateHtml = () => `
    <section class="gpt-empty-state">
      <div class="gpt-empty-copy">
        <h1>Como posso ajudar com suas financas?</h1>
        <p>Use o chat para perguntar sobre gastos, categorias, cartoes, recorrencias e variacoes por periodo.</p>
      </div>
      <div class="gpt-suggestion-grid">
        <button class="gpt-suggestion" type="button" data-chat-suggestion="Quanto gastei no cartao este mes?">
          <strong>Gastos do mes</strong>
          <small>Quanto gastei no cartao este mes?</small>
        </button>
        <button class="gpt-suggestion" type="button" data-chat-suggestion="Quais categorias mais consumiram meu dinheiro nos ultimos 30 dias?">
          <strong>Top categorias</strong>
          <small>Quais categorias mais consumiram meu dinheiro nos ultimos 30 dias?</small>
        </button>
        <button class="gpt-suggestion" type="button" data-chat-suggestion="Liste minhas ultimas movimentacoes relevantes.">
          <strong>Ultimas movimentacoes</strong>
          <small>Liste minhas ultimas movimentacoes relevantes.</small>
        </button>
        <button class="gpt-suggestion" type="button" data-chat-suggestion="Me explique como meu saldo evoluiu por mes.">
          <strong>Evolucao do saldo</strong>
          <small>Me explique como meu saldo evoluiu por mes.</small>
        </button>
      </div>
    </section>
  `;

  const autoResize = () => {
    if (!input) return;
    input.style.height = "0px";
    input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
  };

  const applyComposerMeta = (composer = {}) => {
    if (composer.placeholder && input) {
      input.setAttribute("placeholder", composer.placeholder);
    }
  };

  const setWidgetOpen = (open) => {
    chatRoot.classList.toggle("is-open", !!open);
    widgetToggle?.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      window.requestAnimationFrame(() => {
        messages.scrollTop = messages.scrollHeight;
        input?.focus();
      });
    }
  };

  const renderSessionList = (items = [], currentSessionId = "") => {
    if (!sessionList) return;
    sessionList.innerHTML = Array.isArray(items)
      ? items.map((item) => sessionItemHtml(item, currentSessionId)).join("")
      : "";
  };

  const renderMessages = (items, activities = []) => {
    if ((!Array.isArray(items) || !items.length) && !(Array.isArray(activities) && activities.length)) {
      messages.innerHTML = emptyStateHtml();
      messages.scrollTop = 0;
      return;
    }
    messages.innerHTML = [
      ...(Array.isArray(items) ? items.map((item) => bubbleHtml(item.role, item.content)) : []),
      activitiesHtml(activities),
    ].join("");
    messages.scrollTop = messages.scrollHeight;
  };

  const applyChatPayload = (payload = {}) => {
    const currentSessionId = String(payload.session_id || "").trim();
    if (currentSessionId) {
      sessionIdField.value = currentSessionId;
      chatRoot.dataset.sessionId = currentSessionId;
    }
    renderSessionList(payload.sessions || [], currentSessionId);
    renderMessages(payload.messages || [], payload.activities || []);
    applyComposerMeta(payload.composer || {});
    if (typeof payload.pending_authorizations !== "undefined" && pendingBadge) {
      pendingBadge.textContent = `${payload.pending_authorizations} autorizacoes pendentes`;
    }
    if (payload.summary_balance && summaryBalance) {
      summaryBalance.textContent = payload.summary_balance;
    }
    autoResize();
  };

  const renderPendingExchange = (userMessage) => {
    if (messages.querySelector(".gpt-empty-state")) {
      messages.innerHTML = "";
    }
    messages.insertAdjacentHTML("beforeend", bubbleHtml("user", userMessage));
    messages.insertAdjacentHTML("beforeend", bubbleHtml("assistant", "Processando sua solicitacao...", "is-loading"));
    messages.scrollTop = messages.scrollHeight;
  };

  const setLoading = (loading) => {
    submit.disabled = loading;
    submit.textContent = loading ? "Pensando..." : "Enviar";
  };

  const fetchSession = async (targetSessionId) => {
    const response = await fetch(`/api/chat/session/${encodeURIComponent(targetSessionId)}`);
    const payload = await parseJsonResponse(response);
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Falha ao carregar conversa.");
    }
    applyChatPayload(payload);
    setWidgetOpen(true);
  };

  const sendMessage = async () => {
    if (submit.disabled) return;
    const message = input.value.trim();
    if (!message) return;

    const previousMarkup = messages.innerHTML;
    input.value = "";
    autoResize();
    setLoading(true);
    renderPendingExchange(message);
    try {
      const response = await fetch("/api/chat/message", {
        method: "POST",
        headers: withCsrfHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          session_id: sessionIdField.value,
          message,
        }),
      });
      const payload = await parseJsonResponse(response);
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Falha ao enviar mensagem.");
      }
      applyChatPayload(payload);
    } catch (error) {
      messages.innerHTML = previousMarkup;
      input.value = message;
      autoResize();
      window.alert(error.message || "Falha ao enviar mensagem.");
    } finally {
      setLoading(false);
      input.focus();
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendMessage();
  });

  input?.addEventListener("input", autoResize);
  input?.addEventListener("keydown", async (event) => {
    if (event.key === "Enter" && !event.shiftKey && !submit.disabled) {
      event.preventDefault();
      await sendMessage();
    }
  });

  widgetToggle?.addEventListener("click", () => {
    setWidgetOpen(!chatRoot.classList.contains("is-open"));
  });

  widgetClose?.addEventListener("click", () => {
    setWidgetOpen(false);
  });

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-open-chat-widget]");
    if (!trigger) return;
    event.preventDefault();
    setWidgetOpen(true);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && chatRoot.classList.contains("is-open")) {
      setWidgetOpen(false);
    }
  });

  if (sessionMenu) {
    document.addEventListener("click", (event) => {
      if (!sessionMenu.open) return;
      if (sessionMenu.contains(event.target)) return;
      sessionMenu.open = false;
    });
  }

  newChatButton?.addEventListener("click", async () => {
    try {
      const response = await fetch("/api/chat/session", {
        method: "POST",
        headers: withCsrfHeaders(),
      });
      const payload = await parseJsonResponse(response);
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Falha ao criar conversa.");
      applyChatPayload(payload);
      setWidgetOpen(true);
    } catch (error) {
      window.alert(error.message || "Falha ao criar conversa.");
    }
  });

  const runActivityAction = async (button) => {
    const previousMarkup = messages.innerHTML;
    const action = button.getAttribute("data-chat-activity-action") || "";
    const accountId = button.getAttribute("data-chat-activity-account") || "";
    const cardNumber = button.getAttribute("data-chat-activity-card") || "";
    const fieldKey = button.getAttribute("data-chat-activity-field") || "";
    const value = button.getAttribute("data-chat-activity-value") || "";
    const label = button.getAttribute("data-chat-activity-label") || button.textContent.trim();
    if (!action) return;

    setLoading(true);
    renderPendingExchange(label);
    try {
      const response = await fetch("/api/chat/activity", {
        method: "POST",
        headers: withCsrfHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          session_id: sessionIdField.value,
          action,
          account_id: accountId,
          card_number: cardNumber,
          field_key: fieldKey,
          value,
          label,
        }),
      });
      const payload = await parseJsonResponse(response);
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Falha ao executar atividade.");
      }
      applyChatPayload(payload);
    } catch (error) {
      messages.innerHTML = previousMarkup;
      window.alert(error.message || "Falha ao executar atividade.");
    } finally {
      setLoading(false);
      input.focus();
    }
  };

  messages.addEventListener("click", async (event) => {
    const suggestion = event.target.closest("[data-chat-suggestion]");
    if (suggestion) {
      event.preventDefault();
      input.value = suggestion.getAttribute("data-chat-suggestion") || "";
      autoResize();
      input.focus();
      await sendMessage();
      return;
    }

    const button = event.target.closest("[data-chat-activity-action]");
    if (!button) return;
    event.preventDefault();
    await runActivityAction(button);
  });

  sessionList?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-chat-session-target]");
    if (!button) return;
    event.preventDefault();
    const targetSessionId = button.getAttribute("data-chat-session-target") || "";
    if (!targetSessionId) return;
    try {
      await fetchSession(targetSessionId);
      if (sessionMenu) sessionMenu.open = false;
    } catch (error) {
      window.alert(error.message || "Falha ao carregar conversa.");
    }
  });

  autoResize();
  applyComposerMeta({ placeholder: input?.getAttribute("placeholder") || "" });
  messages.scrollTop = messages.scrollHeight;
  if (chatRoot.dataset.autoOpen === "1") {
    setWidgetOpen(true);
  }
})();
