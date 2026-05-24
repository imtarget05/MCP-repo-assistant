// MCP Repo Assistant Client App

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const repoPathInput = document.getElementById("repo-path-input");
    const collectionInput = document.getElementById("collection-input");
    const ingestBtn = document.getElementById("ingest-btn");
    const repoStatusVal = document.getElementById("repo-status-val");
    const repoDocsCount = document.getElementById("repo-docs-count");
    const repoActivePath = document.getElementById("repo-active-path");
    const chatMessagesContainer = document.getElementById("chat-messages-container");
    const chatInputTextarea = document.getElementById("chat-input-textarea");
    const sendChatBtn = document.getElementById("send-chat-btn");
    const clearChatBtn = document.getElementById("clear-chat-btn");
    const themeToggleBtn = document.getElementById("theme-toggle-btn");
    const reindexToggle = document.getElementById("reindex-toggle");
    const liveTracesLog = document.getElementById("live-traces-log");
    const globalLoaderOverlay = document.getElementById("global-loader-overlay");

    // LangGraph Node Elements
    const nodes = {
        start: document.getElementById("node-start"),
        agent: document.getElementById("node-agent"),
        tools: document.getElementById("node-tools"),
        verifier: document.getElementById("node-verifier"),
        end: document.getElementById("node-end")
    };

    const arrows = {
        startAgent: document.getElementById("arrow-start-agent"),
        agentTools: document.getElementById("arrow-agent-tools"),
        toolsAgent: document.getElementById("arrow-tools-agent"),
        agentVerifier: document.getElementById("arrow-agent-verifier"),
        verifierAgent: document.getElementById("arrow-verifier-agent"),
        verifierEnd: document.getElementById("arrow-verifier-end")
    };

    // App State
    let isIngesting = false;
    let isChatting = false;

    // Set Default Repo Path on load
    fetch("/health")
        .then(res => res.json())
        .then(data => {
            logEvent("Đã kết nối thành công với FastAPI Backend server.", "success");
        })
        .catch(err => {
            logEvent("Không thể kết nối với FastAPI Backend server. Hãy khởi chạy server.", "node-verifier");
            document.getElementById("connection-status-dot").className = "status-dot offline";
            document.getElementById("connection-status-text").textContent = "FastAPI Server Offline";
        });

    // Theme Toggle
    themeToggleBtn.addEventListener("click", () => {
        const currentTheme = document.body.getAttribute("data-theme");
        const nextTheme = currentTheme === "light" ? "dark" : "light";
        document.body.setAttribute("data-theme", nextTheme);
        themeToggleBtn.innerHTML = nextTheme === "light" ? '<i class="fa-solid fa-sun"></i>' : '<i class="fa-solid fa-moon"></i>';
        logEvent(`Đã chuyển giao diện sang chế độ ${nextTheme === "light" ? "Sáng" : "Tối"}.`, "system");
    });

    // Auto-growing textarea
    chatInputTextarea.addEventListener("input", function() {
        this.style.height = "auto";
        this.style.height = (this.scrollHeight - 10) + "px";
    });

    // Ingest Button Handler
    ingestBtn.addEventListener("click", async () => {
        const repoPath = repoPathInput.value.trim();
        const collection = collectionInput.value.trim();

        if (isIngesting) return;
        
        isIngesting = true;
        globalLoaderOverlay.classList.add("show");
        logEvent("Bắt đầu quá trình nạp repository...", "system");

        try {
            const response = await fetch("/ingest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ repo_path: repoPath || null, collection_name: collection })
            });

            const data = await response.json();

            if (response.ok) {
                repoStatusVal.textContent = "Đã Index";
                repoStatusVal.className = "status-pill status-active";
                repoDocsCount.textContent = data.documents_indexed;
                repoActivePath.textContent = data.repo_path;
                repoActivePath.title = data.repo_path;

                logEvent(`Index thành công ${data.documents_indexed} chunks từ repository.`, "success");
                alertSuccessMessage(data.repo_path, data.documents_indexed);
            } else {
                throw new Error(data.detail || "Không thể nạp dữ liệu.");
            }
        } catch (error) {
            logEvent(`Lỗi nạp repository: ${error.message}`, "node-verifier");
            repoStatusVal.textContent = "Lỗi Nạp";
            repoStatusVal.className = "status-pill status-gray";
        } finally {
            isIngesting = false;
            globalLoaderOverlay.classList.remove("show");
        }
    });

    // Clear Chat
    clearChatBtn.addEventListener("click", () => {
        chatMessagesContainer.innerHTML = `
            <div class="message system-message">
                <div class="avatar">
                    <i class="fa-solid fa-robot"></i>
                </div>
                <div class="message-content">
                    <p>Đã xóa lịch sử chat. Tôi đã sẵn sàng cho các câu hỏi mới từ bạn!</p>
                </div>
            </div>
        `;
        logEvent("Đã xóa lịch sử hội thoại.", "system");
        resetGraphHighlight();
    });

    // Quick Prompt Chips
    document.querySelectorAll(".prompt-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            chatInputTextarea.value = chip.getAttribute("data-prompt");
            chatInputTextarea.style.height = "auto";
            chatInputTextarea.style.height = (chatInputTextarea.scrollHeight - 10) + "px";
            chatInputTextarea.focus();
        });
    });

    // Send Chat Message on click or Enter
    sendChatBtn.addEventListener("click", sendChatMessage);
    chatInputTextarea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });

    // Main Chat Function
    async function sendChatMessage() {
        const question = chatInputTextarea.value.trim();
        const repoPath = repoPathInput.value.trim();
        const collection = collectionInput.value.trim();
        const reindex = reindexToggle.checked;

        if (!question || isChatting) return;

        isChatting = true;
        chatInputTextarea.value = "";
        chatInputTextarea.style.height = "auto";

        // Append User Message to UI
        appendMessage("user", question);
        logEvent(`Câu hỏi mới: "${question.substring(0, 45)}..."`, "system");

        // Create placeholders for AI response
        const aiMessageEl = appendMessage("system", "Đang xử lý RAG và kích hoạt Agent...");
        const aiContentEl = aiMessageEl.querySelector(".message-content");

        // Highlight Start node in Graph
        resetGraphHighlight();
        highlightNode("start", "active-start");
        highlightArrow("startAgent");

        try {
            const response = await fetch("/chat/stream", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question: question,
                    repo_path: repoPath || null,
                    collection_name: collection,
                    reindex: reindex,
                    top_k: 5
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || "Không thể xử lý yêu cầu.");
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let accumulatedContent = "";
            let isFirstContent = true;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunkText = decoder.decode(value);
                const lines = chunkText.split("\n");

                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        const rawData = line.substring(6).trim();
                        if (rawData === "[DONE]") {
                            logEvent("Agent hoàn thành luồng thực thi.", "success");
                            highlightNode("end", "active-start");
                            highlightArrow("verifierEnd");
                            break;
                        }

                        try {
                            const eventData = JSON.parse(rawData);
                            handleGraphSSEEvent(eventData);

                            // Process actual message content
                            if (eventData.data && eventData.data.content) {
                                if (isFirstContent) {
                                    aiContentEl.innerHTML = "";
                                    isFirstContent = false;
                                }
                                accumulatedContent += eventData.data.content;
                                aiContentEl.innerHTML = parseMarkdown(accumulatedContent);
                                chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
                            }
                        } catch (e) {
                            // Non-json chunk or partial parse
                        }
                    }
                }
            }

        } catch (error) {
            logEvent(`Lỗi thực thi: ${error.message}`, "node-verifier");
            aiContentEl.innerHTML = `<span style="color: var(--accent-pink);">❌ Rất tiếc, đã xảy ra lỗi trong quá trình thực thi: ${error.message}</span>`;
            highlightNode("verifier", "active-verifier");
        } finally {
            isChatting = false;
        }
    }

    // Handle Graph Highlight on incoming SSE events
    function handleGraphSSEEvent(event) {
        const node = event.node;
        const data = event.data;

        if (node === "agent") {
            logEvent("Trạng thái: LangGraph Agent Node đang xử lý...", "node-agent");
            resetGraphHighlight();
            highlightNode("agent", "active-agent");
            
            if (data.tool_calls && data.tool_calls.length > 0) {
                const toolNames = data.tool_calls.map(tc => tc.name).join(", ");
                logEvent(`🛠️ Agent quyết định gọi các công cụ MCP: ${toolNames}`, "node-tools");
                highlightArrow("agentTools");
            } else if (data.content) {
                highlightArrow("agentVerifier");
            }
        } else if (node === "tools") {
            logEvent("Trạng thái: Đang thực thi MCP tool trên môi trường...", "node-tools");
            resetGraphHighlight();
            highlightNode("tools", "active-tools");
            highlightArrow("toolsAgent");
        } else if (node === "verifier") {
            const isValid = data.is_valid !== undefined ? data.is_valid : true;
            if (isValid) {
                logEvent("Trạng thái: Verifier kiểm tra chất lượng kết quả đạt chuẩn.", "success");
                resetGraphHighlight();
                highlightNode("verifier", "active-verifier");
                highlightArrow("verifierEnd");
            } else {
                logEvent("⚠️ Cảnh báo: Verifier phát hiện câu trả lời chưa đạt chất lượng! Kích hoạt luồng Tự Sửa Lỗi (Self-Correction)...", "node-verifier");
                resetGraphHighlight();
                highlightNode("verifier", "active-verifier");
                // Flash verifier red or pulsing pink
                nodes.verifier.querySelector(".node-circle").style.borderColor = "var(--accent-pink)";
                highlightArrow("verifierAgent", "active-feedback-flow");
            }
        }
    }

    // UI Helper Functions
    function appendMessage(sender, text) {
        const messageDiv = document.createElement("div");
        messageDiv.className = `message ${sender === "user" ? "user-message" : "system-message"}`;
        
        const avatarDiv = document.createElement("div");
        avatarDiv.className = "avatar";
        avatarDiv.innerHTML = sender === "user" ? '<i class="fa-solid fa-user-astronaut"></i>' : '<i class="fa-solid fa-robot"></i>';

        const contentDiv = document.createElement("div");
        contentDiv.className = "message-content";
        contentDiv.innerHTML = sender === "user" ? `<p>${escapeHtml(text)}</p>` : text;

        messageDiv.appendChild(avatarDiv);
        messageDiv.appendChild(contentDiv);
        chatMessagesContainer.appendChild(messageDiv);
        chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;

        return messageDiv;
    }

    function logEvent(message, type = "system") {
        const time = new Date().toLocaleTimeString();
        const line = document.createElement("div");
        line.className = `log-line log-${type}`;
        line.innerHTML = `<span>[${time}]</span> ${escapeHtml(message)}`;
        
        liveTracesLog.appendChild(line);
        liveTracesLog.scrollTop = liveTracesLog.scrollHeight;
    }

    function alertSuccessMessage(path, count) {
        const welcomeMessage = `
            <div class="message system-message">
                <div class="avatar">
                    <i class="fa-solid fa-square-check"></i>
                </div>
                <div class="message-content">
                    <p style="color: var(--accent-green); font-weight: bold; margin-bottom: 5px;">🎉 Nạp dữ liệu hoàn tất!</p>
                    <p>Repository <code>${escapeHtml(path)}</code> đã được index thành công với <strong>${count}</strong> tài liệu vào cơ sở dữ liệu vector.</p>
                    <p>Bạn có thể chọn các gợi ý bên dưới hoặc hỏi trực tiếp về cấu trúc code ngay bây giờ!</p>
                </div>
            </div>
        `;
        chatMessagesContainer.innerHTML += welcomeMessage;
        chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
    }

    // Graph Visualizer highlights
    function resetGraphHighlight() {
        Object.values(nodes).forEach(node => {
            const circle = node.querySelector(".node-circle");
            circle.className = circle.className.replace(/active-\w+/g, "").trim();
            circle.style.borderColor = "";
        });

        Object.values(arrows).forEach(arrow => {
            arrow.className = arrow.className.replace(/active-flow/g, "").replace(/active-feedback-flow/g, "").trim();
        });
    }

    function highlightNode(nodeKey, className) {
        if (nodes[nodeKey]) {
            nodes[nodeKey].querySelector(".node-circle").classList.add("active", className);
        }
    }

    function highlightArrow(arrowKey, className = "active-flow") {
        if (arrows[arrowKey]) {
            arrows[arrowKey].classList.add(className);
        }
    }

    // Utility text parsers
    function escapeHtml(text) {
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Extremely lightweight Markdown to HTML Parser
    function parseMarkdown(markdown) {
        let html = markdown;
        
        // Escape HTML tags to prevent XSS except specific allowed markdown constructs
        html = escapeHtml(html);

        // Code blocks: ```language ... ```
        html = html.replace(/&lt;pre&gt;&lt;code&gt;/g, "<pre><code>").replace(/&lt;\/code&gt;&lt;\/pre&gt;/g, "</code></pre>");
        html = html.replace(/```(?:[a-zA-Z0-9]+)?\n([\s\S]*?)```/g, (match, code) => {
            return `<pre><code>${code}</code></pre>`;
        });

        // Inline code blocks: `code`
        html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

        // Bold headers: **text**
        html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

        // Italic: *text*
        html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");

        // Bullets: - text
        html = html.replace(/^\s*-\s+(.+)$/gm, "<li>$1</li>");
        html = html.replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>");

        // Convert double newlines to paragraphs
        html = html.replace(/\n\n/g, "</p><p>");

        // Single newlines to line breaks
        html = html.replace(/\n/g, "<br>");

        return html;
    }
});
