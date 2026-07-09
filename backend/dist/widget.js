(function () {
  // Capture currentScript src outside init in case it's run asynchronously
  const scriptElement = document.currentScript;
  const scriptSrc = scriptElement ? scriptElement.src : "";
  let defaultOrigin = "https://chatbot.codeqlik.cloud";
  if (scriptSrc) {
    try {
      defaultOrigin = new URL(scriptSrc).origin;
    } catch (e) {}
  }

  window.CodeQlikChat = {
    async init(config = {}) {
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
        logoUrl: "",
        botAvatar: "CQ",
        launcherIcon: "💬",
        launcherText: "",
        showNewChat: true,
        footerText: "",
        suggestions: [],
        storage: "local", // local | session
        suggestionApiUrl: defaultOrigin + "/api/widget/suggestions",
        enableDynamicSuggestions: true,
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
      
      const isDark = cfg.theme === "dark";
      const bg = isDark ? "rgba(13, 13, 17, 0.88)" : "rgba(255, 255, 255, 0.95)";
      const text = isDark ? "#f3f4f6" : "#111827";
      const botBg = isDark ? "rgba(255, 255, 255, 0.06)" : "#f3f4f6";
      const userBg = cfg.primaryColor;
      const borderColor = isDark ? "rgba(255, 255, 255, 0.08)" : "rgba(0, 0, 0, 0.08)";
      const headBg = isDark ? "rgba(20, 20, 26, 0.95)" : cfg.primaryColor;
      const headText = "#ffffff";

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
            bottom: 20px;
            min-width: 60px;
            height: 60px;
            border-radius: 999px;
            border: 0;
            background: ${cfg.primaryColor};
            color: #fff;
            font-size: 22px;
            cursor: pointer;
            z-index: 2147483647 !important;
            padding: 0 20px;
            box-shadow: 0 8px 32px rgba(255, 126, 33, 0.25);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            font-family: inherit;
            font-weight: 600;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
          }
          #cq-btn:hover {
            transform: scale(1.05) translateY(-2px);
            box-shadow: 0 12px 36px rgba(255, 126, 33, 0.35);
          }

          #cq-box {
            position: fixed;
            ${sideCss}
            bottom: 95px;
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
            z-index: 2147483647 !important; /* Forces layout to sit over absolute frameworks */
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
            border-bottom: 1px solid ${borderColor};
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
            color: ${cfg.primaryColor};
            border: 1.5px solid ${isDark ? "rgba(255, 255, 255, 0.15)" : "rgba(0, 0, 0, 0.05)"};
          }
          #cq-logo img { width: 100%; height: 100%; object-fit: cover; }
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
            background: ${isDark ? "rgba(255, 255, 255, 0.1)" : cfg.primaryColor};
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
            object-fit: cover;
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
            border: 1px solid ${borderColor};
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
            0%, 80%, 100% { 
              transform: scale(0);
            } 40% { 
              transform: scale(1.0);
            }
          }

          @keyframes cqFadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
          }

          #cq-suggestions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            padding: 0 16px 12px;
          }
          .cq-suggestion {
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
            border-color: ${cfg.primaryColor};
            background: ${isDark ? "rgba(255, 126, 33, 0.08)" : "rgba(255, 126, 33, 0.05)"};
            color: ${isDark ? "#ffffff" : cfg.primaryColor};
            transform: translateY(-1px);
          }
          .cq-inline-options {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 12px;
          }
          .cq-fixed-option {
            border: 1px solid ${cfg.primaryColor};
            background: ${isDark ? "rgba(255, 126, 33, 0.14)" : "rgba(255, 126, 33, 0.10)"};
            color: ${isDark ? "#ffffff" : cfg.primaryColor};
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 700;
            transition: all 0.2s;
          }
          .cq-fixed-option:hover:not(:disabled) {
            background: ${cfg.primaryColor};
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
            
            /* Rigid selectable parameters */
            pointer-events: auto !important;
            cursor: text !important;
            user-select: text !important;
            -webkit-user-select: text !important;
          }

          #cq-input:focus {
            border-color: ${cfg.primaryColor} !important;
          }

          #cq-send {
            background: ${cfg.primaryColor};
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
          #cq-mic {
            background: ${isDark ? "rgba(255, 255, 255, 0.05)" : "#f3f4f6"};
            color: ${text};
            border: 1px solid ${borderColor};
            height: 40px;
            width: 40px;
            min-width: 40px;
            border-radius: 10px;
            font-size: 16px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
          }
          #cq-mic:hover {
            border-color: ${cfg.primaryColor};
            background: ${isDark ? "rgba(255, 255, 255, 0.1)" : "#e5e7eb"};
          }
          #cq-mic.cq-recording {
            background: #ef4444 !important;
            color: #ffffff !important;
            border-color: #ef4444 !important;
            animation: cqPulse 1.2s infinite ease-in-out;
          }
          @keyframes cqPulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
          }

          #cq-footer {
            font-size: 11px;
            text-align: center;
            padding: 8px;
            color: ${isDark ? "rgba(255, 255, 255, 0.3)" : "rgba(0, 0, 0, 0.3)"};
            border-top: 1px solid ${borderColor};
            background: ${isDark ? "rgba(5, 5, 7, 0.5)" : "rgba(0, 0, 0, 0.01)"};
          }

          @media (max-width: 480px) {
            #cq-box {
              width: calc(100vw - 24px);
              height: calc(100vh - 110px);
              ${right ? "right:12px" : "left:12px"};
              bottom: 82px;
            }
            #cq-btn {
              ${right ? "right:12px" : "left:12px"};
              bottom: 14px;
            }
          }
        </style>
      `);

      document.body.insertAdjacentHTML("beforeend", `
        <button id="cq-btn">${cfg.launcherText ? `<span>${cfg.launcherIcon}</span> <span>${cfg.launcherText}</span>` : cfg.launcherIcon}</button>
        <div id="cq-box">
          <div id="cq-head">
            <div id="cq-logo">${cfg.logoUrl ? `<img src="${cfg.logoUrl}" alt="logo">` : cfg.botAvatar}</div>
            <div id="cq-title-container">
              <div id="cq-title">${cfg.title}</div>
              <div id="cq-subtitle">${cfg.subtitle}</div>
            </div>
            ${cfg.showNewChat ? `<button id="cq-new">New</button>` : ""}
          </div>
          <div id="cq-msgs">
            <div class="cq-msg-row cq-bot-row">
              <div class="cq-msg-avatar">${cfg.botAvatar || "🤖"}</div>
              <div class="cq-msg cq-bot">${formatMessageText(cfg.welcomeMessage)}</div>
            </div>
          </div>
          <div id="cq-suggestions"></div>
          <div id="cq-form">
            <input id="cq-input" placeholder="${cfg.placeholder}" />
            <button id="cq-mic" type="button" title="Record voice message">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
              </svg>
            </button>
            <button id="cq-send" title="Send message">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
          </div>
          ${cfg.footerText ? `<div id="cq-footer">${cfg.footerText}</div>` : ""}
        </div>
      `);

      const $ = (id) => document.getElementById(id);
      const box = $("cq-box");
      const msgs = $("cq-msgs");
      const input = $("cq-input");
      const suggestions = $("cq-suggestions");
      const mic = $("cq-mic");
      const sendBtn = $("cq-send");

      let mediaRecorder = null;
      let isRecording = false;
      let fixedOptions = [];
      const defaultPlaceholder = cfg.placeholder;

      function audioExtensionFromMime(mimeType = "") {
        const type = String(mimeType || "").toLowerCase();
        if (type.includes("ogg")) return "ogg";
        if (type.includes("mp4") || type.includes("m4a")) return "mp4";
        if (type.includes("wav")) return "wav";
        if (type.includes("mpeg") || type.includes("mp3")) return "mp3";
        return "webm";
      }

      function updateButtonVisibility() {
        const hasText = input.value.trim().length > 0;
        if (isRecording) {
          mic.style.display = "flex";
          sendBtn.style.display = "none";
        } else {
          if (hasText) {
            mic.style.display = "none";
            sendBtn.style.display = "block";
          } else {
            mic.style.display = "flex";
            sendBtn.style.display = "none";
          }
        }
      }

      // Initialize visibility
      updateButtonVisibility();

      input.oninput = updateButtonVisibility;

      async function startRecording() {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          
          let options = {};
          if (MediaRecorder.isTypeSupported("audio/webm")) {
            options = { mimeType: "audio/webm" };
          } else if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
            options = { mimeType: "audio/webm;codecs=opus" };
          } else if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) {
            options = { mimeType: "audio/ogg;codecs=opus" };
          } else if (MediaRecorder.isTypeSupported("audio/mp4")) {
            options = { mimeType: "audio/mp4" };
          }

          const recorder = new MediaRecorder(stream, options);
          const chunks = [];

          recorder.ondataavailable = (e) => {
            if (e.data.size > 0) {
              chunks.push(e.data);
            }
          };

          recorder.onstop = async () => {
            const audioBlob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
            await sendVoiceMessage(audioBlob);
            stream.getTracks().forEach((track) => track.stop());
          };

          mediaRecorder = recorder;
          recorder.start(250);
          isRecording = true;
          mic.innerHTML = `
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
          `;
          mic.classList.add("cq-recording");
          updateButtonVisibility();
        } catch (err) {
          console.error("Error accessing microphone:", err);
          alert("Could not access microphone.");
        }
      }

      function stopRecording() {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
          try {
            mediaRecorder.requestData();
          } catch (err) {
            console.warn("Could not request final audio data:", err);
          }
          mediaRecorder.stop();
          isRecording = false;
          mic.innerHTML = `
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
            </svg>
          `;
          mic.classList.remove("cq-recording");
          updateButtonVisibility();
        }
      }

      mic.onclick = () => {
        if (isRecording) {
          stopRecording();
        } else {
          startRecording();
        }
      };

      async function sendVoiceMessage(audioBlob) {
        suggestions.innerHTML = "";
        const userRow = add("🎙️ Sending voice message...", "user");
        const typing = add("", "typing");

        try {
          const formData = new FormData();
          const extension = audioExtensionFromMime(audioBlob.type);
          formData.append("file", audioBlob, `recording.${extension}`);
          formData.append("thread_id", threadId);

          const voiceApiUrl = cfg.apiUrl.replace("/api/chat", "/api/voice/process");
          const res = await fetch(voiceApiUrl, {
            method: "POST",
            body: formData
          });

          const data = await res.json();
          typing.remove();

          if (data.success) {
            const userBubble = userRow.querySelector(".cq-msg");
            if (userBubble) {
              userBubble.textContent = `🎙️ ${data.user_text}`;
            }

            const botText = data.bot_text;
            const nextFixedOptions = Array.isArray(data.fixed_options) ? data.fixed_options : [];
            let botRow;
            botRow = add(botText, "bot", () => {
              if (nextFixedOptions.length > 0) {
                renderFixedOptions(nextFixedOptions, botRow);
              } else if (cfg.enableDynamicSuggestions) {
                loadDynamicSuggestions(botText, data.user_text);
              }
            });

            if (data.audio_url) {
              const host = cfg.apiUrl.split("/api/")[0];
              const audio = new Audio(host + data.audio_url);
              audio.play().catch((e) => console.error("Error playing audio:", e));
            }
          } else {
            const userBubble = userRow.querySelector(".cq-msg");
            if (userBubble) {
              userBubble.textContent = "🎙️ [Voice transmission failed]";
            }
          }
        } catch (err) {
          console.error("Voice processing error:", err);
          typing.remove();
          const userBubble = userRow.querySelector(".cq-msg");
          if (userBubble) {
            userBubble.textContent = "🎙️ [Voice transmission failed]";
          }
        }
      }

      function add(text, type, onComplete) {
        const row = document.createElement("div");
        row.className = `cq-msg-row cq-${type === "typing" ? "bot" : type}-row`;
        
        if (type === "bot" || type === "typing") {
          const avatar = document.createElement("div");
          avatar.className = "cq-msg-avatar";
          avatar.textContent = cfg.botAvatar || "🤖";
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
        updateButtonVisibility();
      }

      function renderFixedOptions(items = [], row = null) {
        fixedOptions = Array.isArray(items) ? items.filter(Boolean) : [];
        suggestions.innerHTML = "";
        input.disabled = false;
        input.placeholder = defaultPlaceholder;
        updateButtonVisibility();

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
        updateButtonVisibility();
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

      // STOP PROPAGATION Hooks: Completely protects form environment from exterior script listeners
      box.onclick = (e) => e.stopPropagation();
      $("cq-form").onclick = (e) => e.stopPropagation();
      input.onclick = (e) => e.stopPropagation();

      $("cq-btn").onclick = (e) => {
        e.stopPropagation();
        box.classList.toggle("cq-open");
        
        if (box.classList.contains("cq-open")) {
          setTimeout(() => {
            input.removeAttribute('disabled');
            input.focus();
          }, 100);
        }
      };

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
              <div class="cq-msg-avatar">${cfg.botAvatar || "🤖"}</div>
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
