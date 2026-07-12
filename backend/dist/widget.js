(function () {
  // Capture currentScript src outside init in case it's run asynchronously
  const scriptElement = document.currentScript;
  const scriptSrc = scriptElement ? scriptElement.src : "";
  let defaultOrigin = "https://chatbot.codeqlik.cloud";
  if (scriptSrc) {
    try {
      defaultOrigin = new URL(scriptSrc).origin;
    } catch (e) { }
  }

  window.CodeQlikChat = {
    async init(config = {}) {
      // Clear session storage if URL contains reset params or if testing locally to assist development
      if (window.location.search.includes("reset") || window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost") {
        sessionStorage.removeItem("codeqlik_card_dismissed");
      }

      function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (char) => ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;"
        }[char]));
      }

      function escapeAttribute(value) {
        return escapeHtml(value);
      }

      function formatMessageText(text) {
        if (!text) return "";
        let formatted = text
          .replace(/\u2011/g, "-")
          .replace(/\u202f/g, " ")
          .replace(/\u2019/g, "'");

        formatted = formatted.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

        const lines = formatted.split("\n");
        const parsedLines = lines.map((line) => {
          const isListItem = /^\s*(\d+\.|\*|-)\s+/.test(line);
          if (isListItem) {
            return `<div style="padding-left:20px; text-indent:-20px; margin-bottom:4px;">${line}</div>`;
          }
          if (line.trim() === "") {
            return `<div style="height:12px;"></div>`;
          }
          return `<div style="margin-bottom:4px;">${line}</div>`;
        });

        return parsedLines.join("");
      }

      const settingsUrl = config.settingsUrl || (defaultOrigin + "/api/public/settings");
      const DEFAULT_LOGO_LIGHT = "/uploads/default_logo_light.png";
      const DEFAULT_LOGO_DARK = "/uploads/default_logo_dark.jpeg";

      let fetchedSettings = {};
      try {
        const res = await fetch(settingsUrl);
        if (res.ok) {
          fetchedSettings = await res.json();
        }
      } catch (err) {
        console.error("Failed to fetch widget settings:", err);
      }

      const cfg = {
        apiUrl: defaultOrigin + "/api/chat",
        title: "CodeQlik Assistant",
        subtitle: "Usually replies instantly",
        welcomeMessage: "Hi! How can we help you today?",
        placeholder: "Type your message...",
        primaryColor: "#ff7e21", // CodeQlik Accent Orange
        theme: "dark", // light | dark
        position: "bottom-right", // bottom-right | bottom-left
        width: "480px",
        height: "680px",
        logoUrl: DEFAULT_LOGO_LIGHT,
        logoUrlLight: DEFAULT_LOGO_LIGHT,
        logoUrlDark: DEFAULT_LOGO_DARK,
        botAvatar: "CQ",
        launcherIcon: "\uD83D\uDCAC",
        launcherSize: 60,
        launcherText: "",
        showLauncherGreeting: true,
        launcherGreeting: "Hello! Welcome to CodeQlik",
        launcherGreetingColor: "#ffffff",
        launcherGreetingBgStart: "#ff7e21",
        launcherGreetingBgEnd: "#ff477e",
        launcherGreetingWidth: 112,
        launcherGreetingBorderRadius: 20,
        launcherGreetingOffsetX: 52,
        launcherGreetingOffsetY: 54,
        showNewChat: true,
        footerText: "",
        suggestions: [],
        storage: "local", // local | session
        suggestionApiUrl: defaultOrigin + "/api/widget/suggestions",
        enableDynamicSuggestions: true,

        // Premium welcome card settings with text settings support
        launcherCardEnabled: fetchedSettings.launcherTextEnabled !== undefined ? fetchedSettings.launcherTextEnabled : (fetchedSettings.launcherCardEnabled !== undefined ? fetchedSettings.launcherCardEnabled : (fetchedSettings.showLauncherGreeting !== undefined ? fetchedSettings.showLauncherGreeting : true)),
        launcherCardLabel: fetchedSettings.launcherTextLabel || fetchedSettings.launcherCardLabel || "CODEQLIK AI",
        launcherCardTitle: fetchedSettings.launcherTextTitle || fetchedSettings.launcherCardTitle || "Let’s build something powerful.",
        launcherCardDescription: fetchedSettings.launcherTextDescription || fetchedSettings.launcherCardDescription || "Tell us what you’re planning, and our AI assistant will guide you.",
        launcherCardCTA: fetchedSettings.launcherTextCTA || fetchedSettings.launcherCardCTA || "Start Conversation →",
        launcherCardShowStatus: fetchedSettings.launcherTextShowStatus !== undefined ? fetchedSettings.launcherTextShowStatus : (fetchedSettings.launcherCardShowStatus !== undefined ? fetchedSettings.launcherCardShowStatus : true),
        launcherCardStatusText: fetchedSettings.launcherTextStatus || fetchedSettings.launcherCardStatusText || "CODEQLIK AI • ONLINE",
        launcherCardShowClose: fetchedSettings.launcherTextShowClose !== undefined ? fetchedSettings.launcherTextShowClose : (fetchedSettings.launcherCardShowClose !== undefined ? fetchedSettings.launcherCardShowClose : true),
        launcherCardBackground: fetchedSettings.launcherTextBackground || fetchedSettings.launcherCardBackground || "glassmorphism",
        launcherCardTextColor: fetchedSettings.launcherTextColor || fetchedSettings.launcherCardTextColor || "#ffffff",
        launcherCardAccentColor: fetchedSettings.launcherTextAccentColor || fetchedSettings.launcherCardAccentColor || "#ff7e21",
        launcherCardWidth: fetchedSettings.launcherTextWidth !== undefined ? Number(fetchedSettings.launcherTextWidth) : (fetchedSettings.launcherCardWidth !== undefined ? Number(fetchedSettings.launcherCardWidth) : 330),
        launcherCardBorderRadius: fetchedSettings.launcherTextBorderRadius !== undefined ? Number(fetchedSettings.launcherTextBorderRadius) : (fetchedSettings.launcherCardBorderRadius !== undefined ? Number(fetchedSettings.launcherCardBorderRadius) : 22),
        launcherCardAnimation: fetchedSettings.launcherTextAnimation || fetchedSettings.launcherCardAnimation || "ai-signal-boot",
        launcherCardDelay: fetchedSettings.launcherTextDelay !== undefined ? Number(fetchedSettings.launcherTextDelay) : (fetchedSettings.launcherCardDelay !== undefined ? Number(fetchedSettings.launcherCardDelay) : 1000),
        launcherCardAutoHide: fetchedSettings.launcherTextAutoHide !== undefined ? fetchedSettings.launcherTextAutoHide : (fetchedSettings.launcherCardAutoHide !== undefined ? fetchedSettings.launcherCardAutoHide : true),
        launcherCardVisibleDuration: fetchedSettings.launcherTextVisibleDuration !== undefined ? Number(fetchedSettings.launcherTextVisibleDuration) : (fetchedSettings.launcherCardVisibleDuration !== undefined ? Number(fetchedSettings.launcherCardVisibleDuration) : 6000),
        launcherCardShowOncePerSession: fetchedSettings.launcherTextShowOncePerSession !== undefined ? fetchedSettings.launcherTextShowOncePerSession : (fetchedSettings.launcherCardShowOncePerSession !== undefined ? fetchedSettings.launcherCardShowOncePerSession : true),
        launcherCardPosition: fetchedSettings.launcherTextPosition || fetchedSettings.launcherCardPosition || "top",
        launcherTextIdleAnimation: fetchedSettings.launcherTextIdleAnimation || "pulse",
        launcherTextCoreAnimation: fetchedSettings.launcherTextCoreAnimation || "rotate",

        ...fetchedSettings,
        ...config
      };

      const store = cfg.storage === "session" ? sessionStorage : localStorage;
      const key = "codeqlik_thread_id";

      let threadId = store.getItem(key);
      if (!threadId) {
        threadId = (typeof crypto !== 'undefined' && crypto.randomUUID)
          ? crypto.randomUUID()
          : Math.random().toString(36).substring(2, 15);
        store.setItem(key, threadId);
      }

      const right = cfg.position === "bottom-right";
      const sideCss = right ? "right:20px;" : "left:20px;";

      // Ensure that codeqlik_card_dismissed is cleaned up if showOncePerSession is false
      if (!cfg.launcherCardShowOncePerSession) {
        sessionStorage.removeItem("codeqlik_card_dismissed");
      }

      function resolveAssetUrl(value) {
        const raw = String(value || "").trim();
        if (!raw) return "";
        try {
          return new URL(raw, defaultOrigin).href;
        } catch (e) {
          return "";
        }
      }

      function isImageAssetValue(value) {
        const raw = String(value || "").trim();
        if (!raw) return false;
        return raw.startsWith("/uploads/")
          || raw.startsWith("data:image/")
          || /^https?:\/\//i.test(raw)
          || /\.(png|jpe?g|gif|webp|svg)(\?.*)?$/i.test(raw);
      }

      function safeHexColor(value, fallback) {
        const raw = String(value || "").trim();
        return /^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$/.test(raw) ? raw : fallback;
      }

      function clampNumber(value, min, max, fallback) {
        const numberValue = Number(value);
        return Number.isFinite(numberValue) ? Math.min(max, Math.max(min, numberValue)) : fallback;
      }

      const primary = safeHexColor(cfg.primaryColor, "#ff7e21");
      const isDark = cfg.theme === "dark";
      const launcherSize = clampNumber(cfg.launcherSize, 44, 96, 60);
      const launcherIconSize = cfg.launcherIconSize ? clampNumber(cfg.launcherIconSize, 14, 80, 28) : null;
      const launcherIconWhite = !!cfg.launcherIconWhite;
      const launcherImageInset = Math.max(5, Math.round(launcherSize * 0.12));
      const launcherBottomOffset = 20;
      const widgetBottomOffset = launcherBottomOffset + launcherSize + 15;

      // Extract launcher welcome card variables
      const cardEnabled = !!cfg.launcherCardEnabled;
      const cardLabel = cfg.launcherCardLabel;
      const cardTitle = cfg.launcherCardTitle;
      const cardDescription = cfg.launcherCardDescription;
      const cardCTA = cfg.launcherCardCTA;
      const cardShowStatus = !!cfg.launcherCardShowStatus;
      const cardStatusText = cfg.launcherCardStatusText;
      const cardShowClose = !!cfg.launcherCardShowClose;
      const cardBgMode = cfg.launcherCardBackground;
      const cardTextColor = safeHexColor(cfg.launcherCardTextColor, "#ffffff");
      const cardAccentColor = safeHexColor(cfg.launcherCardAccentColor, "#ff7e21");
      const cardWidth = clampNumber(cfg.launcherCardWidth, 200, 450, 330);
      const cardBorderRadius = clampNumber(cfg.launcherCardBorderRadius, 8, 36, 22);
      const cardAnimation = cfg.launcherCardAnimation;
      const cardDelay = clampNumber(cfg.launcherCardDelay, 0, 10000, 1000);
      const cardAutoHide = !!cfg.launcherCardAutoHide;
      const cardVisibleDuration = clampNumber(cfg.launcherCardVisibleDuration, 1000, 30000, 6000);
      const cardOncePerSession = !!cfg.launcherCardShowOncePerSession;
      const cardPosition = cfg.launcherCardPosition;
      const txtFontSize = clampNumber(cfg.launcherCardFontSize || cfg.launcherGreetingFontSize, 9, 24, 13);

      const fallbackLogo = resolveAssetUrl(isDark ? DEFAULT_LOGO_DARK : DEFAULT_LOGO_LIGHT);
      const configuredLogo = isDark
        ? (cfg.logoUrlDark || cfg.logoUrl || DEFAULT_LOGO_DARK)
        : (cfg.logoUrlLight || cfg.logoUrl || DEFAULT_LOGO_LIGHT);
      const activeLogo = resolveAssetUrl(configuredLogo) || fallbackLogo;

      const bg = isDark ? "linear-gradient(180deg, #0d0a1b 0%, #06050a 100%)" : "rgba(255, 255, 255, 0.98)";
      const text = isDark ? "#f3f4f6" : "#111827";
      const botBg = isDark ? "rgba(255, 255, 255, 0.06)" : "#f3f4f6";
      const userBg = isDark ? "linear-gradient(135deg, #ff7e21 0%, #ff477e 100%)" : primary;
      const borderColor = isDark ? "rgba(255, 126, 33, 0.25)" : "rgba(0, 0, 0, 0.08)";
      const headBg = isDark ? "rgba(255, 255, 255, 0.02)" : primary;
      const headText = "#ffffff";

      function renderLogoImage(altText = "CodeQlik logo") {
        if (!activeLogo) {
          return escapeHtml(cfg.botAvatar || "CQ");
        }
        const fallbackHandler = fallbackLogo && fallbackLogo !== activeLogo
          ? ` onerror="this.onerror=null;this.src='${escapeAttribute(fallbackLogo)}'"`
          : "";
        return `<img src="${escapeAttribute(activeLogo)}" alt="${escapeAttribute(altText)}"${fallbackHandler}>`;
      }

      function renderFooterText(value) {
        return escapeHtml(value || "").replace(/CodeQlik/gi, '<span class="cq-footer-brand">$&</span>');
      }

      function renderLauncherIcon() {
        const customIcon = String(cfg.launcherIcon || "").trim();
        if (customIcon && isImageAssetValue(customIcon)) {
          const iconUrl = resolveAssetUrl(customIcon);
          if (iconUrl) {
            return `<img src="${escapeAttribute(iconUrl)}" alt="Chat">`;
          }
        }
        if (customIcon && customIcon !== "\uD83D\uDCAC") {
          return `<span class="cq-launcher-custom-icon">${escapeHtml(customIcon)}</span>`;
        }
        return `
          <svg class="cq-launcher-chat-icon" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
            <path d="M14 5.5c-5.5 0-10 3.35-10 7.48 0 2.55 1.72 4.8 4.35 6.15l-.62 3.12 3.42-2.03c.9.16 1.85.25 2.85.25 5.5 0 10-3.35 10-7.49S19.5 5.5 14 5.5Z" fill="#f8fbff"></path>
            <path d="M18.4 18.95c-1.28.66-2.78 1.02-4.4 1.02-1 0-1.95-.09-2.85-.25l-3.42 2.03.62-3.12c-1.04-.53-1.94-1.22-2.63-2.03 1.74.92 3.92 1.45 6.26 1.45 2.42 0 4.66-.56 6.42-1.52v2.42Z" fill="#c7d2fe" opacity="0.95"></path>
          </svg>
        `;
      }

      function highlightText(val, isTitle = false) {
        let escaped = escapeHtml(val || "");
        escaped = escaped.replace(/CodeQlik/gi, `<span class="cq-greeting-brand">$&</span>`);
        if (isTitle) {
          if (escaped.toLowerCase().includes("powerful")) {
            escaped = escaped.replace(/powerful/i, `<span class="cq-ai-signal__highlight">$&<span class="cq-ai-signal__highlight-point"></span></span>`);
          } else {
            // highlight the last word
            const words = escaped.split(" ");
            if (words.length > 0) {
              const lastWord = words[words.length - 1];
              const cleanLast = lastWord.replace(/[.,\/#!$%\^&\*;:{}=\-_`~()]/g, "");
              if (cleanLast.length > 0) {
                escaped = escaped.replace(lastWord, `<span class="cq-ai-signal__highlight">${lastWord}<span class="cq-ai-signal__highlight-point"></span></span>`);
              }
            }
          }
        }
        return escaped;
      }

      const formattedTitle = highlightText(cardTitle, true);
      const formattedDescription = highlightText(cardDescription, false);

      function renderLauncherGreetingBadge() {
        if (!cardEnabled) return "";
        if (cardOncePerSession && sessionStorage.getItem("codeqlik_card_dismissed")) {
          return "";
        }

        return `
          <div id="cq-launcher-card" tabindex="0" class="cq-ai-signal cq-launcher-card--hidden cq-anim-${cardAnimation} cq-pos-${cardPosition}" aria-label="Welcome Invitation">
            <div class="cq-ai-signal__top-border"></div>
            <div class="cq-ai-signal__ambient-glow-blue"></div>
            <div class="cq-ai-signal__ambient-glow-orange"></div>
            <div class="cq-ai-signal__grid-bg"></div>
            <div class="cq-ai-signal__scan-line-panel"></div>
            <div class="cq-ai-signal__connector"></div>

            ${cardShowClose ? `
              <button id="cq-launcher-card__close" class="cq-ai-signal__close" aria-label="Close invitation">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            ` : ""}
            
            <div class="cq-ai-signal__panel">
              <div class="cq-ai-signal__core-container">
                <div class="cq-ai-signal__core">
                  <div class="cq-ai-signal__core-inner">
                    ${renderLogoImage("AI Core logo")}
                  </div>
                  <div class="cq-ai-signal__core-ring"></div>
                  <div class="cq-ai-signal__core-dot"></div>
                </div>
              </div>

              <div class="cq-ai-signal__vertical-accent"></div>

              <div class="cq-ai-signal__content">
                <div class="cq-ai-signal__status-container">
                  <div class="cq-ai-signal__status">
                    <span class="cq-ai-signal__status-dot"></span>
                    <span class="cq-ai-signal__status-text">${escapeHtml(cardLabel)}</span>
                  </div>
                  <div class="cq-ai-signal__status-scan-line"></div>
                </div>

                <h3 class="cq-ai-signal__heading">${formattedTitle}</h3>
                <p class="cq-ai-signal__description">${formattedDescription}</p>

                <div class="cq-ai-signal__cta-container">
                  <div class="cq-ai-signal__cta-line"></div>
                  <div class="cq-ai-signal__cta">
                    <span>${escapeHtml(cardCTA)}</span>
                    <svg class="cq-ai-signal__cta-arrow" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <line x1="5" y1="12" x2="19" y2="12"></line>
                      <polyline points="12 5 19 12 12 19"></polyline>
                    </svg>
                  </div>
                </div>
              </div>
            </div>
          </div>
        `;
      }

      // Configure position styles dynamically
      let posCss = "";
      if (cardPosition === "top") {
        posCss = `
          bottom: calc(${launcherBottomOffset + launcherSize + 16}px + env(safe-area-inset-bottom));
          ${right ? `right: 20px;` : `left: 20px;`}
        `;
      } else {
        // "left"
        posCss = `
          ${right ? `right: calc(${20 + launcherSize + 16}px);` : `left: calc(${20 + launcherSize + 16}px);`}
          bottom: calc(${launcherBottomOffset + Math.round(launcherSize * 0.1)}px + env(safe-area-inset-bottom));
        `;
      }

      document.head.insertAdjacentHTML("beforeend", `
        <style>
          #cq-msgs::-webkit-scrollbar { width: 6px; }
          #cq-msgs::-webkit-scrollbar-track { background: transparent; }
          #cq-msgs::-webkit-scrollbar-thumb {
            background: ${isDark ? "rgba(255, 255, 255, 0.12)" : "rgba(0, 0, 0, 0.12)"};
            border-radius: 99px;
          }
          #cq-msgs::-webkit-scrollbar-thumb:hover {
            background: ${isDark ? "rgba(255, 255, 255, 0.24)" : "rgba(0, 0, 0, 0.24)"};
          }

          #cq-btn {
            position: fixed;
            ${sideCss}
            bottom: calc(${launcherBottomOffset}px + env(safe-area-inset-bottom));
            min-width: ${launcherSize}px;
            width: ${launcherSize}px;
            height: ${launcherSize}px;
            border-radius: 999px;
            border: none;
            background: linear-gradient(135deg, #ff7e21 0%, #ff477e 100%) !important;
            color: #fff;
            font-size: 22px;
            cursor: pointer;
            z-index: 2147483647 !important;
            padding: 0;
            box-shadow: 0 10px 25px rgba(255, 71, 126, 0.4), 0 4px 10px rgba(15, 23, 42, 0.12) !important;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: inherit;
            font-weight: 600;
            overflow: hidden;
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.3s ease;
          }
          #cq-btn img {
            width: ${launcherIconSize ? launcherIconSize + "px" : `calc(100% - ${launcherImageInset * 2}px)`};
            height: ${launcherIconSize ? launcherIconSize + "px" : `calc(100% - ${launcherImageInset * 2}px)`};
            object-fit: contain;
            display: block;
            filter: ${launcherIconWhite ? "brightness(0) invert(1)" : "none"};
          }
          #cq-btn .cq-launcher-chat-icon {
            width: ${launcherIconSize ? launcherIconSize + "px" : `${Math.round(launcherSize * 0.47)}px`};
            height: ${launcherIconSize ? launcherIconSize + "px" : `${Math.round(launcherSize * 0.47)}px`};
            display: block;
            filter: drop-shadow(0 2px 3px rgba(15, 23, 42, 0.18));
          }
          #cq-btn .cq-launcher-custom-icon {
            display: block;
            font-size: ${launcherIconSize ? launcherIconSize + "px" : `${Math.round(launcherSize * 0.36)}px`};
            line-height: 1;
          }
          #cq-btn:hover {
            transform: scale(1.08) translateY(-2px);
            box-shadow: 0 18px 40px rgba(255, 71, 126, 0.55), 0 8px 18px rgba(15, 23, 42, 0.18) !important;
          }

          /* CodeQlik AI Signal Welcome Card styling */
          #cq-launcher-card.cq-ai-signal {
            position: fixed;
            ${posCss}
            width: ${cardWidth}px;
            min-height: 105px;
            box-sizing: border-box;
            padding: 16px;
            border-radius: ${cardBorderRadius}px;
            color: ${cardTextColor};
            font-family: 'Outfit', 'Inter', system-ui, -apple-system, sans-serif;
            z-index: 2147483646 !important;
            cursor: pointer;
            
            background: linear-gradient(135deg, rgba(7, 9, 13, 0.96), rgba(14, 17, 23, 0.94)) !important;
            border: 1px solid rgba(255, 132, 43, 0.35) !important;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.55),
                        0 10px 35px rgba(255, 120, 35, 0.14),
                        0 0 0 1px rgba(255, 132, 43, 0.05),
                        inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
            backdrop-filter: blur(18px) saturate(130%);
            -webkit-backdrop-filter: blur(18px) saturate(130%);
            
            overflow: hidden;
            transition: opacity 0.4s ease, transform 0.4s ease, visibility 0.4s ease, border-color 0.3s, box-shadow 0.3s;
          }

          #cq-launcher-card:focus-visible {
            outline: 2px solid #ff7e21 !important;
            outline-offset: 2px !important;
          }

          .cq-ai-signal__panel {
            display: flex;
            align-items: flex-start;
            gap: 14px;
            position: relative;
            z-index: 2;
          }

          /* Ambient glow blue behind AI core */
          .cq-ai-signal__ambient-glow-blue {
            position: absolute;
            top: -20px;
            left: -20px;
            width: 100px;
            height: 100px;
            background: radial-gradient(circle, rgba(0, 150, 255, 0.15) 0%, rgba(0, 0, 0, 0) 70%);
            pointer-events: none;
          }
          /* Orange glow near lower-right corner */
          .cq-ai-signal__ambient-glow-orange {
            position: absolute;
            bottom: -20px;
            right: -20px;
            width: 100px;
            height: 100px;
            background: radial-gradient(circle, rgba(255, 126, 33, 0.12) 0%, rgba(0, 0, 0, 0) 70%);
            pointer-events: none;
          }
          /* Grid background */
          .cq-ai-signal__grid-bg {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0.04;
            background-image: linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px),
                              linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px);
            background-size: 10px 10px;
            pointer-events: none;
          }
          /* One faint orange light beam passing through the top border */
          .cq-ai-signal__top-border {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 1px;
            background: linear-gradient(90deg, transparent, #ff7e21, transparent);
            animation: cqTopBorderLight 4s linear infinite;
          }
          @keyframes cqTopBorderLight {
            0% { background-position: -200px 0; }
            100% { background-position: 400px 0; }
          }
          /* One soft scanning light passing across the panel after entrance */
          .cq-ai-signal__scan-line-panel {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 126, 33, 0.05), transparent);
            transform: translateX(-100%);
            pointer-events: none;
            animation: cqPanelScan 1.2s ease-in-out 1.5s 1 forwards;
          }
          @keyframes cqPanelScan {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
          }

          /* Left AI Core */
          .cq-ai-signal__core-container {
            flex-shrink: 0;
            width: 44px;
            height: 44px;
            position: relative;
            opacity: 0;
            transform: translateY(15px) scale(0.65);
            animation: cqCoreActivate 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) 0.5s forwards;
            transition: transform 0.3s ease;
          }
          @keyframes cqCoreActivate {
            to {
              opacity: 1;
              transform: translateY(0) scale(1);
            }
          }
          .cq-ai-signal__core {
            width: 44px;
            height: 44px;
            border-radius: 50%;
            background: #0f121d;
            border: 1px solid rgba(255, 132, 43, 0.25);
            box-shadow: inset 0 0 8px rgba(255, 132, 43, 0.1);
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
          }
          .cq-ai-signal__core-inner {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            animation: cqLogoPulse 0.4s ease-out 0.9s 1;
          }
          @keyframes cqLogoPulse {
            0% { box-shadow: inset 0 0 0 rgba(255, 126, 33, 0); }
            50% { box-shadow: inset 0 0 15px rgba(255, 126, 33, 0.6); filter: brightness(1.2); }
            100% { box-shadow: inset 0 0 0 rgba(255, 126, 33, 0); }
          }
          .cq-ai-signal__core-inner img {
            width: 80%;
            height: 80%;
            object-fit: contain;
          }

          /* Outer ring draws itself */
          .cq-ai-signal__core-ring {
            position: absolute;
            top: -3px;
            left: -3px;
            right: -3px;
            bottom: -3px;
            border: 1.5px solid transparent;
            border-top-color: #ff7e21;
            border-right-color: #ff7e21;
            border-radius: 50%;
            animation: cqRingDraw 0.8s cubic-bezier(0.4, 0, 0.2, 1) 0.5s forwards,
                       cqRingRotate 0.8s cubic-bezier(0.4, 0, 0.2, 1) 0.5s forwards;
          }
          @keyframes cqRingDraw {
            0% { border-color: transparent; }
            100% { border-color: rgba(255, 126, 33, 0.6); }
          }
          @keyframes cqRingRotate {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }

          /* Orbiting light dot */
          .cq-ai-signal__core-dot {
            position: absolute;
            top: -3px;
            left: 50%;
            width: 4px;
            height: 4px;
            background: #ff7e21;
            border-radius: 50%;
            box-shadow: 0 0 8px #ff7e21;
            transform-origin: 0px 25px;
            animation: cqDotOrbit 0.8s cubic-bezier(0.4, 0, 0.2, 1) 0.5s forwards;
          }
          @keyframes cqDotOrbit {
            0% { transform: rotate(0deg) translateX(-50%); opacity: 1; }
            100% { transform: rotate(180deg) translateX(-50%); opacity: 0; }
          }

          /* One thin vertical accent line near content */
          .cq-ai-signal__vertical-accent {
            width: 1px;
            align-self: stretch;
            background: linear-gradient(to bottom, transparent, rgba(255, 132, 43, 0.3), transparent);
            flex-shrink: 0;
          }

          /* Speech bubble tail pointer pointing towards launcher */
          .cq-ai-signal__connector {
            position: absolute;
            bottom: -6px;
            right: 25px;
            width: 10px;
            height: 10px;
            transform: rotate(45deg);
            background: #07090d;
            border-right: 1px solid rgba(255, 132, 43, 0.35);
            border-bottom: 1px solid rgba(255, 132, 43, 0.35);
            z-index: 1;
            transition: border-color 0.3s;
          }

          /* Close button */
          .cq-ai-signal__close {
            position: absolute;
            top: 10px;
            right: 10px;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: #9ca3af;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s;
            pointer-events: auto !important;
            z-index: 10 !important;
          }
          .cq-ai-signal__close:hover {
            background: rgba(255, 126, 33, 0.1);
            border-color: rgba(255, 126, 33, 0.5);
            color: #ff7e21;
          }

          /* Right Content Area */
          .cq-ai-signal__content {
            flex: 1;
            display: flex;
            flex-direction: column;
          }

          /* Status Label */
          .cq-ai-signal__status-container {
            position: relative;
            overflow: hidden;
            display: inline-block;
            align-self: flex-start;
          }
          .cq-ai-signal__status {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 6px;
            opacity: 0;
            animation: cqStatusReveal 0.25s ease-out 0.8s forwards;
          }
          @keyframes cqStatusReveal {
            to { opacity: 1; }
          }
          .cq-ai-signal__status-text {
            font-size: 9.5px;
            font-weight: 600;
            letter-spacing: 1.4px;
            color: #ff7e21;
            text-transform: uppercase;
          }
          .cq-ai-signal__status-scan-line {
            position: absolute;
            top: 0;
            left: 0;
            height: 100%;
            width: 4px;
            background: #ff7e21;
            box-shadow: 0 0 8px #ff7e21;
            transform: translateX(-100%);
            animation: cqStatusScan 0.5s ease-in-out 0.8s forwards;
          }
          @keyframes cqStatusScan {
            0% { transform: translateX(-100%); opacity: 1; }
            100% { transform: translateX(350px); opacity: 0; }
          }

          /* Online dot status change and idle pulse */
          .cq-ai-signal__status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            display: inline-block;
            background: #ff7e21;
            box-shadow: 0 0 6px #ff7e21;
            position: relative;
            animation: cqDotStatusChange 0.3s ease-out 1s forwards,
                       cqStatusDotIdle 3s ease-in-out 2s infinite;
          }
          @keyframes cqDotStatusChange {
            0% { background: #ff7e21; box-shadow: 0 0 6px #ff7e21; }
            100% { background: #10b981; box-shadow: 0 0 6px #10b981; }
          }
          @keyframes cqStatusDotIdle {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.3); opacity: 0.7; }
          }
          .cq-ai-signal__status-dot::after {
            content: "";
            position: absolute;
            top: -3px;
            left: -3px;
            right: -3px;
            bottom: -3px;
            border-radius: 50%;
            border: 1px solid #10b981;
            opacity: 0;
            animation: cqDotGreenPulse 1s ease-out 1.2s forwards;
          }
          @keyframes cqDotGreenPulse {
            0% { transform: scale(1); opacity: 1; }
            100% { transform: scale(3); opacity: 0; }
          }

          /* Heading */
          .cq-ai-signal__heading {
            font-size: 16px;
            font-weight: 700;
            line-height: 1.25;
            color: #ffffff;
            margin: 0 0 6px 0;
            opacity: 0;
            filter: blur(4px);
            transform: translateY(7px);
            clip-path: polygon(0 100%, 100% 100%, 100% 100%, 0 100%);
            animation: cqTextReveal 0.4s cubic-bezier(0.16, 1, 0.3, 1) 0.9s forwards;
          }

          /* Special Highlight Animation */
          .cq-ai-signal__highlight {
            position: relative;
            display: inline-block;
            background: linear-gradient(90deg, #ff7e21, #ff9e53, #ff7e21);
            background-size: 200% 100%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: cqGradientSweep 1.2s ease-in-out 1.2s 1 forwards;
          }
          @keyframes cqGradientSweep {
            0% { background-position: 100% 0%; }
            100% { background-position: -100% 0%; }
          }
          .cq-ai-signal__highlight::after {
            content: "";
            position: absolute;
            bottom: -2px;
            left: 0;
            width: 0;
            height: 1px;
            background: #ff7e21;
            animation: cqUnderlineDraw 0.6s ease-out 1.5s forwards;
          }
          @keyframes cqUnderlineDraw {
            to { width: 100%; }
          }
          .cq-ai-signal__highlight-point {
            position: absolute;
            bottom: -4px;
            left: 0;
            width: 4px;
            height: 4px;
            background: #ff7e21;
            border-radius: 50%;
            box-shadow: 0 0 6px #ff7e21;
            opacity: 0;
            animation: cqPointTravel 1s cubic-bezier(0.25, 0.46, 0.45, 0.94) 1.8s forwards;
          }
          @keyframes cqPointTravel {
            0% { left: 0; opacity: 1; }
            50% { left: 100%; opacity: 1; }
            100% { left: 150px; opacity: 0; }
          }

          /* Description */
          .cq-ai-signal__description {
            font-size: 12px;
            font-weight: 400;
            line-height: 1.45;
            color: #9ca3af;
            margin: 0 0 12px 0;
            opacity: 0;
            filter: blur(4px);
            transform: translateY(7px);
            clip-path: polygon(0 100%, 100% 100%, 100% 100%, 0 100%);
            animation: cqTextReveal 0.4s cubic-bezier(0.16, 1, 0.3, 1) 1.0s forwards;
          }

          /* CTA */
          .cq-ai-signal__cta-container {
            opacity: 0;
            filter: blur(4px);
            transform: translateY(7px);
            animation: cqTextReveal 0.4s cubic-bezier(0.16, 1, 0.3, 1) 1.1s forwards;
            margin-top: auto;
          }
          .cq-ai-signal__cta-line {
            height: 1px;
            background: linear-gradient(90deg, rgba(255, 126, 33, 0.4), transparent);
            width: 0;
            margin-bottom: 12px;
            animation: cqCtaLineDraw 0.6s ease-out 1.1s forwards;
          }
          @keyframes cqCtaLineDraw {
            to { width: 100%; }
          }
          .cq-ai-signal__cta {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            font-weight: 600;
            color: #ff7e21;
            cursor: pointer;
            transition: color 0.2s, text-shadow 0.2s;
            align-self: flex-start;
          }
          .cq-ai-signal__cta:hover {
            color: #ff9e53;
            text-shadow: 0 0 8px rgba(255, 126, 33, 0.3);
          }
          .cq-ai-signal__cta-arrow {
            transform: translateX(-10px);
            opacity: 0;
            animation: cqArrowArrive 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94) 1.3s forwards,
                       cqCtaArrowIdle 8s ease-in-out 5s infinite;
            transition: transform 0.2s ease;
          }
          @keyframes cqArrowArrive {
            0% { transform: translateX(-15px); opacity: 0; }
            70% { transform: translateX(5px); opacity: 1; }
            100% { transform: translateX(0); opacity: 1; }
          }
          @keyframes cqCtaArrowIdle {
            0%, 90%, 100% { transform: translateX(0); }
            95% { transform: translateX(4px); }
          }

          @keyframes cqTextReveal {
            to {
              opacity: 1;
              filter: blur(0);
              transform: translateY(0);
              clip-path: polygon(0 0, 100% 0, 100% 100%, 0 100%);
            }
          }

          /* Hover interaction styling rules */
          #cq-launcher-card:hover {
            transform: translateY(-3px) !important;
            border-color: rgba(255, 132, 43, 0.65) !important;
            box-shadow: 0 25px 70px rgba(0, 0, 0, 0.65),
                        0 15px 45px rgba(255, 120, 35, 0.22),
                        0 0 0 1px rgba(255, 132, 43, 0.1) !important;
          }
          #cq-launcher-card:hover .cq-ai-signal__core-container {
            transform: rotate(2deg) scale(1.02) !important;
          }
          #cq-launcher-card:hover .cq-ai-signal__cta-arrow {
            transform: translateX(4px) !important;
          }
          #cq-launcher-card:hover .cq-ai-signal__connector {
            border-color: rgba(255, 132, 43, 0.6) !important;
          }

          /* Hidden/Fadeout state transitions */
          .cq-launcher-card--hidden {
            opacity: 0 !important;
            visibility: hidden !important;
            pointer-events: none !important;
          }
          .cq-launcher-card--animate-entry {
            visibility: visible !important;
            pointer-events: auto !important;
          }
          .cq-launcher-card--fadeout {
            opacity: 0 !important;
            transform: translateY(12px) scale(0.9) !important;
            transition: all 0.4s ease;
          }

          @keyframes cqGreetingMinimal {
            0% { opacity: 0; }
            100% { opacity: 1; }
          }
          @keyframes cqLauncherSoftBounce {
            0%, 100% { transform: translateY(0); }
            40% { transform: translateY(-12px) scaleY(1.05); }
            60% { transform: translateY(2px) scaleY(0.97); }
            80% { transform: translateY(-3px); }
          }

          /* Keyframe Animations for Capsule Expansion */
          @keyframes cqCapsuleExpand {
            0% {
              opacity: 0;
              transform: translateY(12px) scaleX(0.12) scaleY(0.65);
              border-radius: 999px;
              filter: blur(8px);
            }
            40% {
              opacity: 1;
              transform: translateY(6px) scaleX(1.04) scaleY(0.65);
              border-radius: 999px;
              filter: blur(4px);
            }
            75% {
              transform: translateY(-2px) scaleX(0.98) scaleY(1.02);
              border-radius: 24px;
              filter: blur(0);
            }
            100% {
              opacity: 1;
              transform: translateY(0) scaleX(1) scaleY(1);
              border-radius: 22px;
              filter: blur(0);
            }
          }

          /* Apply animation rules based on config setting */
          #cq-launcher-card.cq-anim-ai-signal-boot.cq-launcher-card--animate-entry {
            animation: cqCapsuleExpand 0.7s cubic-bezier(0.16, 1, 0.3, 1) forwards;
          }
          #cq-launcher-card.cq-anim-energy-capsule.cq-launcher-card--animate-entry {
            animation: cqCapsuleExpand 0.5s cubic-bezier(0.22, 1, 0.36, 1) forwards;
          }
          #cq-launcher-card.cq-anim-signal-scan.cq-launcher-card--animate-entry {
            animation: cqGreetingFadeUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards;
          }
          #cq-launcher-card.cq-anim-core-activation.cq-launcher-card--animate-entry {
            animation: cqGreetingSoftPop 0.7s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
          }
          #cq-launcher-card.cq-anim-soft-tech-reveal.cq-launcher-card--animate-entry {
            animation: cqGreetingFadeUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
          }
          #cq-launcher-card.cq-anim-minimal.cq-launcher-card--animate-entry {
            animation: cqGreetingMinimal 0.4s ease forwards;
          }
          #cq-launcher-card.cq-anim-none.cq-launcher-card--animate-entry {
            opacity: 1 !important;
            visibility: visible !important;
            transform: none !important;
          }

          .cq-launcher-soft-bounce {
            animation: cqLauncherSoftBounce 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94) !important;
          }

          /* Spark & Trail */
          .cq-ai-signal__spark {
            width: 6px;
            height: 6px;
            background: #ff7e21;
            border-radius: 50%;
            box-shadow: 0 0 12px 3px #ff7e21;
            animation: cqSparkMove 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94) 0.25s forwards;
          }
          .cq-ai-signal__trail {
            width: 2px;
            height: 0;
            background: linear-gradient(to top, transparent, #ff7e21);
            box-shadow: 0 0 6px rgba(255, 126, 33, 0.5);
            transform-origin: bottom;
            animation: cqTrailDraw 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94) 0.25s forwards;
          }

          @keyframes cqSparkMove {
            0% { transform: translateY(0) translateX(0); opacity: 1; }
            100% { transform: translateY(-80px) translateX(-20px); opacity: 0; }
          }
          @keyframes cqTrailDraw {
            0% { height: 0; transform: skewX(0deg); opacity: 1; }
            100% { height: 80px; transform: skewX(-15deg); opacity: 0; }
          }

          /* Closing transitions */
          .cq-ai-signal--closing .cq-ai-signal__cta-container {
            opacity: 0;
            transform: translateY(-5px);
            transition: opacity 0.2s, transform 0.2s;
          }
          .cq-ai-signal--closing .cq-ai-signal__description {
            opacity: 0;
            transform: translateY(-5px);
            transition: opacity 0.25s, transform 0.25s;
          }
          .cq-ai-signal--closing .cq-ai-signal__heading {
            opacity: 0;
            transform: translateX(10px);
            transition: opacity 0.3s, transform 0.3s;
          }
          .cq-ai-signal--closing .cq-ai-signal__core-container {
            transform: scale(0);
            opacity: 0;
            transition: transform 0.3s, opacity 0.3s;
          }
          .cq-ai-signal--closing {
            transform: translateY(20px) scaleX(0.12) scaleY(0.12) !important;
            opacity: 0 !important;
            border-radius: 999px !important;
            transition: all 0.55s cubic-bezier(0.16, 1, 0.3, 1) !important;
          }

          /* Launcher energy pulse & confirmation pulse */
          .cq-launcher-energy-pulse {
            position: relative;
          }
          .cq-launcher-energy-pulse::after {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            border-radius: 50%;
            box-shadow: 0 0 0 0px #ff7e21;
            animation: cqLauncherPulseAnim 0.25s ease-out forwards;
          }
          @keyframes cqLauncherPulseAnim {
            0% { box-shadow: 0 0 0 0px rgba(255, 126, 33, 0.7); transform: scale(0.8); opacity: 0.7; }
            100% { box-shadow: 0 0 0 20px rgba(255, 126, 33, 0); transform: scale(1.25); opacity: 0; }
          }

          .cq-launcher-confirm-pulse {
            animation: cqLauncherConfirmPulseAnim 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards;
          }
          @keyframes cqLauncherConfirmPulseAnim {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.15); box-shadow: 0 0 20px #ff7e21 !important; }
          }

          /* Media Reduced Motion */
          @media (prefers-reduced-motion: reduce) {
            #cq-launcher-card.cq-launcher-card--animate-entry {
              animation: cqGreetingMinimal 0.5s ease forwards !important;
            }
          }

          #cq-box {
            position: fixed;
            ${sideCss}
            bottom: calc(${widgetBottomOffset}px + env(safe-area-inset-bottom));
            width: ${cfg.width};
            height: ${cfg.height};
            background: ${bg};
            color: ${text};
            border-radius: 20px;
            border: 1px solid ${borderColor};
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            z-index: 2147483647 !important;
            font-family: system-ui, -apple-system, sans-serif;
            
            visibility: hidden;
            opacity: 0;
            pointer-events: none;
            transform: translateY(20px) scale(.95);
            transition: visibility 0.3s, opacity 0.3s ease, transform 0.3s ease;
          }
          
          #cq-box.cq-open {
            visibility: visible;
            opacity: 1;
            pointer-events: auto !important;
            transform: translateY(0) scale(1);
          }

          #cq-head {
            background: ${headBg};
            color: ${headText};
            padding: 18px;
            display: flex;
            align-items: center;
            gap: 12px;
            border-bottom: 1px solid ${isDark ? "rgba(255, 126, 33, 0.25)" : primary};
          }
          #cq-logo {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.1);
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            font-weight: 700;
            color: ${primary};
            border: 1.5px solid ${isDark ? "rgba(255, 126, 33, 0.55)" : "rgba(0, 0, 0, 0.05)"};
          }
          #cq-logo img { width: 100%; height: 100%; object-fit: contain; display: block; }
          #cq-title-container { flex: 1; }
          #cq-title { font-weight: 700; font-size: 16px; letter-spacing: -0.01em; }
          #cq-subtitle {
            font-size: 12px;
            opacity: 0.85;
            margin-top: 2px;
            display: flex;
            align-items: center;
            gap: 5px;
          }
          #cq-subtitle::before {
            content: "";
            display: inline-block;
            width: 7px;
            height: 7px;
            background: #10b981;
            border-radius: 50%;
            box-shadow: 0 0 8px #10b981;
          }
          #cq-new {
            background: rgba(255, 255, 255, 0.12);
            color: #fff;
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            padding: 6px 12px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.2s;
          }
          #cq-new:hover {
            background: rgba(255, 255, 255, 0.2);
            border-color: rgba(255, 255, 255, 0.3);
          }

          #cq-msgs {
            flex: 1;
            padding: 16px;
            overflow: auto;
            font-size: 14px;
            display: flex;
            flex-direction: column;
            gap: 12px;
          }
          .cq-msg-row {
            display: flex;
            width: 100%;
            align-items: flex-end;
            gap: 8px;
            animation: cqFadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards;
          }
          .cq-msg-row.cq-user-row {
            justify-content: flex-end;
          }
          .cq-msg-row.cq-bot-row {
            justify-content: flex-start;
          }
          .cq-msg-avatar {
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background: ${isDark ? "#0f172a" : primary};
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 700;
            overflow: hidden;
            flex-shrink: 0;
            border: 1px solid ${borderColor};
          }
          .cq-msg-avatar img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
          }
          .cq-msg {
            padding: 12px 14px;
            border-radius: 16px;
            max-width: 78%;
            white-space: pre-wrap;
            line-height: 1.45;
          }
          .cq-user {
            background: ${userBg};
            color: #fff;
            border-bottom-right-radius: 4px;
            box-shadow: 0 4px 12px rgba(255, 126, 33, 0.15);
          }
          .cq-bot {
            background: ${botBg};
            color: ${text};
            border-bottom-left-radius: 4px;
            border: 1px solid ${isDark ? `${primary}33` : borderColor};
          }

          .cq-typing-indicator {
            display: flex;
            align-items: center;
            gap: 4px;
            padding: 4px 2px;
          }
          .cq-typing-indicator span {
            display: inline-block;
            width: 8px;
            height: 8px;
            background-color: ${isDark ? "rgba(255, 255, 255, 0.7)" : "rgba(0, 0, 0, 0.5)"};
            border-radius: 50%;
            animation: cqBounce 1.4s infinite ease-in-out both;
          }
          .cq-typing-indicator span:nth-child(1) {
            animation-delay: -0.32s;
          }
          .cq-typing-indicator span:nth-child(2) {
            animation-delay: -0.16s;
          }
          @keyframes cqBounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1.0); }
          }

          @keyframes cqFadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
          }

          #cq-suggestions {
            display: flex !important;
            gap: 8px !important;
            flex-wrap: nowrap !important;
            overflow-x: auto !important;
            overflow-y: hidden !important;
            padding: 0 16px 12px !important;
            scrollbar-width: none !important;
            -ms-overflow-style: none !important;
            -webkit-overflow-scrolling: touch !important;
          }
          #cq-suggestions::-webkit-scrollbar {
            display: none !important;
          }
          .cq-suggestion {
            flex-shrink: 0;
            white-space: nowrap;
            border: 1px solid ${isDark ? "rgba(255, 255, 255, 0.15)" : "rgba(0, 0, 0, 0.15)"};
            background: ${isDark ? "rgba(255, 255, 255, 0.03)" : "rgba(0, 0, 0, 0.02)"};
            color: ${text};
            border-radius: 999px;
            padding: 8px 14px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
            transition: all 0.2s;
          }
          .cq-suggestion:hover {
            border-color: ${primary};
            background: ${isDark ? "rgba(255, 126, 33, 0.08)" : "rgba(255, 126, 33, 0.05)"};
            color: ${isDark ? "#ffffff" : primary};
            transform: translateY(-1px);
          }
          .cq-inline-options {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 12px;
          }
          .cq-fixed-option {
            border: 1px solid ${primary};
            background: ${isDark ? "rgba(255, 126, 33, 0.14)" : "rgba(255, 126, 33, 0.10)"};
            color: ${isDark ? "#ffffff" : primary};
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 700;
            transition: all 0.2s;
          }
          .cq-fixed-option:hover:not(:disabled) {
            background: ${primary};
            color: #ffffff;
          }
          .cq-fixed-option:disabled {
            opacity: 0.45;
            cursor: not-allowed;
          }

          #cq-form {
            display: flex !important;
            border-top: 1px solid ${borderColor};
            background: ${isDark ? "rgba(20, 20, 26, 0.95)" : "#ffffff"} !important;
            padding: 12px 16px !important;
            align-items: center !important;
            gap: 10px !important;
            pointer-events: auto !important;
          }

          #cq-input {
            flex: 1 !important;
            height: 40px !important;
            padding: 0 14px !important;
            border: 1px solid gray !important;
            border-radius: 10px !important;
            outline: none !important;
            background: ${isDark ? "rgba(255, 255, 255, 0.05)" : "#f9fafb"} !important;
            color: ${text} !important;
            font-size: 14px !important;
            font-family: inherit !important;
            pointer-events: auto !important;
            cursor: text !important;
            user-select: text !important;
            -webkit-user-select: text !important;
          }
          #cq-input:focus {
            border-color: ${primary} !important;
          }

          #cq-send {
            background: ${primary};
            color: #fff;
            border: 0;
            height: 40px;
            width: 40px;
            min-width: 40px;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
          }
          #cq-send:hover {
            background: ${isDark ? "#e06310" : "#ff8c3a"};
            box-shadow: 0 4px 12px rgba(255, 126, 33, 0.2);
          }

          #cq-footer {
            font-size: 11px;
            text-align: center;
            padding: 8px;
            color: ${isDark ? "#e5e7eb" : "#374151"};
            border-top: 1px solid ${borderColor};
            background: ${isDark ? "#0f172a" : "rgba(0, 0, 0, 0.02)"};
            font-weight: 600;
          }
          #cq-footer .cq-footer-brand {
            color: ${primary};
            font-weight: 800;
          }

          #cq-close {
            background: transparent;
            border: none;
            color: #fff;
            cursor: pointer;
            padding: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0.85;
            transition: all 0.2s;
            flex-shrink: 0;
            border-radius: 6px;
          }
          #cq-close:hover {
            opacity: 1;
            background: rgba(255, 255, 255, 0.15);
          }

          @media (max-width: 560px), (max-height: 560px) {
            #cq-box {
              width: 100% !important;
              height: 100vh !important;
              height: 100dvh !important;
              min-width: 0 !important;
              min-height: 0 !important;
              max-height: 100vh !important;
              max-height: 100dvh !important;
              bottom: 0 !important;
              right: 0 !important;
              left: 0 !important;
              border-radius: 0 !important;
              max-width: 100vw !important;
              border: none !important;
            }
            #cq-head {
              padding: calc(14px + env(safe-area-inset-top)) 16px 14px !important;
              gap: 8px !important;
            }
            .cq-msg-row.cq-bot-row {
              display: grid !important;
              grid-template-columns: 28px minmax(0, 1fr) !important;
              align-items: flex-end !important;
              column-gap: 8px !important;
            }
            .cq-msg-row.cq-user-row {
              display: flex !important;
            }
            .cq-msg-avatar {
              width: 28px !important;
              height: 28px !important;
            }
            .cq-msg {
              padding: 10px 12px !important;
              font-size: 13.5px !important;
              max-width: 85% !important;
            }
            .cq-bot-row .cq-msg {
              grid-column: 2 !important;
              width: auto !important;
              max-width: 88% !important;
              white-space: normal !important;
            }
            .cq-bot-row .cq-msg-avatar {
              grid-column: 1 !important;
            }
            .cq-bot-row .cq-msg > div {
              white-space: normal !important;
            }
            .cq-user-row .cq-msg {
              width: auto !important;
              max-width: 88% !important;
            }
            #cq-suggestions {
              gap: 6px !important;
              padding: 0 12px 8px !important;
            }
            .cq-suggestion {
              padding: 7px 11px !important;
              font-size: 11.5px !important;
            }
            #cq-form {
              padding: 9px 12px calc(9px + env(safe-area-inset-bottom)) !important;
              gap: 8px !important;
            }

            /* Responsive greeting welcome card on mobile */
            #cq-launcher-card.cq-ai-signal {
              width: calc(100vw - 28px) !important;
              max-width: 300px !important;
              padding: 12px !important;
              ${right ? "right: 14px !important;" : "left: 14px !important;"}
              bottom: calc(${launcherBottomOffset + launcherSize + 14}px + env(safe-area-inset-bottom)) !important;
              border-radius: ${cardBorderRadius - 4}px !important;
            }
            .cq-ai-signal__panel {
              gap: 10px !important;
            }
            .cq-ai-signal__core-container {
              width: 38px !important;
              height: 38px !important;
            }
            .cq-ai-signal__core {
              width: 38px !important;
              height: 38px !important;
            }
            .cq-ai-signal__core-ring {
              top: -2px; left: -2px; right: -2px; bottom: -2px;
            }
            .cq-ai-signal__core-dot {
              transform-origin: 0px 19px;
            }
            .cq-ai-signal__heading {
              font-size: 14.5px !important;
            }
            .cq-ai-signal__description {
              font-size: 11.5px !important;
              margin-bottom: 8px !important;
            }
            
            /* Very small screens: stacked layout */
            @media (max-width: 360px) {
              .cq-ai-signal__panel {
                flex-direction: column !important;
                align-items: flex-start !important;
              }
              .cq-ai-signal__vertical-accent {
                display: none !important;
              }
            }
          }
        </style>
      `);

      document.body.insertAdjacentHTML("beforeend", `
        ${renderLauncherGreetingBadge()}
        <button id="cq-btn" title="${escapeAttribute(cfg.launcherGreeting || "Open chat")}" aria-label="${escapeAttribute(cfg.launcherGreeting || "Open chat")}">${renderLauncherIcon()}</button>
        <div id="cq-box">
          <div id="cq-head">
            <div id="cq-logo">${renderLogoImage("CodeQlik logo")}</div>
            <div id="cq-title-container">
              <div id="cq-title">${cfg.title}</div>
              <div id="cq-subtitle">${cfg.subtitle}</div>
            </div>
            ${cfg.showNewChat ? `<button id="cq-new">New</button>` : ""}
            <button id="cq-close" title="Close chat" aria-label="Close chat">
              <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
              </svg>
            </button>
          </div>
          <div id="cq-msgs">
            <div class="cq-msg-row cq-bot-row">
              <div class="cq-msg-avatar" style="overflow:hidden;">${renderLogoImage("Bot avatar")}</div>
              <div class="cq-msg cq-bot">${formatMessageText(cfg.welcomeMessage)}</div>
            </div>
          </div>
          <div id="cq-suggestions"></div>
          <div id="cq-form">
            <input id="cq-input" placeholder="${cfg.placeholder}" />
            <button id="cq-send" title="Send message">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
          </div>
          ${cfg.footerText ? `<div id="cq-footer">${renderFooterText(cfg.footerText)}</div>` : ""}
        </div>
      `);

      const $ = (id) => document.getElementById(id);
      const box = $("cq-box");
      const msgs = $("cq-msgs");
      const input = $("cq-input");
      const suggestions = $("cq-suggestions");
      const sendBtn = $("cq-send");
      const launcherCard = $("cq-launcher-card");

      let fixedOptions = [];
      const defaultPlaceholder = cfg.placeholder;

      function updateSendButtonState() {
        const hasText = input.value.trim().length > 0;
        sendBtn.disabled = !hasText;
        sendBtn.style.opacity = hasText ? "1" : "0.55";
        sendBtn.style.cursor = hasText ? "pointer" : "not-allowed";
      }

      updateSendButtonState();
      input.oninput = updateSendButtonState;

      // Handle launcher card events
      if (launcherCard) {
        let clicked = false;
        launcherCard.onclick = (e) => {
          e.stopPropagation();
          if (clicked) return;
          clicked = true;

          // Open chat window immediately
          setBoxOpen(true);

          // Fade and scale invitation towards launcher
          launcherCard.classList.add("cq-ai-signal--closing");
          setTimeout(() => {
            launcherCard.style.display = "none";
          }, 400);
        };

        launcherCard.onkeydown = (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            e.stopPropagation();
            setBoxOpen(true);
          }
        };

        const cardCloseBtn = $("cq-launcher-card__close");
        if (cardCloseBtn) {
          cardCloseBtn.onclick = (e) => {
            e.stopPropagation();
            dismissCard(true); // explicit close click
          };
        }

        // Trigger reveal animation sequence (AI Signal Boot)
        setTimeout(() => {
          if (launcherCard && !box.classList.contains("cq-open") && !sessionStorage.getItem("codeqlik_card_dismissed")) {
            const btn = $("cq-btn");
            if (btn) {
              const rect = btn.getBoundingClientRect();

              // Add energy pulse class to launcher (Stage 1)
              btn.classList.add("cq-launcher-energy-pulse");

              // Create spark & trail (Stage 2)
              const spark = document.createElement("div");
              spark.className = "cq-ai-signal__spark";

              const trail = document.createElement("div");
              trail.className = "cq-ai-signal__trail";

              const bottomOffset = window.innerHeight - rect.top;
              const rightOffset = window.innerWidth - rect.right;

              spark.style.cssText = `position:fixed; bottom:${bottomOffset}px; right:${rightOffset + rect.width / 2}px; z-index:2147483647;`;
              trail.style.cssText = `position:fixed; bottom:${bottomOffset}px; right:${rightOffset + rect.width / 2}px; z-index:2147483646;`;

              document.body.appendChild(spark);
              document.body.appendChild(trail);

              // Clean up spark/trail and reveal card (Stage 3)
              setTimeout(() => {
                spark.remove();
                trail.remove();
                btn.classList.remove("cq-launcher-energy-pulse");

                launcherCard.classList.remove("cq-launcher-card--hidden");
                launcherCard.classList.add("cq-launcher-card--animate-entry");

                // Launcher soft reaction bounce on settle
                setTimeout(() => {
                  btn.classList.add("cq-launcher-soft-bounce");
                  setTimeout(() => {
                    btn.classList.remove("cq-launcher-soft-bounce");
                  }, 600);
                }, 800);

              }, 550); // Stage 1 (250ms) + Stage 2 (300ms) = 550ms
            } else {
              launcherCard.classList.remove("cq-launcher-card--hidden");
              launcherCard.classList.add("cq-launcher-card--animate-entry");
            }

            // Auto-hide handling
            if (cardAutoHide) {
              setTimeout(() => {
                if (launcherCard && !box.classList.contains("cq-open") && !launcherCard.classList.contains("cq-ai-signal--closing")) {
                  dismissCard(false); // implicit hide (no session storage dismissed key)
                }
              }, cardVisibleDuration + 1000);
            }
          }
        }, cardDelay);
      }

      // Keyboard Esc close support
      window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && launcherCard && !launcherCard.classList.contains("cq-ai-signal--closing")) {
          dismissCard(true); // explicit escape key close
        }
      });

      function dismissCard(explicit = false) {
        if (launcherCard) {
          launcherCard.classList.add("cq-ai-signal--closing");
          if (explicit && cardOncePerSession) {
            sessionStorage.setItem("codeqlik_card_dismissed", "true");
          }
          setTimeout(() => {
            const btn = $("cq-btn");
            if (btn && explicit) {
              btn.classList.add("cq-launcher-confirm-pulse");
              setTimeout(() => btn.classList.remove("cq-launcher-confirm-pulse"), 600);
            }
            launcherCard.style.display = "none";
          }, 600);
        }
      }

      function add(text, type, onComplete) {
        const row = document.createElement("div");
        row.className = `cq-msg-row cq-${type === "typing" ? "bot" : type}-row`;

        if (type === "bot" || type === "typing") {
          const avatar = document.createElement("div");
          avatar.className = "cq-msg-avatar";
          avatar.style.overflow = "hidden";
          avatar.innerHTML = renderLogoImage("Bot avatar");
          row.appendChild(avatar);
        }

        const bubble = document.createElement("div");
        bubble.className = `cq-msg cq-${type === "typing" ? "bot" : type}`;
        if (type === "typing") {
          bubble.innerHTML = `<div class="cq-typing-indicator"><span></span><span></span><span></span></div>`;
        } else {
          bubble.textContent = "";
        }
        row.appendChild(bubble);

        msgs.appendChild(row);
        msgs.scrollTop = msgs.scrollHeight;

        if (type === "bot" && text) {
          const words = text.split(" ");
          let index = 0;
          let currentText = "";

          function typeNextWord() {
            if (index < words.length) {
              currentText += (index === 0 ? "" : " ") + words[index];
              bubble.innerHTML = formatMessageText(currentText);
              index++;
              msgs.scrollTop = msgs.scrollHeight;
              setTimeout(typeNextWord, 40);
            } else {
              bubble.innerHTML = formatMessageText(text);
              if (typeof onComplete === "function") {
                onComplete();
              }
            }
          }
          typeNextWord();
        } else {
          if (type !== "typing") {
            bubble.textContent = text;
          }
          if (typeof onComplete === "function") {
            onComplete();
          }
        }

        return row;
      }

      function renderSuggestions(items = []) {
        suggestions.innerHTML = "";
        const list = Array.isArray(items) ? items.slice(0, 4) : [];
        list.forEach((s) => {
          const btn = document.createElement("button");
          btn.className = "cq-suggestion";
          btn.textContent = s;
          btn.onclick = (e) => {
            e.stopPropagation();
            send(s);
          };
          suggestions.appendChild(btn);
        });
        setTimeout(() => {
          msgs.scrollTop = msgs.scrollHeight;
        }, 50);
      }

      function clearFixedOptions() {
        fixedOptions = [];
        input.placeholder = defaultPlaceholder;
        msgs.querySelectorAll(".cq-fixed-option").forEach((btn) => {
          btn.disabled = true;
        });
        updateSendButtonState();
      }

      function renderFixedOptions(items = [], row = null) {
        fixedOptions = Array.isArray(items) ? items.filter(Boolean) : [];
        suggestions.innerHTML = "";
        input.disabled = false;
        input.placeholder = defaultPlaceholder;
        updateSendButtonState();

        if (fixedOptions.length === 0) {
          return;
        }

        const bubble = row ? row.querySelector(".cq-msg") : null;
        if (!bubble) {
          return;
        }

        const existing = bubble.querySelector(".cq-inline-options");
        if (existing) {
          existing.remove();
        }

        const optionBox = document.createElement("div");
        optionBox.className = "cq-inline-options";

        fixedOptions.forEach((option) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "cq-fixed-option";
          btn.textContent = option.label || option.value;
          btn.onclick = (e) => {
            e.stopPropagation();
            if (fixedOptions.length === 0) return;
            send(option.value || option.label, true);
          };
          optionBox.appendChild(btn);
        });

        bubble.appendChild(optionBox);

        setTimeout(() => {
          msgs.scrollTop = msgs.scrollHeight;
        }, 50);
      }

      async function send(messageOverride, fromFixedOption = false) {
        const message = String(messageOverride || input.value || "").trim();
        if (!message) return;

        add(message, "user");
        input.value = "";
        clearFixedOptions();
        updateSendButtonState();
        suggestions.innerHTML = "";

        const typing = add("", "typing");

        try {
          const res = await fetch(cfg.apiUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message, thread_id: threadId })
          });

          const data = await res.json();
          typing.remove();

          if (data.thread_id) {
            threadId = data.thread_id;
            store.setItem(key, threadId);
          }

          const botText = data.reply || data.response || data.message || "Sorry, I couldn't get a response.";
          const nextFixedOptions = Array.isArray(data.fixed_options) ? data.fixed_options : [];
          let botRow;
          botRow = add(botText, "bot", () => {
            if (nextFixedOptions.length > 0) {
              renderFixedOptions(nextFixedOptions, botRow);
            } else if (cfg.enableDynamicSuggestions) {
              loadDynamicSuggestions(botText, message);
            }
          });
        } catch {
          clearFixedOptions();
          typing.remove();
          add("Connection error. Please try again.", "bot");
        }
      }

      async function loadDynamicSuggestions(latestBotMessage, latestUserMessage = "") {
        try {
          const recentMessages = Array.from(msgs.querySelectorAll(".cq-msg"))
            .slice(-10)
            .map((el) => {
              const row = el.closest(".cq-msg-row");
              const role = row && row.classList.contains("cq-user-row") ? "user" : "assistant";
              return { role, content: el.textContent || "" };
            });

          const res = await fetch(cfg.suggestionApiUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              latest_bot_message: latestBotMessage,
              latest_user_message: latestUserMessage,
              recent_messages: recentMessages,
              company_name: cfg.title || "CodeQlik",
              assistant_name: cfg.botAvatar || "Assistant",
              business_context: "software development, websites, mobile apps, AI automation, CRM, SaaS, cloud, IT consulting",
              language_hint: "auto",
              max_suggestions: 4,
              thread_id: threadId
            })
          });

          if (!res.ok) {
            renderSuggestions([]);
            return;
          }

          const data = await res.json();
          renderSuggestions(data.suggestions || []);
        } catch (err) {
          renderSuggestions([]);
        }
      }

      box.onclick = (e) => e.stopPropagation();
      $("cq-form").onclick = (e) => e.stopPropagation();
      input.onclick = (e) => e.stopPropagation();

      function setBoxOpen(open) {
        const launcher = $("cq-btn");
        if (open) {
          box.classList.add("cq-open");
          if (launcherCard) {
            launcherCard.style.display = "none";
          }
          if (window.innerWidth <= 560) {
            launcher.style.display = "none";
          }
          setTimeout(() => {
            input.removeAttribute('disabled');
            input.focus();
          }, 100);
        } else {
          box.classList.remove("cq-open");
          launcher.style.display = "flex";
          if (launcherCard) {
            launcherCard.classList.remove("cq-ai-signal--closing", "cq-launcher-card--animate-entry");
            launcherCard.classList.add("cq-launcher-card--hidden");
            launcherCard.style.display = !sessionStorage.getItem("codeqlik_card_dismissed") && cfg.launcherCardEnabled ? "block" : "none";

            // Re-trigger the animation on closing chat
            setTimeout(() => {
              if (launcherCard && !box.classList.contains("cq-open") && !sessionStorage.getItem("codeqlik_card_dismissed")) {
                launcherCard.classList.remove("cq-launcher-card--hidden");
                launcherCard.classList.add("cq-launcher-card--animate-entry");
              }
            }, 500);
          }
        }
      }

      $("cq-btn").onclick = (e) => {
        e.stopPropagation();
        const isOpen = box.classList.contains("cq-open");
        setBoxOpen(!isOpen);
      };

      if ($("cq-close")) {
        $("cq-close").onclick = (e) => {
          e.stopPropagation();
          setBoxOpen(false);
        };
      }

      window.addEventListener("resize", () => {
        const isOpen = box.classList.contains("cq-open");
        const launcher = $("cq-btn");
        if (isOpen && window.innerWidth <= 560) {
          launcher.style.display = "none";
          if (launcherCard) launcherCard.style.display = "none";
        } else {
          launcher.style.display = "flex";
          if (launcherCard) {
            launcherCard.style.display = !isOpen && !sessionStorage.getItem("codeqlik_card_dismissed") && cfg.launcherCardEnabled ? "block" : "none";
          }
        }
      });

      if ($("cq-new")) {
        $("cq-new").onclick = (e) => {
          e.stopPropagation();
          threadId = (typeof crypto !== 'undefined' && crypto.randomUUID)
            ? crypto.randomUUID()
            : Math.random().toString(36).substring(2, 15);
          store.setItem(key, threadId);
          clearFixedOptions();
          msgs.innerHTML = `
            <div class="cq-msg-row cq-bot-row">
              <div class="cq-msg-avatar" style="overflow:hidden;">${renderLogoImage("Bot avatar")}</div>
              <div class="cq-msg cq-bot">${cfg.welcomeMessage}</div>
            </div>
          `;
          if (Array.isArray(cfg.suggestions) && cfg.suggestions.length > 0) {
            renderSuggestions(cfg.suggestions);
          } else if (cfg.enableDynamicSuggestions) {
            loadDynamicSuggestions(cfg.welcomeMessage);
          } else {
            renderSuggestions([]);
          }
        };
      }

      $("cq-send").onclick = (e) => {
        e.stopPropagation();
        send();
      };

      input.onkeydown = (e) => {
        e.stopPropagation();
        if (e.key === "Enter") send();
      };

      if (Array.isArray(cfg.suggestions) && cfg.suggestions.length > 0) {
        renderSuggestions(cfg.suggestions);
      } else if (cfg.enableDynamicSuggestions) {
        loadDynamicSuggestions(cfg.welcomeMessage);
      } else {
        renderSuggestions([]);
      }
    }
  };
})();