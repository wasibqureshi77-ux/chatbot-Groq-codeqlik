import { apiFetch } from "../api";
import { useEffect, useState } from "react";
import React from "react";

const API_BASE = "/api/admin";
// API_ROOT is derived from API_BASE — change API_BASE and this updates automatically
const API_ROOT = API_BASE.replace("/api/admin", "");
const PUBLIC_ROOT = window.location.origin;

function Admin() {

    const [activeTab, setActiveTab] = useState("dashboard");
    const [loading, setLoading] = useState(false);
    
    // Search / Filter states
    const [searchQuery, setSearchQuery] = useState("");
    const [statusFilter, setStatusFilter] = useState("");
    const [extraFilter, setExtraFilter] = useState("");

    // Data lists
    const [dashboardData, setDashboardData] = useState({
        counters: { chats: 0, threads: 0, leads: 0, support: 0, hiring: 0, meetings: 0, knowledge: 0, active_sources: 0, disabled_sources: 0 },
        recent_activity: [],
        intent_breakdown: {}
    });
    const [chatsList, setChatsList] = useState([]); // Grouped threads
    const [selectedThreadId, setSelectedThreadId] = useState("");
    const [selectedThreadMessages, setSelectedThreadMessages] = useState([]);
    const [selectedThreadProfile, setSelectedThreadProfile] = useState({});
    
    const [leads, setLeads] = useState([]);
    const [tickets, setTickets] = useState([]);
    const [candidates, setCandidates] = useState([]);
    const [meetings, setMeetings] = useState([]);
    const [knowledgeSources, setKnowledgeSources] = useState([]);
    const [syncStatus, setSyncStatus] = useState({
        total_sources: 0,
        active_sources: 0,
        disabled_sources: 0,
        total_chunks: 0,
        last_updated: "N/A"
    });
    const [settings, setSettings] = useState({
        companyName: "",
        companyDescription: "",
        fallbackMessage: "",
        generalEmail: "",
        generalPhone: "",
        supportEmail: "",
        supportPhone: "",
        title: "",
        subtitle: "",
        welcomeMessage: "",
        placeholder: "",
        primaryColor: "",
        theme: "light",
        position: "bottom-right",
        width: "",
        height: "",
        logoUrl: "",
        botAvatar: "",
        launcherIcon: "",
        launcherText: "",
        showNewChat: true,
        footerText: "",
        suggestions: [],
        storage: "local",
        company_name: "",
        company_description: "",
        contact_email: "",
        contact_phone: "",
        chatbot_greeting: "",
        fallback_message: "",
        support_email: "",
        support_phone: ""
    });
    const [settingsLoading, setSettingsLoading] = useState(true);

    // LLM Usage Analytics states
    const [llmSummary, setLlmSummary] = useState({
        total_requests: 0,
        total_input_tokens: 0,
        total_output_tokens: 0,
        total_tokens: 0,
        total_cost: 0,
        avg_latency: 0,
        avg_tokens_per_request: 0,
        estimated_monthly_cost: 0
    });
    const [modelUsage, setModelUsage] = useState([]);
    const [dailyUsage, setDailyUsage] = useState([]);
    const [recentLlmCalls, setRecentLlmCalls] = useState([]);
    const [llmStartDate, setLlmStartDate] = useState("");
    const [llmEndDate, setLlmEndDate] = useState("");
    const [llmModelFilter, setLlmModelFilter] = useState("");
    
    // Cost Calculator Simulated Rate States
    const [modelRates, setModelRates] = useState({});

    const getDefaultRates = (modelName) => {
        const name = (modelName || "").toLowerCase();
        if (name.includes("gpt-oss-120b")) {
            return { input: 0.15, output: 0.60 };
        } else if (name.includes("gpt-oss-20b")) {
            return { input: 0.075, output: 0.30 };
        } else if (name.includes("llama3-70b") || name.includes("llama-3.1-70b")) {
            return { input: 0.59, output: 0.79 };
        } else if (name.includes("llama3-8b") || name.includes("llama-3.1-8b")) {
            return { input: 0.05, output: 0.08 };
        } else if (name.includes("compound-mini")) {
            return { input: 0.015, output: 0.03 };
        } else if (name.includes("qwen3.6-27b")) {
            return { input: 0.10, output: 0.15 };
        } else if (name.includes("qwen3-32b") || name.includes("qwen")) {
            return { input: 0.12, output: 0.18 };
        } else if (name.includes("prompt-guard")) {
            return { input: 0.005, output: 0.005 };
        } else if (name.includes("mixtral")) {
            return { input: 0.24, output: 0.24 };
        } else if (name.includes("gemma")) {
            return { input: 0.20, output: 0.20 };
        }
        return { input: 0.15, output: 0.60 }; // default fallback
    };

    // Knowledge Creator states
    const [sourceType, setSourceType] = useState("manual"); // manual, document, database, website
    const [manualForm, setManualForm] = useState({ title: "", category: "Company Information", content: "", intent_scope: "Auto", topic: "Auto", service: "Auto", tags: "" });
    const [dbForm, setDbForm] = useState({ connection_name: "", db_type: "mongodb", connection_string: "", db_name: "", target_collection: "", category: "Company Information", intent_scope: "Auto", topic: "Auto", service: "Auto", tags: "" });
    const [webForm, setWebForm] = useState({ url: "", category: "Company Information", intent_scope: "Auto", topic: "Auto", service: "Auto", tags: "" });
    const [docFile, setDocFile] = useState(null);
    const [docCategory, setDocCategory] = useState("Company Information");
    const [docMetadata, setDocMetadata] = useState({ intent_scope: "Auto", topic: "Auto", service: "Auto", tags: "" });
    
    // Knowledge Editor Modal States
    const [isEditModalOpen, setIsEditModalOpen] = useState(false);
    const [editingSourceId, setEditingSourceId] = useState(null);
    const [editForm, setEditForm] = useState({
        title: "",
        category: "Company Information",
        content: "",
        full_content: "",
        intent_scope: "Auto",
        topic: "Auto",
        service: "Auto",
        tags: "",
        url: "",
        connection_name: "",
        db_type: "mongodb",
        connection_string: "",
        db_name: "",
        target_collection: "",
        type: "manual"
    });

    // Core Fetch Tab function
    async function fetchData() {
        try {
            if (activeTab === "dashboard") {
                const res = await apiFetch(`${API_BASE}/dashboard`);
                if (res.ok) {
                    setDashboardData(await res.json());
                }
            } else if (activeTab === "chats") {
                const queryParams = new URLSearchParams();
                if (searchQuery) queryParams.append("q", searchQuery);
                if (extraFilter) queryParams.append("intent", extraFilter);
                
                const res = await apiFetch(`${API_BASE}/chats?${queryParams.toString()}`);
                if (res.ok) {
                    const data = await res.json();
                    setChatsList(data);
                    
                    // Maintain selected thread
                    if (selectedThreadId) {
                        fetchThreadMessages(selectedThreadId);
                    } else if (data.length > 0) {
                        setSelectedThreadId(data[0].thread_id);
                        fetchThreadMessages(data[0].thread_id);
                    }
                }
            } else if (activeTab === "leads") {
                const queryParams = new URLSearchParams();
                if (searchQuery) queryParams.append("q", searchQuery);
                if (statusFilter) queryParams.append("status", statusFilter);
                
                const res = await apiFetch(`${API_BASE}/leads?${queryParams.toString()}`);
                if (res.ok) {
                    setLeads(await res.json());
                }
            } else if (activeTab === "support") {
                const queryParams = new URLSearchParams();
                if (searchQuery) queryParams.append("q", searchQuery);
                if (statusFilter) queryParams.append("status", statusFilter);
                if (extraFilter) queryParams.append("priority", extraFilter);
                
                const res = await apiFetch(`${API_BASE}/support?${queryParams.toString()}`);
                if (res.ok) {
                    setTickets(await res.json());
                }
            } else if (activeTab === "hiring") {
                const queryParams = new URLSearchParams();
                if (searchQuery) queryParams.append("q", searchQuery);
                if (statusFilter) queryParams.append("status", statusFilter);
                
                const res = await apiFetch(`${API_BASE}/hiring?${queryParams.toString()}`);
                if (res.ok) {
                    setCandidates(await res.json());
                }
            } else if (activeTab === "meetings") {
                const res = await apiFetch(`${API_BASE}/meetings`);
                if (res.ok) {
                    setMeetings(await res.json());
                }
            } else if (activeTab === "knowledge") {
                const queryParams = new URLSearchParams();
                if (searchQuery) queryParams.append("q", searchQuery);
                if (statusFilter) queryParams.append("type", statusFilter);
                
                const res = await apiFetch(`${API_BASE}/knowledge?${queryParams.toString()}`);
                if (res.ok) {
                    setKnowledgeSources(await res.json());
                }
                
                // Fetch sync status details
                const syncRes = await apiFetch(`${API_BASE}/knowledge/sync-status`);
                if (syncRes.ok) {
                    setSyncStatus(await syncRes.json());
                }
            } else if (activeTab === "settings") {
                setSettingsLoading(true);
                const res = await apiFetch(`${API_ROOT}/api/settings`);
                if (res.ok) {
                    setSettings(await res.json());
                }
                setSettingsLoading(false);
            } else if (activeTab === "llm-usage") {
                const queryParams = new URLSearchParams();
                if (llmStartDate) queryParams.append("start_date", llmStartDate);
                if (llmEndDate) queryParams.append("end_date", llmEndDate);
                if (llmModelFilter) queryParams.append("model", llmModelFilter);
                
                const [summaryRes, modelRes, dailyRes, recentRes] = await Promise.all([
                    apiFetch(`${API_BASE}/analytics/llm-usage/summary?${queryParams.toString()}`),
                    apiFetch(`${API_BASE}/analytics/llm-usage/by-model?${queryParams.toString()}`),
                    apiFetch(`${API_BASE}/analytics/llm-usage/daily?${queryParams.toString()}`),
                    apiFetch(`${API_BASE}/analytics/llm-usage/recent?${queryParams.toString()}`)
                ]);
                
                if (summaryRes.ok) setLlmSummary(await summaryRes.json());
                if (modelRes.ok) setModelUsage(await modelRes.json());
                if (dailyRes.ok) setDailyUsage(await dailyRes.json());
                if (recentRes.ok) setRecentLlmCalls(await recentRes.json());
            }
        } catch (error) {
            console.error("Connection error:", error);
        }
    }

    async function fetchThreadMessages(threadId) {
        try {
            const res = await apiFetch(`${API_BASE}/chats/${threadId}`);
            if (res.ok) {
                const data = await res.json();
                if (data && typeof data === "object" && !Array.isArray(data)) {
                    setSelectedThreadMessages(data.messages || []);
                    setSelectedThreadProfile(data.profile || {});
                } else if (Array.isArray(data)) {
                    setSelectedThreadMessages(data);
                    setSelectedThreadProfile(data[data.length - 1]?.profile_snapshot || {});
                }
            }
        } catch (err) {
            console.error("Failed to load thread details:", err);
        }
    }

    // 1. Initial Fetch on Tab switch
    useEffect(() => {
        setSearchQuery("");
        setStatusFilter("");
        setExtraFilter("");
        if (activeTab !== "chats") {
            setSelectedThreadId("");
            setSelectedThreadMessages([]);
            setSelectedThreadProfile({});
        }
        
        setLoading(true);
        fetchData().finally(() => setLoading(false));
    }, [activeTab]);

    // 2. React to Search query changes (with debouncing)
    useEffect(() => {
        const delay = setTimeout(() => {
            fetchData();
        }, 300);
        return () => clearTimeout(delay);
    }, [searchQuery, statusFilter, extraFilter]);

    useEffect(() => {
        if (activeTab === "llm-usage") {
            fetchData();
        }
    }, [llmStartDate, llmEndDate, llmModelFilter]);

    // 3. REST API Polling (No WebSockets, no SSE)
    useEffect(() => {
        if (activeTab === "settings" || activeTab === "llm-usage") return;

        const delay = activeTab === "knowledge" ? 30000 : 5000;
        const pollInterval = setInterval(() => {
            fetchData();
        }, delay);

        return () => clearInterval(pollInterval);
    }, [activeTab, searchQuery, statusFilter, extraFilter, selectedThreadId]);

    // Handle Thread Selection click
    function handleSelectThread(threadId) {
        setSelectedThreadId(threadId);
        fetchThreadMessages(threadId);
    }

    // Update statuses
    async function handleLeadStatus(leadId, newStatus) {
        try {
            const res = await apiFetch(`${API_BASE}/leads/${leadId}/status`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: newStatus })
            });
            if (res.ok) {
                setLeads(leads.map(l => l._id === leadId ? { ...l, status: newStatus } : l));
            }
        } catch (err) { console.error(err); }
    }

    async function handleUpdateMeetingStatus(meetingId, newStatus) {
        try {
            const res = await apiFetch(`${API_BASE}/meetings/${meetingId}/status`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: newStatus })
            });
            if (res.ok) {
                setMeetings(meetings.map(m => (m.id === meetingId || m._id === meetingId) ? { ...m, profile: { ...m.profile, status: newStatus } } : m));
            }
        } catch (err) { console.error("Failed to update meeting status:", err); }
    }

    async function handleSupportUpdate(ticketId, field, value) {
        const payload = {};
        payload[field] = value;
        try {
            const res = await apiFetch(`${API_BASE}/support/${ticketId}/status`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                setTickets(tickets.map(t => t._id === ticketId ? { ...t, [field]: value } : t));
            }
        } catch (err) { console.error(err); }
    }

    async function handleHiringStatus(candidateId, newStatus) {
        try {
            const res = await apiFetch(`${API_BASE}/hiring/${candidateId}/status`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: newStatus })
            });
            if (res.ok) {
                setCandidates(candidates.map(c => c._id === candidateId ? { ...c, status: newStatus } : c));
            }
        } catch (err) { console.error(err); }
    }

    // Save Brand configuration Settings
    async function saveSettings(e) {
        e.preventDefault();
        try {
            const res = await apiFetch(`${API_ROOT}/api/settings`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(settings)
            });
            if (res.ok) {
                alert("Configurations saved!");
            } else {
                const errData = await res.json();
                alert("Failed to save settings: " + (errData.detail || "Validation or auth error"));
            }
        } catch (err) {
            console.error(err);
            alert("Failed to save settings due to network error.");
        }
    }

    // Knowledge actions
    async function handleToggleSource(sourceId, currentState) {
        const url = currentState ? `${API_BASE}/knowledge/${sourceId}/disable` : `${API_BASE}/knowledge/${sourceId}/enable`;
        try {
            const res = await apiFetch(url, { method: "PUT" });
            if (res.ok) {
                setKnowledgeSources(knowledgeSources.map(s => s._id === sourceId ? { ...s, enabled: !currentState } : s));
                fetchData(); // Sync metrics
            }
        } catch (err) { console.error(err); }
    }

    async function handleReindexSource(sourceId) {
        try {
            const res = await apiFetch(`${API_BASE}/knowledge/${sourceId}/reindex`, { method: "POST" });
            if (res.ok) {
                alert("Source re-indexing successfully completed!");
                fetchData();
            }
        } catch (err) { console.error(err); }
    }

    async function handleDeleteSource(sourceId) {
        if (!confirm("Are you sure you want to delete this source? This will remove all chunks and indexing parameters. The chatbot will immediately lose access to this context.")) return;
        try {
            const res = await apiFetch(`${API_BASE}/knowledge/${sourceId}`, { method: "DELETE" });
            if (res.ok) {
                fetchData();
            }
        } catch (err) { console.error(err); }
    }

    // CREATE operations
    async function handleCreateManual(e) {
        e.preventDefault();
        try {
            const body = {
                title: manualForm.title,
                category: manualForm.category,
                content: manualForm.content,
                intent_scope: manualForm.intent_scope === "Auto" ? "" : manualForm.intent_scope,
                topic: manualForm.topic === "Auto" ? "" : manualForm.topic,
                service: manualForm.service === "Auto" ? "" : manualForm.service,
                tags: manualForm.tags || ""
            };
            const res = await apiFetch(`${API_BASE}/knowledge`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });
            if (res.ok) {
                setManualForm({ title: "", category: "Company Information", content: "", intent_scope: "Auto", topic: "Auto", service: "Auto", tags: "" });
                fetchData();
            }
        } catch (err) { console.error(err); }
    }

    async function handleUploadDoc(e) {
        e.preventDefault();
        if (!docFile) return alert("Select a document file first");
        const formData = new FormData();
        formData.append("file", docFile);
        formData.append("category", docCategory);
        if (docMetadata.intent_scope !== "Auto") {
            formData.append("intent_scope", docMetadata.intent_scope);
        }
        if (docMetadata.topic !== "Auto") {
            formData.append("topic", docMetadata.topic);
        }
        if (docMetadata.service !== "Auto") {
            formData.append("service", docMetadata.service);
        }
        if (docMetadata.tags) {
            formData.append("tags", docMetadata.tags);
        }
        try {
            const res = await apiFetch(`${API_BASE}/knowledge/upload`, {
                method: "POST",
                body: formData
            });
            if (res.ok) {
                setDocFile(null);
                setDocMetadata({ intent_scope: "Auto", topic: "Auto", service: "Auto", tags: "" });
                fetchData();
            }
        } catch (err) { console.error(err); }
    }

    async function handleConnectDb(e) {
        e.preventDefault();
        try {
            const body = {
                ...dbForm,
                intent_scope: dbForm.intent_scope === "Auto" ? "" : dbForm.intent_scope,
                topic: dbForm.topic === "Auto" ? "" : dbForm.topic,
                service: dbForm.service === "Auto" ? "" : dbForm.service,
                tags: dbForm.tags || ""
            };
            const res = await apiFetch(`${API_BASE}/sources/database`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });
            if (res.ok) {
                setDbForm({
                    connection_name: "",
                    db_type: "mongodb",
                    connection_string: "",
                    db_name: "",
                    target_collection: "",
                    category: "Company Information",
                    intent_scope: "Auto",
                    topic: "Auto",
                    service: "Auto",
                    tags: ""
                });
                fetchData();
            }
        } catch (err) { console.error(err); }
    }

    async function handleConnectWeb(e) {
        e.preventDefault();
        try {
            const body = {
                ...webForm,
                intent_scope: webForm.intent_scope === "Auto" ? "" : webForm.intent_scope,
                topic: webForm.topic === "Auto" ? "" : webForm.topic,
                service: webForm.service === "Auto" ? "" : webForm.service,
                tags: webForm.tags || ""
            };
            const res = await apiFetch(`${API_BASE}/sources/website`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });
            if (res.ok) {
                setWebForm({ url: "", category: "Company Information", intent_scope: "Auto", topic: "Auto", service: "Auto", tags: "" });
                fetchData();
            }
        } catch (err) { console.error(err); }
    }

    function openEditModal(source) {
        setEditingSourceId(source._id);
        setEditForm({
            title: source.title || "",
            category: source.category || "Company Information",
            content: source.content || "",
            full_content: source.full_content || source.content || "",
            intent_scope: source.intent_scope || "Auto",
            topic: source.topic || "Auto",
            service: source.service || "Auto",
            tags: (source.tags || []).join(", "),
            url: source.url || "",
            connection_name: source.connection_name || source.title || "",
            db_type: source.db_type || "mongodb",
            connection_string: source.connection_string || "",
            db_name: source.db_name || "",
            target_collection: source.target_collection || "",
            type: source.type || "manual"
        });
        setIsEditModalOpen(true);
    }

    async function handleSaveEdit(e) {
        e.preventDefault();
        try {
            const body = {
                ...editForm,
                tags: editForm.tags,
                intent_scope: editForm.intent_scope === "Auto" ? "" : editForm.intent_scope,
                topic: editForm.topic === "Auto" ? "" : editForm.topic,
                service: editForm.service === "Auto" ? "" : editForm.service
            };
            const res = await apiFetch(`${API_BASE}/knowledge/${editingSourceId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });
            if (res.ok) {
                setIsEditModalOpen(false);
                fetchData();
            }
        } catch (err) { console.error(err); }
    }

    function exportLeadsCSV() {
        if (leads.length === 0) return;
        let csvContent = "data:text/csv;charset=utf-8,";
        csvContent += "Name,Email/Phone,Company,Project Type,Budget,Timeline,Status,Updated\n";
        leads.forEach((l) => {
            const p = l.profile || {};
            const row = [
                `"${p.name || ''}"`,
                `"${p.email_or_phone || ''}"`,
                `"${p.company || ''}"`,
                `"${p.project_type || ''}"`,
                `"${p.budget || ''}"`,
                `"${p.timeline || ''}"`,
                `"${l.status || 'New'}"`,
                `"${l.updated_at || ''}"`
            ].join(",");
            csvContent += row + "\n";
        });
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `client_leads_export_${Date.now()}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    function renderMetadataFields(formState, setFormState) {
        return (
            <>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
                    <div className="formGroup">
                        <label>Intent Scope</label>
                        <select value={formState.intent_scope} onChange={(e) => setFormState({ ...formState, intent_scope: e.target.value })}>
                            <option value="Auto">Auto</option>
                            <option value="all">all</option>
                            <option value="client">client</option>
                            <option value="support">support</option>
                            <option value="hiring">hiring</option>
                            <option value="greet">greet</option>
                        </select>
                    </div>
                    <div className="formGroup">
                        <label>Topic</label>
                        <select value={formState.topic} onChange={(e) => setFormState({ ...formState, topic: e.target.value })}>
                            <option value="Auto">Auto</option>
                            <option value="general">general</option>
                            <option value="services">services</option>
                            <option value="technologies">technologies</option>
                            <option value="pricing">pricing</option>
                            <option value="contact">contact</option>
                            <option value="portfolio">portfolio</option>
                            <option value="faq">faq</option>
                            <option value="policies">policies</option>
                        </select>
                    </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
                    <div className="formGroup">
                        <label>Service</label>
                        <select value={formState.service} onChange={(e) => setFormState({ ...formState, service: e.target.value })}>
                            <option value="Auto">Auto</option>
                            <option value="general">general</option>
                            <option value="website">website</option>
                            <option value="mobile_app">mobile app</option>
                            <option value="ecommerce">ecommerce</option>
                            <option value="crm">crm</option>
                            <option value="ai_automation">ai automation</option>
                            <option value="software">software</option>
                        </select>
                    </div>
                    <div className="formGroup">
                        <label>Tags (comma-separated)</label>
                        <input 
                            type="text" 
                            value={formState.tags || ""} 
                            onChange={(e) => setFormState({ ...formState, tags: e.target.value })} 
                            placeholder="e.g. tag1, tag2" 
                        />
                    </div>
                </div>
            </>
        );
    }

    return (
        <div className="adminPage">
            <aside className="sidebar">
                <div className="sidebarBrand" style={{ padding: '20px 15px', borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', justifyContent: 'center', marginBottom: '6px' }}>
                        <img src="https://codeqlik.com/assets/img/fav-icon-codeqlik.jpeg" alt="CodeQlik Logo" style={{ width: '32px', height: '32px', borderRadius: '4px', boxShadow: '0 2px 8px rgba(255, 126, 33, 0.2)' }} />
                        <h2 style={{ margin: 0, fontSize: '20px', fontWeight: '700' }}>CodeQlik</h2>
                    </div>
                    <p style={{ margin: 0, textAlign: 'center', fontSize: '11px', color: '#94a3b8' }}>Chatbot Admin Panel</p>
                </div>
                <nav className="sidebarMenu">
                    <button className={`sidebarBtn ${activeTab === "dashboard" ? "active" : ""}`} onClick={() => setActiveTab("dashboard")}>
                        📊 Dashboard
                    </button>
                    <button className={`sidebarBtn ${activeTab === "chats" ? "active" : ""}`} onClick={() => setActiveTab("chats")}>
                        💬 Chats Log
                    </button>
                    <button className={`sidebarBtn ${activeTab === "leads" ? "active" : ""}`} onClick={() => setActiveTab("leads")}>
                        🤝 Client Leads
                    </button>
                    <button className={`sidebarBtn ${activeTab === "support" ? "active" : ""}`} onClick={() => setActiveTab("support")}>
                        🛠️ Support Tickets
                    </button>
                    <button className={`sidebarBtn ${activeTab === "hiring" ? "active" : ""}`} onClick={() => setActiveTab("hiring")}>
                        💼 Hiring Candidates
                    </button>
                    <button className={`sidebarBtn ${activeTab === "meetings" ? "active" : ""}`} onClick={() => setActiveTab("meetings")}>
                        📅 Booked Meetings
                    </button>
                    <button className={`sidebarBtn ${activeTab === "knowledge" ? "active" : ""}`} onClick={() => setActiveTab("knowledge")}>
                        📚 Knowledge Sources
                    </button>
                    <button className={`sidebarBtn ${activeTab === "llm-usage" ? "active" : ""}`} onClick={() => setActiveTab("llm-usage")}>
                        📊 AI Usage
                    </button>
                    <button className={`sidebarBtn ${activeTab === "settings" ? "active" : ""}`} onClick={() => setActiveTab("settings")}>
                        ⚙️ Settings
                    </button>
                </nav>
            
                <button 
                    onClick={() => { sessionStorage.removeItem("admin_token"); window.location.replace("/"); }} 
                    style={{marginTop: 'auto', background: 'transparent', border: '1px solid #ef4444', color: '#ef4444', padding: '10px', borderRadius: '6px', cursor: 'pointer', width: '100%', display: 'block', textAlign: 'center'}}
                >
                    Logout
                </button>
            </aside>


            <main className="adminContent">
                <div className="adminHeader">
                    <h1>{activeTab === "llm-usage" ? "AI Usage Analytics" : activeTab.toUpperCase()}</h1>
                    <div className="adminHeaderRight">
                        <button className="secondaryBtn" onClick={fetchData}>
                            🔄 Refresh
                        </button>
                        {activeTab === "leads" && (
                            <button className="primaryBtn" onClick={exportLeadsCSV}>
                                📥 Export CSV
                            </button>
                        )}
                    </div>
                </div>

                {loading && <p>Loading data summary...</p>}

                {/* ==========================================
                    DASHBOARD TAB
                    ========================================== */}
                {!loading && activeTab === "dashboard" && (
                    <div>
                        <div className="statsGrid">
                            <div className="statCard">
                                <span className="statCardTitle">Total Chats</span>
                                <span className="statCardValue">{dashboardData.counters.chats}</span>
                                <span className="statCardFooter">Total logged user inputs</span>
                            </div>
                            <div className="statCard">
                                <span className="statCardTitle">Active User Threads</span>
                                <span className="statCardValue">{dashboardData.counters.threads}</span>
                                <span className="statCardFooter">Unique conversation threads</span>
                            </div>
                            <div className="statCard">
                                <span className="statCardTitle">Client Leads</span>
                                <span className="statCardValue">{dashboardData.counters.leads}</span>
                                <span className="statCardFooter">Qualified project records</span>
                            </div>
                            <div className="statCard">
                                <span className="statCardTitle">Support Tickets</span>
                                <span className="statCardValue">{dashboardData.counters.support}</span>
                                <span className="statCardFooter">Logged customer tickets</span>
                            </div>
                            <div className="statCard">
                                <span className="statCardTitle">Hiring Candidates</span>
                                <span className="statCardValue">{dashboardData.counters.hiring}</span>
                                <span className="statCardFooter">Submitted job application candidacies</span>
                            </div>
                            <div className="statCard">
                                <span className="statCardTitle">Booked Meetings</span>
                                <span className="statCardValue">{dashboardData.counters.meetings || 0}</span>
                                <span className="statCardFooter">Confirmed discussion slots</span>
                            </div>
                            <div className="statCard">
                                <span className="statCardTitle">Total Knowledge Sources</span>
                                <span className="statCardValue">{dashboardData.counters.knowledge}</span>
                                <span className="statCardFooter">
                                    Active: <strong>{dashboardData.counters.active_sources}</strong> | Disabled: <strong>{dashboardData.counters.disabled_sources}</strong>
                                </span>
                            </div>
                        </div>

                        <div className="dashboardSections">
                            <div className="dashboardPanel">
                                <h3>Enterprise Activity Stream</h3>
                                <div className="timeline">
                                    {dashboardData.recent_activity.length === 0 ? (
                                        <p>No recent activity logged.</p>
                                    ) : (
                                        dashboardData.recent_activity.map((act, idx) => (
                                            <div className="timelineItem" key={idx}>
                                                <div className={`timelineIcon ${act.type}`}>
                                                    {act.type === "chat" && "💬"}
                                                    {act.type === "lead" && "🤝"}
                                                    {act.type === "support" && "🛠️"}
                                                    {act.type === "hiring" && "💼"}
                                                    {act.type === "meeting" && "📅"}
                                                </div>
                                                <div className="timelineBody">
                                                    <div className="timelineTitle">{act.title}</div>
                                                    <div className="timelineDesc">{act.description}</div>
                                                    <div className="timelineTime">{new Date(act.timestamp).toLocaleString()}</div>
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </div>

                            <div className="dashboardPanel">
                                <h3>User Intent Analysis</h3>
                                <div className="intentBreakdownList">
                                    {Object.keys(dashboardData.intent_breakdown).length === 0 ? (
                                        <p>No intent breakdown metrics registered.</p>
                                    ) : (
                                        Object.entries(dashboardData.intent_breakdown).map(([intent, count]) => {
                                            const total = Object.values(dashboardData.intent_breakdown).reduce((a, b) => a + b, 0);
                                            const pct = total > 0 ? (count / total) * 100 : 0;
                                            return (
                                                <div className="intentBarRow" key={intent}>
                                                    <div className="intentBarLabels">
                                                        <span style={{textTransform: "capitalize"}}>{intent.replace("_", " ")}</span>
                                                        <span>{count} ({pct.toFixed(0)}%)</span>
                                                    </div>
                                                    <div className="intentBarBg">
                                                        <div className="intentBarFill" style={{ width: `${pct}%` }}></div>
                                                    </div>
                                                </div>
                                            );
                                        })
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ==========================================
                    CHATS LOG REAL-TIME MONITOR TAB
                    ========================================== */}
                {!loading && activeTab === "chats" && (
                    <div>
                        <div className="filterRow">
                            <div className="searchBox">
                                <span className="searchBoxIcon">🔍</span>
                                <input 
                                    type="text" 
                                    placeholder="Search logs, thread ID, user inputs..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                />
                            </div>
                            <div className="filterControls">
                                <select value={extraFilter} onChange={(e) => setExtraFilter(e.target.value)}>
                                    <option value="">All Intents</option>
                                    <option value="company_info">Company Info</option>
                                    <option value="client_lead">Client Lead</option>
                                    <option value="customer_support">Customer Support</option>
                                    <option value="hiring_support">Hiring Support</option>
                                    <option value="meeting_booking">Meeting Booking</option>
                                    <option value="general_chat">General Chat</option>
                                </select>
                            </div>
                        </div>

                        {chatsList.length === 0 ? (
                            <p>No conversation threads loaded.</p>
                        ) : (
                            <div className="chatsLayout">
                                <div className="threadsPanel">
                                    <div className="threadsHeader">
                                        <h4>Conversations (Groups)</h4>
                                        <span style={{fontSize: "12px", color: "var(--success)"}}>● Live Updates</span>
                                    </div>
                                    <div className="threadsList">
                                        {chatsList.map((t) => (
                                            <div 
                                                key={t.thread_id}
                                                className={`threadCard ${selectedThreadId === t.thread_id ? "active" : ""}`}
                                                onClick={() => handleSelectThread(t.thread_id)}
                                            >
                                                <div className="threadCardHeader">
                                                    <span className="threadCardName">{t.user_name}</span>
                                                    <span className="threadCardTime">
                                                        {new Date(t.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                                    </span>
                                                </div>
                                                <div className="threadCardMessage">{t.last_message}</div>
                                                <div className="threadCardMeta">
                                                    <span className="threadCardIntent">{t.intent}</span>
                                                    <span className="threadCardCount">{t.total_messages} messages</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <div className="conversationPanel">
                                    {selectedThreadId && selectedThreadMessages.length > 0 ? (
                                        <>
                                            <div className="conversationHeader">
                                                <h3>Conversation: {chatsList.find(t=>t.thread_id===selectedThreadId)?.user_name || "Anonymous User"}</h3>
                                                <p>Thread ID: {selectedThreadId}</p>
                                            </div>
                                            <div className="conversationMessages">
                                                {(() => {
                                                    const thread = chatsList.find(t => t.thread_id === selectedThreadId);
                                                    let intent = thread?.intent || "";
                                                    
                                                    const schemas = {
                                                        client_lead: [
                                                            "name",
                                                            "email_or_phone",
                                                            "company",
                                                            "project_type",
                                                            "requirements",
                                                            "budget",
                                                            "timeline"
                                                        ],
                                                        customer_support: [
                                                            "name",
                                                            "email_or_phone",
                                                            "issue_type",
                                                            "issue_details",
                                                            "urgency"
                                                        ],
                                                        hiring_support: [
                                                            "name",
                                                            "email",
                                                            "phone",
                                                            "role",
                                                            "experience",
                                                            "skills",
                                                            "resume_or_portfolio"
                                                        ],
                                                        meeting_booking: [
                                                            "name",
                                                            "email",
                                                            "phone",
                                                            "company",
                                                            "work_details",
                                                            "meeting_mode",
                                                            "date",
                                                            "time_slot",
                                                            "status"
                                                        ]
                                                    };
                                                    
                                                    if (!schemas[intent]) {
                                                        const keys = Object.keys(selectedThreadProfile || {});
                                                        if (keys.some(k => ["work_details", "meeting_mode", "time_slot"].includes(k))) {
                                                            intent = "meeting_booking";
                                                        } else if (keys.some(k => ["project_type", "requirements", "budget", "timeline"].includes(k))) {
                                                            intent = "client_lead";
                                                        } else if (keys.some(k => ["issue_type", "issue_details", "urgency"].includes(k))) {
                                                            intent = "customer_support";
                                                        } else if (keys.some(k => ["role", "experience", "skills", "resume_or_portfolio"].includes(k))) {
                                                            intent = "hiring_support";
                                                        } else {
                                                            intent = "client_lead";
                                                        }
                                                    }
                                                    
                                                    const fields = schemas[intent] || [];
                                                    const extractedFields = fields.filter(field => {
                                                        const val = selectedThreadProfile?.[field];
                                                        return val !== undefined && val !== null && val !== "";
                                                    });
                                                    
                                                    if (extractedFields.length === 0) {
                                                        return null;
                                                    }
                                                    
                                                    return (
                                                        <div className="extractedProfilePanel">
                                                            <h5>Extracted Profile Details ({intent.replace(/_/g, ' ').toUpperCase()})</h5>
                                                            <div className="profileGrid">
                                                                {extractedFields.map(field => {
                                                                    const val = selectedThreadProfile[field];
                                                                    return (
                                                                        <div className="profileGridItem" key={field}>
                                                                            <span className="profileKey">{field.replace(/_/g, ' ')}</span>
                                                                            <span className="profileValue" style={{ color: "white" }}>
                                                                                {String(val)}
                                                                            </span>
                                                                        </div>
                                                                    );
                                                                })}
                                                            </div>
                                                        </div>
                                                    );
                                                })()}
                                                
                                                {selectedThreadMessages.map((m, idx) => (
                                                    <div key={idx} style={{width: "100%"}}>
                                                        <div className="messageRow userRow">
                                                            <div className="messageBubble userBubble">
                                                                <div>{m.user_message}</div>
                                                                <div style={{fontSize: "10px", color: "rgba(255,255,255,0.7)", marginTop: "4px", textAlign: "right"}}>
                                                                    {new Date(m.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                                                </div>
                                                            </div>
                                                        </div>
                                                        <div className="messageRow botRow" style={{marginTop: "12px"}}>
                                                            <div className="messageBubble botBubble">
                                                                <div>{m.bot_message}</div>
                                                                <div style={{fontSize: "10px", color: "var(--text-muted)", marginTop: "4px"}}>
                                                                    {new Date(m.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})} | Intent: {m.intent}
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </>
                                    ) : (
                                        <div className="emptyConversation">
                                            Select a conversation thread from the left log pane to monitor exchange.
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* ==========================================
                    LEADS TAB
                    ========================================== */}
                {!loading && activeTab === "leads" && (
                    <div>
                        <div className="filterRow">
                            <div className="searchBox">
                                <span className="searchBoxIcon">🔍</span>
                                <input 
                                    type="text" 
                                    placeholder="Search name, company, timeline..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                />
                            </div>
                            <div className="filterControls">
                                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                                    <option value="">All Statuses</option>
                                    <option value="New">New</option>
                                    <option value="Contacted">Contacted</option>
                                    <option value="Qualified">Qualified</option>
                                    <option value="Lost">Lost</option>
                                </select>
                            </div>
                        </div>

                        {leads.length === 0 ? (
                            <p>No client leads saved.</p>
                        ) : (
                            <div className="tableContainer">
                                <table className="customTable">
                                    <thead>
                                        <tr>
                                            <th>Client Name</th>
                                            <th>Contact Details</th>
                                            <th>Company Name</th>
                                            <th>Project Type</th>
                                            <th>Requirements details</th>
                                            <th>Budget / Timeline</th>
                                            <th>Status</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {leads.map((l) => {
                                            const name = l.name || l.profile?.name || "N/A";
                                            const email_or_phone = l.email_or_phone || l.profile?.email_or_phone || "N/A";
                                            const company = l.company || l.profile?.company || "N/A";
                                            const project_type = l.project_type || l.profile?.project_type || "N/A";
                                            const requirements = l.requirements || l.profile?.requirements || "N/A";
                                            const budget = l.budget || l.profile?.budget || "N/A";
                                            const timeline = l.timeline || l.profile?.timeline || "N/A";
                                            const status = l.status || "New";
                                            const id = l.id || l._id;
                                            return (
                                                <tr key={id}>
                                                    <td><strong>{name}</strong></td>
                                                    <td>{email_or_phone}</td>
                                                    <td>{company}</td>
                                                    <td>{project_type}</td>
                                                    <td style={{maxWidth: "200px", wordBreak: "break-word"}}>{requirements}</td>
                                                    <td>
                                                        <div>Budget: {budget}</div>
                                                        <div style={{fontSize: "12px", color: "var(--text-muted)"}}>Timeline: {timeline}</div>
                                                    </td>
                                                    <td>
                                                        <select
                                                            className="tableSelect"
                                                            value={status}
                                                            onChange={(e) => handleLeadStatus(id, e.target.value)}
                                                        >
                                                            <option value="New">New</option>
                                                            <option value="Contacted">Contacted</option>
                                                            <option value="Qualified">Qualified</option>
                                                            <option value="Lost">Lost</option>
                                                        </select>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {/* ==========================================
                    SUPPORT TICKETS TAB
                    ========================================== */}
                {!loading && activeTab === "support" && (
                    <div>
                        <div className="filterRow">
                            <div className="searchBox">
                                <span className="searchBoxIcon">🔍</span>
                                <input 
                                    type="text" 
                                    placeholder="Search tickets, name, issues..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                />
                            </div>
                            <div className="filterControls">
                                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                                    <option value="">All Statuses</option>
                                    <option value="Open">Open</option>
                                    <option value="In Progress">In Progress</option>
                                    <option value="Resolved">Resolved</option>
                                </select>
                                <select value={extraFilter} onChange={(e) => setExtraFilter(e.target.value)}>
                                    <option value="">All Priorities</option>
                                    <option value="Low">Low</option>
                                    <option value="Medium">Medium</option>
                                    <option value="High">High</option>
                                </select>
                            </div>
                        </div>

                        {tickets.length === 0 ? (
                            <p>No support tickets logged.</p>
                        ) : (
                            <div className="tableContainer">
                                <table className="customTable">
                                    <thead>
                                        <tr>
                                            <th>Client Name</th>
                                            <th>Contact Details</th>
                                            <th>Issue Type</th>
                                            <th>Description Details</th>
                                            <th>Priority</th>
                                            <th>Status</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {tickets.map((t) => {
                                            const name = t.name || t.profile?.name || "N/A";
                                            const email_or_phone = t.email_or_phone || t.profile?.email_or_phone || "N/A";
                                            const issue_type = t.issue_type || t.profile?.issue_type || "N/A";
                                            const issue_details = t.issue_details || t.profile?.issue_details || "N/A";
                                            const priority = t.urgency || t.priority || "Medium";
                                            const status = t.status || "Open";
                                            const id = t.id || t._id;
                                            return (
                                                <tr key={id}>
                                                    <td><strong>{name}</strong></td>
                                                    <td>{email_or_phone}</td>
                                                    <td><span className="threadCardIntent">{issue_type}</span></td>
                                                    <td style={{maxWidth: "250px", wordBreak: "break-word"}}>{issue_details}</td>
                                                    <td>
                                                        <select
                                                            className="tableSelect"
                                                            value={priority}
                                                            onChange={(e) => handleSupportUpdate(id, "priority", e.target.value)}
                                                        >
                                                            <option value="Low">Low</option>
                                                            <option value="Medium">Medium</option>
                                                            <option value="High">High</option>
                                                        </select>
                                                    </td>
                                                    <td>
                                                        <select
                                                            className="tableSelect"
                                                            value={status}
                                                            onChange={(e) => handleSupportUpdate(id, "status", e.target.value)}
                                                        >
                                                            <option value="Open">Open</option>
                                                            <option value="In Progress">In Progress</option>
                                                            <option value="Resolved">Resolved</option>
                                                        </select>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {/* ==========================================
                    HIRING CANDIDATES TAB
                    ========================================== */}
                {!loading && activeTab === "hiring" && (
                    <div>
                        <div className="filterRow">
                            <div className="searchBox">
                                <span className="searchBoxIcon">🔍</span>
                                <input 
                                    type="text" 
                                    placeholder="Search applicants, skill tags..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                />
                            </div>
                            <div className="filterControls">
                                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                                    <option value="">All Statuses</option>
                                    <option value="Applied">Applied</option>
                                    <option value="Reviewed">Reviewed</option>
                                    <option value="Interviewed">Interviewed</option>
                                    <option value="Hired">Hired</option>
                                    <option value="Rejected">Rejected</option>
                                </select>
                            </div>
                        </div>

                        {candidates.length === 0 ? (
                            <p>No job applications received.</p>
                        ) : (
                            <div className="tableContainer">
                                <table className="customTable">
                                    <thead>
                                        <tr>
                                            <th>Applicant Name</th>
                                            <th>Email / Phone</th>
                                            <th>Role Applied</th>
                                            <th>Experience</th>
                                            <th>Skills Snapshot</th>
                                            <th>Resume</th>
                                            <th>Status</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {candidates.map((c) => {
                                            const name = c.name || c.profile?.name || "N/A";
                                            const email = c.email || c.profile?.email || "N/A";
                                            const phone = c.phone || c.profile?.phone || "N/A";
                                            const role = c.role || c.profile?.role || "N/A";
                                            const experience = c.experience || c.profile?.experience || "N/A";
                                            const skills = c.skills || c.profile?.skills || "N/A";
                                            const resume_or_portfolio = c.resume_or_portfolio || c.profile?.resume_or_portfolio || "";
                                            const status = c.status || "Applied";
                                            const id = c.id || c._id;
                                            return (
                                                <tr key={id}>
                                                    <td><strong>{name}</strong></td>
                                                    <td>
                                                        <div>{email}</div>
                                                        <div style={{fontSize: "12px", color:"var(--text-muted)"}}>{phone}</div>
                                                    </td>
                                                    <td>{role}</td>
                                                    <td>{experience}</td>
                                                    <td style={{maxWidth: "200px"}}>{skills}</td>
                                                    <td>
                                                        {resume_or_portfolio ? (
                                                            <a href={resume_or_portfolio} target="_blank" rel="noreferrer" style={{color: "var(--accent)", fontWeight: "600"}}>
                                                                Open Link
                                                            </a>
                                                        ) : "Not Provided"}
                                                    </td>
                                                    <td>
                                                        <select
                                                            className="tableSelect"
                                                            value={status}
                                                            onChange={(e) => handleHiringStatus(id, e.target.value)}
                                                        >
                                                            <option value="Applied">Applied</option>
                                                            <option value="Reviewed">Reviewed</option>
                                                            <option value="Interviewed">Interviewed</option>
                                                            <option value="Hired">Hired</option>
                                                            <option value="Rejected">Rejected</option>
                                                        </select>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {/* ==========================================
                    KNOWLEDGE SOURCES MANAGEMENT PAGE
                    ========================================== */}
                {!loading && activeTab === "knowledge" && (
                    <div>
                        {/* 30-Second checking banner info */}
                        <div className="extractedProfilePanel" style={{display: "flex", justifyContent:"space-between", alignItems:"center", marginBottom: "24px"}}>
                            <div>
                                📊 <strong>Retriever Sync Status:</strong> Active Sources: <strong>{syncStatus.active_sources}</strong> / Chunks: <strong>{syncStatus.total_chunks}</strong>
                            </div>
                            <span style={{fontSize: "12px", color: "var(--text-muted)"}}>
                                Auto checking sync every 30s | Last sync: {syncStatus.last_updated}
                            </span>
                        </div>

                        <div className="knowledgeTabs">
                            <button className={`knowledgeTabBtn ${sourceType === "manual" ? "active" : ""}`} onClick={() => setSourceType("manual")}>✍️ Manual Knowledge</button>
                            <button className={`knowledgeTabBtn ${sourceType === "document" ? "active" : ""}`} onClick={() => setSourceType("document")}>📂 Document Upload</button>
                            <button className={`knowledgeTabBtn ${sourceType === "database" ? "active" : ""}`} onClick={() => setSourceType("database")}>💾 Database Connection</button>
                            <button className={`knowledgeTabBtn ${sourceType === "website" ? "active" : ""}`} onClick={() => setSourceType("website")}>🌐 Website crawl</button>
                        </div>

                        {/* FORM: Manual Entry */}
                        {sourceType === "manual" && (
                            <form className="settingsForm" onSubmit={handleCreateManual} style={{marginBottom: "36px"}}>
                                <h4>Add Manual Knowledge</h4>
                                <div className="formGroup">
                                    <label>Source Title</label>
                                    <input 
                                        type="text" 
                                        value={manualForm.title} 
                                        onChange={(e) => setManualForm({ ...manualForm, title: e.target.value })} 
                                        placeholder="e.g. Services: Web App Pricing" 
                                        required 
                                    />
                                </div>
                                <div className="formGroup">
                                    <label>Category</label>
                                    <select value={manualForm.category} onChange={(e) => setManualForm({ ...manualForm, category: e.target.value })}>
                                        <option value="Company Information">Company Information</option>
                                        <option value="Services">Services</option>
                                        <option value="Pricing">Pricing</option>
                                        <option value="Policies">Policies</option>
                                        <option value="FAQs">FAQs</option>
                                        <option value="Support Guides">Support Guides</option>
                                        <option value="Hiring Information">Hiring Information</option>
                                    </select>
                                </div>
                                <div className="formGroup">
                                    <label>Content Description</label>
                                    <textarea 
                                        rows="5" 
                                        value={manualForm.content} 
                                        onChange={(e) => setManualForm({ ...manualForm, content: e.target.value })} 
                                        placeholder="Detailed content details to index for retriever search..." 
                                        required 
                                    />
                                </div>
                                {renderMetadataFields(manualForm, setManualForm)}
                                <button className="primaryBtn" type="submit">Index Manual Source</button>
                            </form>
                        )}

                        {/* FORM: Document Upload */}
                        {sourceType === "document" && (
                            <form className="settingsForm" onSubmit={handleUploadDoc} style={{marginBottom: "36px"}}>
                                <h4>Add Document Source (PDF, DOCX, TXT, CSV, JSON, MD, XLSX)</h4>
                                <div className="formGroup">
                                    <label>Choose File</label>
                                    <input 
                                        type="file" 
                                        accept=".txt,.pdf,.docx,.doc,.json,.csv,.xlsx,.xls,.md"
                                        onChange={(e) => setDocFile(e.target.files[0])}
                                        required 
                                    />
                                </div>
                                <div className="formGroup">
                                    <label>Category</label>
                                    <select value={docCategory} onChange={(e) => setDocCategory(e.target.value)}>
                                        <option value="Company Information">Company Information</option>
                                        <option value="Services">Services</option>
                                        <option value="Pricing">Pricing</option>
                                        <option value="Policies">Policies</option>
                                        <option value="FAQs">FAQs</option>
                                        <option value="Support Guides">Support Guides</option>
                                        <option value="Hiring Information">Hiring Information</option>
                                    </select>
                                </div>
                                {renderMetadataFields(docMetadata, setDocMetadata)}
                                <button className="primaryBtn" type="submit">Upload & Chunk File</button>
                            </form>
                        )}

                        {/* FORM: Database Connection */}
                        {sourceType === "database" && (
                            <form className="settingsForm" onSubmit={handleConnectDb} style={{marginBottom: "36px"}}>
                                <h4>Connect Corporate Database Source</h4>
                                <div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px"}}>
                                    <div className="formGroup">
                                        <label>Connection Name</label>
                                        <input 
                                            type="text" 
                                            value={dbForm.connection_name} 
                                            onChange={(e) => setDbForm({ ...dbForm, connection_name: e.target.value })} 
                                            placeholder="e.g. Products MongoDB" 
                                            required 
                                        />
                                    </div>
                                    <div className="formGroup">
                                        <label>Database Type</label>
                                        <select value={dbForm.db_type} onChange={(e) => setDbForm({ ...dbForm, db_type: e.target.value })}>
                                            <option value="mongodb">MongoDB</option>
                                            <option value="mysql">MySQL</option>
                                            <option value="postgresql">PostgreSQL</option>
                                            <option value="sqlserver">SQL Server</option>
                                        </select>
                                    </div>
                                </div>
                                <div className="formGroup">
                                    <label>Connection String</label>
                                    <input 
                                        type="password" 
                                        value={dbForm.connection_string} 
                                        onChange={(e) => setDbForm({ ...dbForm, connection_string: e.target.value })} 
                                        placeholder="mongodb://username:password@host:port" 
                                        required 
                                    />
                                </div>
                                <div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px"}}>
                                    <div className="formGroup">
                                        <label>Database Name</label>
                                        <input 
                                            type="text" 
                                            value={dbForm.db_name} 
                                            onChange={(e) => setDbForm({ ...dbForm, db_name: e.target.value })} 
                                            placeholder="company_inventory" 
                                            required 
                                        />
                                    </div>
                                    <div className="formGroup">
                                        <label>Target Table / Collection</label>
                                        <input 
                                            type="text" 
                                            value={dbForm.target_collection} 
                                            onChange={(e) => setDbForm({ ...dbForm, target_collection: e.target.value })} 
                                            placeholder="products" 
                                            required 
                                        />
                                    </div>
                                </div>
                                <div className="formGroup">
                                    <label>Category</label>
                                    <select value={dbForm.category} onChange={(e) => setDbForm({ ...dbForm, category: e.target.value })}>
                                        <option value="Company Information">Company Information</option>
                                        <option value="Services">Services</option>
                                        <option value="Pricing">Pricing</option>
                                        <option value="Policies">Policies</option>
                                        <option value="FAQs">FAQs</option>
                                        <option value="Support Guides">Support Guides</option>
                                        <option value="Hiring Information">Hiring Information</option>
                                    </select>
                                </div>
                                {renderMetadataFields(dbForm, setDbForm)}
                                <button className="primaryBtn" type="submit">Establish & Chunk Connection</button>
                            </form>
                        )}

                        {/* FORM: Website Crawling */}
                        {sourceType === "website" && (
                            <form className="settingsForm" onSubmit={handleConnectWeb} style={{marginBottom: "36px"}}>
                                <h4>Connect Website Crawler</h4>
                                <div className="formGroup">
                                    <label>Page URL</label>
                                    <input 
                                        type="url" 
                                        value={webForm.url} 
                                        onChange={(e) => setWebForm({ ...webForm, url: e.target.value })} 
                                        placeholder="https://codeqlik.com/about" 
                                        required 
                                    />
                                </div>
                                <div className="formGroup">
                                    <label>Category</label>
                                    <select value={webForm.category} onChange={(e) => setWebForm({ ...webForm, category: e.target.value })}>
                                        <option value="Company Information">Company Information</option>
                                        <option value="Services">Services</option>
                                        <option value="Pricing">Pricing</option>
                                        <option value="Policies">Policies</option>
                                        <option value="FAQs">FAQs</option>
                                        <option value="Support Guides">Support Guides</option>
                                        <option value="Hiring Information">Hiring Information</option>
                                    </select>
                                </div>
                                {renderMetadataFields(webForm, setWebForm)}
                                <button className="primaryBtn" type="submit">Crawl & Index URL</button>
                            </form>
                        )}

                        <hr style={{borderColor: "rgba(255,255,255,0.05)", margin: "40px 0"}} />

                        {/* FILTER BY TYPE */}
                        <div className="filterRow">
                            <h4>Active Chatbot Knowledge Sources</h4>
                            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="tableSelect">
                                <option value="">All Source Types</option>
                                <option value="manual">Manual Entry</option>
                                <option value="document">Document Files</option>
                                <option value="database">Database Connections</option>
                                <option value="website">Websites</option>
                            </select>
                        </div>

                        {/* SOURCE CARDS LIST */}
                        {knowledgeSources.length === 0 ? (
                            <p>No knowledge sources active in system catalog.</p>
                        ) : (
                            <div className="sourceGrid">
                                {knowledgeSources.map((source) => (
                                    <div className="sourceCard" key={source._id}>
                                        <div>
                                            <div className="sourceCardHeader">
                                                <span className={`sourceCardBadge ${source.type}`}>{source.type}</span>
                                                {/* Enable / Disable Slider Switch */}
                                                <label className="switch">
                                                    <input 
                                                        type="checkbox" 
                                                        checked={source.enabled} 
                                                        onChange={() => handleToggleSource(source._id, source.enabled)}
                                                    />
                                                    <span className="slider"></span>
                                                </label>
                                            </div>
                                            <h3 className="sourceCardTitle">{source.title}</h3>
                                            <p className="sourceCardDesc">{source.content}</p>
                                        </div>
                                        <div>
                                            <div className="sourceCardMeta">
                                                <span>Category: <strong>{source.category}</strong></span>
                                                <span>Index: <strong>{source.num_chunks || 0} chunks</strong></span>
                                            </div>
                                            <div className="sourceCardFooter">
                                                <span style={{fontSize:"11px", color:"var(--text-muted)"}}>
                                                    Last Indexed: {new Date(source.updated_at || source.created_at).toLocaleString()}
                                                </span>
                                                <div className="sourceActions">
                                                    <button className="secondaryBtn" style={{padding:"4px 10px", fontSize:"12px"}} onClick={() => handleReindexSource(source._id)}>
                                                        Re-index
                                                    </button>
                                                    <button className="secondaryBtn" style={{padding:"4px 10px", fontSize:"12px"}} onClick={() => openEditModal(source)}>
                                                        Edit
                                                    </button>
                                                    <button 
                                                        className="secondaryBtn" 
                                                        style={{padding:"4px 10px", fontSize:"12px", color:"var(--danger)", borderColor:"rgba(239,68,68,0.2)"}} 
                                                        onClick={() => handleDeleteSource(source._id)}
                                                    >
                                                        Delete
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* ==========================================
                    SETTINGS TAB
                    ========================================== */}
                {!loading && activeTab === "settings" && (
                    settingsLoading ? (
                        <p style={{ padding: "20px", color: "var(--text-muted)" }}>Loading configurations...</p>
                    ) : (
                        <div className="settingsTabContainer">
                            <div className="settingsLeftColumn">
                                <form className="settingsForm" onSubmit={saveSettings} style={{ maxWidth: "100%", width: "100%" }}>
                                    <div className="settingsSection">
                                        <h4>Corporate Branding</h4>
                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                                            <div className="formGroup">
                                                <label>Company Name</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.companyName || settings.company_name || ""}
                                                    onChange={(e) => setSettings({ ...settings, companyName: e.target.value, company_name: e.target.value })}
                                                    required
                                                />
                                            </div>
                                            <div className="formGroup">
                                                <label>Branding / Description Summary</label>
                                                <textarea 
                                                    rows="2"
                                                    value={settings.companyDescription || settings.company_description || ""}
                                                    onChange={(e) => setSettings({ ...settings, companyDescription: e.target.value, company_description: e.target.value })}
                                                    required
                                                />
                                            </div>
                                        </div>
                                        
                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "12px" }}>
                                            <div className="formGroup">
                                                <label>General Email</label>
                                                <input 
                                                    type="email" 
                                                    value={settings.generalEmail || settings.contact_email || ""}
                                                    onChange={(e) => setSettings({ ...settings, generalEmail: e.target.value, contact_email: e.target.value })}
                                                    required
                                                />
                                            </div>
                                            <div className="formGroup">
                                                <label>General Phone</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.generalPhone || settings.contact_phone || ""}
                                                    onChange={(e) => setSettings({ ...settings, generalPhone: e.target.value, contact_phone: e.target.value })}
                                                    required
                                                />
                                            </div>
                                        </div>

                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "12px" }}>
                                            <div className="formGroup">
                                                <label>Support Email</label>
                                                <input 
                                                    type="email" 
                                                    value={settings.supportEmail || settings.support_email || ""}
                                                    onChange={(e) => setSettings({ ...settings, supportEmail: e.target.value, support_email: e.target.value })}
                                                    required
                                                />
                                            </div>
                                            <div className="formGroup">
                                                <label>Support Phone</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.supportPhone || settings.support_phone || ""}
                                                    onChange={(e) => setSettings({ ...settings, supportPhone: e.target.value, support_phone: e.target.value })}
                                                    required
                                                />
                                            </div>
                                        </div>
                                    </div>

                                    <div className="settingsSection">
                                        <h4>Chatbot & Widget Customization</h4>
                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
                                            <div className="formGroup">
                                                <label>Title</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.title || ""}
                                                    onChange={(e) => setSettings({ ...settings, title: e.target.value })}
                                                    required
                                                />
                                            </div>
                                            <div className="formGroup">
                                                <label>Subtitle</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.subtitle || ""}
                                                    onChange={(e) => setSettings({ ...settings, subtitle: e.target.value })}
                                                    required
                                                />
                                            </div>
                                        </div>

                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "12px" }}>
                                            <div className="formGroup">
                                                <label>Welcome Message</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.welcomeMessage || settings.chatbot_greeting || ""}
                                                    onChange={(e) => setSettings({ ...settings, welcomeMessage: e.target.value, chatbot_greeting: e.target.value })}
                                                    required
                                                />
                                            </div>
                                            <div className="formGroup">
                                                <label>Input Placeholder</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.placeholder || ""}
                                                    onChange={(e) => setSettings({ ...settings, placeholder: e.target.value })}
                                                    required
                                                />
                                            </div>
                                        </div>

                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "16px", marginTop: "12px" }}>
                                            <div className="formGroup">
                                                <label>Theme</label>
                                                <select 
                                                    value={settings.theme || "light"} 
                                                    onChange={(e) => setSettings({ ...settings, theme: e.target.value })}
                                                >
                                                    <option value="light">Light</option>
                                                    <option value="dark">Dark</option>
                                                </select>
                                            </div>
                                            <div className="formGroup">
                                                <label>Position</label>
                                                <select 
                                                    value={settings.position || "bottom-right"} 
                                                    onChange={(e) => setSettings({ ...settings, position: e.target.value })}
                                                >
                                                    <option value="bottom-right">Bottom Right</option>
                                                    <option value="bottom-left">Bottom Left</option>
                                                </select>
                                            </div>
                                            <div className="formGroup">
                                                <label>Storage Mechanism</label>
                                                <select 
                                                    value={settings.storage || "local"} 
                                                    onChange={(e) => setSettings({ ...settings, storage: e.target.value })}
                                                >
                                                    <option value="local">Local Storage</option>
                                                    <option value="session">Session Storage</option>
                                                </select>
                                            </div>
                                        </div>

                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "12px" }}>
                                            <div className="formGroup">
                                                <label>Widget Width</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.width ?? "480px"}
                                                    onChange={(e) => setSettings({ ...settings, width: e.target.value })}
                                                    required
                                                />
                                            </div>
                                            <div className="formGroup">
                                                <label>Widget Height</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.height ?? "680px"}
                                                    onChange={(e) => setSettings({ ...settings, height: e.target.value })}
                                                    required
                                                />
                                            </div>
                                        </div>

                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "12px" }}>
                                            <div className="formGroup">
                                                <label>Logo URL</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.logoUrl || ""}
                                                    onChange={(e) => setSettings({ ...settings, logoUrl: e.target.value })}
                                                    placeholder="https://example.com/logo.png"
                                                />
                                            </div>
                                            <div className="formGroup">
                                                <label>Bot Avatar Initials/Text</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.botAvatar ?? "CQ"}
                                                    onChange={(e) => setSettings({ ...settings, botAvatar: e.target.value })}
                                                    required
                                                />
                                            </div>
                                        </div>

                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "12px" }}>
                                            <div className="formGroup">
                                                <label>Launcher Icon</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.launcherIcon ?? "💬"}
                                                    onChange={(e) => setSettings({ ...settings, launcherIcon: e.target.value })}
                                                    required
                                                />
                                            </div>
                                            <div className="formGroup">
                                                <label>Launcher Text</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.launcherText || ""}
                                                    onChange={(e) => setSettings({ ...settings, launcherText: e.target.value })}
                                                    placeholder="Optional button text"
                                                />
                                            </div>
                                        </div>

                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "12px" }}>
                                            <div className="formGroup">
                                                <label>Primary Color</label>
                                                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                                                    <input 
                                                        type="color" 
                                                        value={settings.primaryColor || "#ff7e21"}
                                                        onChange={(e) => setSettings({ ...settings, primaryColor: e.target.value })}
                                                        style={{ width: "45px", height: "35px", padding: "2px", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "4px", cursor: "pointer", background: "none" }}
                                                    />
                                                    <input 
                                                        type="text" 
                                                        value={settings.primaryColor || ""}
                                                        onChange={(e) => setSettings({ ...settings, primaryColor: e.target.value })}
                                                        placeholder="#ff7e21"
                                                        required
                                                        style={{ flex: 1 }}
                                                    />
                                                </div>
                                            </div>
                                            <div className="formGroup">
                                                <label>Show New Chat Button</label>
                                                <div style={{ display: "flex", alignItems: "center", height: "38px" }}>
                                                    <label className="switch">
                                                        <input 
                                                            type="checkbox" 
                                                            checked={!!settings.showNewChat} 
                                                            onChange={(e) => setSettings({ ...settings, showNewChat: e.target.checked })}
                                                        />
                                                        <span className="slider"></span>
                                                    </label>
                                                    <span style={{ marginLeft: "10px", fontSize: "14px" }}>
                                                        {settings.showNewChat ? "Enabled" : "Disabled"}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>

                                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "12px" }}>
                                            <div className="formGroup">
                                                <label>Footer Text</label>
                                                <input 
                                                    type="text" 
                                                    value={settings.footerText || ""}
                                                    onChange={(e) => setSettings({ ...settings, footerText: e.target.value })}
                                                />
                                            </div>
                                            <div className="formGroup">
                                                <label>Suggestions (comma-separated)</label>
                                                <input 
                                                    type="text" 
                                                    value={Array.isArray(settings.suggestions) ? settings.suggestions.join(", ") : ""}
                                                    onChange={(e) => setSettings({ 
                                                        ...settings, 
                                                        suggestions: e.target.value.split(",").map(s => s.trim()).filter(s => s !== "")
                                                    })}
                                                    placeholder="e.g. Build a Website, Pricing, Hire Developers"
                                                />
                                            </div>
                                        </div>
                                    </div>

                                    <div className="settingsSection">
                                        <h4>Fallback & Bound Redirection</h4>
                                        <div className="formGroup">
                                            <label>Default Fallback / Bound Restriction Redirect Message</label>
                                            <textarea 
                                                rows="3"
                                                value={settings.fallbackMessage || settings.fallback_message || ""}
                                                onChange={(e) => setSettings({ ...settings, fallbackMessage: e.target.value, fallback_message: e.target.value })}
                                                required
                                            />
                                        </div>
                                    </div>

                                    <button className="primaryBtn" type="submit">Save Configurations</button>
                                </form>
                            </div>

                            <div className="settingsRightColumn">
                                {/* Live Preview Card */}
                                <div className="previewPanel">
                                    <h3>Widget Preview Look</h3>
                                    <p className="previewSubtitle">Interactive Mockup aligned to current customizing parameters</p>
                                    
                                    <div className={`previewWidgetMock ${settings.theme === "dark" ? "theme-dark" : "theme-light"}`} style={{ height: "450px" }}>
                                        <div className="mockHeader" style={{ backgroundColor: settings.theme === "dark" ? "rgba(20, 20, 26, 0.95)" : (settings.primaryColor || "#ff7e21") }}>
                                            <div className="mockLogo">{settings.logoUrl ? <img src={settings.logoUrl} alt="Logo" /> : (settings.botAvatar || "CQ")}</div>
                                            <div className="mockHeaderText">
                                                <div className="mockTitle">{settings.title || "CodeQlik Assistant"}</div>
                                                <div className="mockSubtitle">{settings.subtitle || "Usually replies instantly"}</div>
                                            </div>
                                            {settings.showNewChat && <button className="mockNewBtn" type="button">New</button>}
                                        </div>
                                        
                                        <div className="mockMsgs">
                                            <div className="mockMsgRow mockBotRow">
                                                <div className="mockMsgAvatar">{settings.botAvatar || "CQ"}</div>
                                                <div className="mockMsg mockBot">{settings.welcomeMessage || settings.chatbot_greeting || "Hi! How can we help you today?"}</div>
                                            </div>
                                        </div>

                                        {settings.suggestions && settings.suggestions.length > 0 && (
                                            <div className="mockSuggestions">
                                                {settings.suggestions.slice(0, 3).map((suggestion, idx) => (
                                                    <span className="mockSuggestionBtn" key={idx}>{suggestion}</span>
                                                ))}
                                            </div>
                                        )}

                                        <div className="mockForm">
                                            <input className="mockInput" type="text" placeholder={settings.placeholder || "Type your message..."} readOnly />
                                            <button className="mockSendBtn" type="button" style={{ backgroundColor: settings.primaryColor || "#ff7e21" }}>Send</button>
                                        </div>

                                        {settings.footerText && (
                                            <div className="mockFooter">{settings.footerText}</div>
                                        )}
                                    </div>
                                </div>

                                {/* Installation Guide */}
                                <div className="installGuidePanel">
                                    <h3>Installation Guide</h3>
                                    <p className="installSubtitle">Add this chat widget to your corporate websites and applications</p>
                                    
                                    <div className="guideTabs">
                                        <button className="guideTabBtn active" type="button">HTML Script</button>
                                    </div>

                                    <div className="guideContent">
                                        <p>Paste the following script inside the <code>&lt;body&gt;</code> element of your HTML pages. The widget automatically binds settings configured above.</p>
                                        <pre className="codeBlock">
{`<!-- CodeQlik Chat Widget -->
<script src="${PUBLIC_ROOT}/dist/widget.js"></script>
<script>
  CodeQlikChat.init({
    apiUrl: "${PUBLIC_ROOT}/api/chat",
    settingsUrl: "${PUBLIC_ROOT}/api/public/settings"
  });
</script>`}
                                        </pre>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )
                )}

                {/* ==========================================
                    AI/LLM USAGE ANALYTICS TAB
                    ========================================== */}
                {!loading && activeTab === "llm-usage" && (
                    <div className="llmUsageTabContainer" style={{ display: "flex", flexDirection: "column", gap: "24px", color: "#ffffff", padding: "10px" }}>
                        
                        {/* Top Cards Grid */}
                        <div className="statsGrid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px" }}>
                            <div className="statCard" style={{ background: "rgba(30, 41, 59, 0.4)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "16px" }}>
                                <span className="statCardTitle" style={{ fontSize: "14px", color: "#94a3b8" }}>Total Requests</span>
                                <span className="statCardValue" style={{ display: "block", fontSize: "28px", fontWeight: "700", margin: "8px 0" }}>{llmSummary.total_requests || 0}</span>
                                <span className="statCardFooter" style={{ fontSize: "12px", color: "#64748b" }}>LLM calls logged</span>
                            </div>
                            <div className="statCard" style={{ background: "rgba(30, 41, 59, 0.4)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "16px" }}>
                                <span className="statCardTitle" style={{ fontSize: "14px", color: "#94a3b8" }}>Input Tokens</span>
                                <span className="statCardValue" style={{ display: "block", fontSize: "28px", fontWeight: "700", margin: "8px 0" }}>{llmSummary.total_input_tokens?.toLocaleString() || 0}</span>
                                <span className="statCardFooter" style={{ fontSize: "12px", color: "#64748b" }}>Prompt/context tokens</span>
                            </div>
                            <div className="statCard" style={{ background: "rgba(30, 41, 59, 0.4)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "16px" }}>
                                <span className="statCardTitle" style={{ fontSize: "14px", color: "#94a3b8" }}>Output Tokens</span>
                                <span className="statCardValue" style={{ display: "block", fontSize: "28px", fontWeight: "700", margin: "8px 0" }}>{llmSummary.total_output_tokens?.toLocaleString() || 0}</span>
                                <span className="statCardFooter" style={{ fontSize: "12px", color: "#64748b" }}>Generated tokens</span>
                            </div>
                            <div className="statCard" style={{ background: "rgba(30, 41, 59, 0.4)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "16px" }}>
                                <span className="statCardTitle" style={{ fontSize: "14px", color: "#94a3b8" }}>Total Tokens</span>
                                <span className="statCardValue" style={{ display: "block", fontSize: "28px", fontWeight: "700", margin: "8px 0" }}>{llmSummary.total_tokens?.toLocaleString() || 0}</span>
                                <span className="statCardFooter" style={{ fontSize: "12px", color: "#64748b" }}>Avg: {llmSummary.avg_tokens_per_request || 0}/req</span>
                            </div>
                            <div className="statCard" style={{ background: "rgba(30, 41, 59, 0.4)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "16px" }}>
                                <span className="statCardTitle" style={{ fontSize: "14px", color: "#94a3b8" }}>Estimated Cost</span>
                                <span className="statCardValue" style={{ display: "block", fontSize: "28px", fontWeight: "700", margin: "8px 0", color: "#10b981" }}>${llmSummary.total_cost || 0}</span>
                                <span className="statCardFooter" style={{ fontSize: "12px", color: "#64748b" }}>Est. Monthly: ${llmSummary.estimated_monthly_cost || 0}</span>
                            </div>
                            <div className="statCard" style={{ background: "rgba(30, 41, 59, 0.4)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "16px" }}>
                                <span className="statCardTitle" style={{ fontSize: "14px", color: "#94a3b8" }}>Avg Latency</span>
                                <span className="statCardValue" style={{ display: "block", fontSize: "28px", fontWeight: "700", margin: "8px 0" }}>{llmSummary.avg_latency || 0}s</span>
                                <span className="statCardFooter" style={{ fontSize: "12px", color: "#64748b" }}>Per LLM request</span>
                            </div>
                        </div>

                        {/* Middle: Filters & Cost Calculator */}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
                            {/* Filters */}
                            <div style={{ background: "rgba(30, 41, 59, 0.2)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "20px" }}>
                                <h3 style={{ fontSize: "16px", fontWeight: "600", marginBottom: "16px", color: "#ff7e21" }}>Analytics Filters</h3>
                                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                                    <div style={{ display: "flex", gap: "12px" }}>
                                        <div style={{ flex: 1 }}>
                                            <label style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}>Start Date</label>
                                            <input 
                                                type="date" 
                                                value={llmStartDate}
                                                onChange={(e) => setLlmStartDate(e.target.value)}
                                                style={{ width: "100%", padding: "10px", borderRadius: "6px", background: "rgba(0, 0, 0, 0.2)", border: "1px solid rgba(255, 255, 255, 0.1)", color: "#ffffff" }}
                                            />
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <label style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}>End Date</label>
                                            <input 
                                                type="date" 
                                                value={llmEndDate}
                                                onChange={(e) => setLlmEndDate(e.target.value)}
                                                style={{ width: "100%", padding: "10px", borderRadius: "6px", background: "rgba(0, 0, 0, 0.2)", border: "1px solid rgba(255, 255, 255, 0.1)", color: "#ffffff" }}
                                            />
                                        </div>
                                    </div>
                                    <div>
                                        <label style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "6px" }}>Filter by Model</label>
                                        <select 
                                            value={llmModelFilter}
                                            onChange={(e) => setLlmModelFilter(e.target.value)}
                                            style={{ width: "100%", padding: "10px", borderRadius: "6px", background: "rgba(0, 0, 0, 0.2)", border: "1px solid rgba(255, 255, 255, 0.1)", color: "#ffffff" }}
                                        >
                                            <option value="">All Models</option>
                                            {modelUsage.map((m, idx) => (
                                                <option key={idx} value={m.model}>{m.model}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>
                            </div>

                            {/* Cost Calculator */}
                            <div style={{ background: "rgba(30, 41, 59, 0.2)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "20px" }}>
                                <h3 style={{ fontSize: "16px", fontWeight: "600", marginBottom: "16px", color: "#ff7e21" }}>Cost Calculator (Simulation)</h3>
                                <div style={{ display: "flex", flexDirection: "column", gap: "12px", maxHeight: "250px", overflowY: "auto", paddingRight: "4px" }}>
                                    
                                    {/* Table Headers */}
                                    <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "10px", fontWeight: "600", fontSize: "11px", color: "#94a3b8", borderBottom: "1px solid rgba(255,255,255,0.05)", paddingBottom: "6px" }}>
                                        <span>MODEL</span>
                                        <span>INPUT ($/1M)</span>
                                        <span>OUTPUT ($/1M)</span>
                                    </div>
                                    
                                    {modelUsage.length === 0 ? (
                                        <p style={{ fontSize: "12px", color: "#94a3b8", textAlign: "center" }}>No active models to configure.</p>
                                    ) : (
                                        modelUsage.map((m) => {
                                            const rate = modelRates[m.model] || getDefaultRates(m.model);
                                            return (
                                                <div key={m.model} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: "10px", alignItems: "center" }}>
                                                    <span style={{ fontSize: "11px", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }} title={m.model}>
                                                        {m.model.split("/").pop()}
                                                    </span>
                                                    <input 
                                                        type="number" 
                                                        step="0.01"
                                                        value={rate.input}
                                                        onChange={(e) => {
                                                            const val = parseFloat(e.target.value) || 0;
                                                            setModelRates(prev => ({
                                                                ...prev,
                                                                [m.model]: { ...rate, input: val }
                                                            }));
                                                        }}
                                                        style={{ width: "100%", padding: "6px", borderRadius: "4px", background: "rgba(0, 0, 0, 0.2)", border: "1px solid rgba(255, 255, 255, 0.1)", color: "#ffffff", fontSize: "11px" }}
                                                    />
                                                    <input 
                                                        type="number" 
                                                        step="0.01"
                                                        value={rate.output}
                                                        onChange={(e) => {
                                                            const val = parseFloat(e.target.value) || 0;
                                                            setModelRates(prev => ({
                                                                ...prev,
                                                                [m.model]: { ...rate, output: val }
                                                            }));
                                                        }}
                                                        style={{ width: "100%", padding: "6px", borderRadius: "4px", background: "rgba(0, 0, 0, 0.2)", border: "1px solid rgba(255, 255, 255, 0.1)", color: "#ffffff", fontSize: "11px" }}
                                                    />
                                                </div>
                                            );
                                        })
                                    )}
                                </div>
                                
                                <div style={{ padding: "12px", borderRadius: "6px", background: "rgba(16, 185, 129, 0.1)", border: "1px solid rgba(16, 185, 129, 0.2)", display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "16px" }}>
                                    <span style={{ fontSize: "13px", color: "#34d399", fontWeight: "600" }}>Simulated Price (Filtered):</span>
                                    <span style={{ fontSize: "16px", color: "#34d399", fontWeight: "700" }}>
                                        ${modelUsage.reduce((acc, m) => {
                                            const rate = modelRates[m.model] || getDefaultRates(m.model);
                                            return acc + (((m.input_tokens || 0) * rate.input + (m.output_tokens || 0) * rate.output) / 1000000);
                                        }, 0).toFixed(6)}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Bottom: Model-wise Usage & Daily Chart */}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
                            {/* Model Usage Table */}
                            <div style={{ background: "rgba(30, 41, 59, 0.2)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "20px" }}>
                                <h3 style={{ fontSize: "16px", fontWeight: "600", marginBottom: "16px", color: "#ff7e21" }}>Model-wise Breakdown</h3>
                                <div className="tableContainer">
                                    <table className="customTable" style={{ width: "100%" }}>
                                        <thead>
                                            <tr>
                                                <th>Model</th>
                                                <th>Requests</th>
                                                <th>Tokens</th>
                                                <th>Cost</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {modelUsage.length === 0 ? (
                                                <tr>
                                                    <td colSpan="4" style={{ textAlign: "center", color: "#94a3b8" }}>No model logs recorded.</td>
                                                </tr>
                                            ) : (
                                                modelUsage.map((m, idx) => (
                                                    <tr key={idx}>
                                                        <td><strong>{m.model}</strong></td>
                                                        <td>{m.total_requests}</td>
                                                        <td>{m.total_tokens?.toLocaleString()}</td>
                                                        <td style={{ color: "#10b981" }}>${m.total_cost}</td>
                                                    </tr>
                                                ))
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </div>

                            {/* Daily Usage Chart (CSS representation) */}
                            <div style={{ background: "rgba(30, 41, 59, 0.2)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "20px" }}>
                                <h3 style={{ fontSize: "16px", fontWeight: "600", marginBottom: "16px", color: "#ff7e21" }}>Daily Token Consumption</h3>
                                <div style={{ display: "flex", alignItems: "flex-end", height: "180px", gap: "20px", padding: "10px 0", overflowX: "auto" }}>
                                    {dailyUsage.length === 0 ? (
                                        <p style={{ color: "#94a3b8", margin: "auto" }}>No log logs available for daily stats.</p>
                                    ) : (
                                        dailyUsage.map((day, idx) => {
                                            const maxTokens = Math.max(...dailyUsage.map(d => d.total_tokens), 1);
                                            const heightPercent = Math.min((day.total_tokens / maxTokens) * 100, 100);
                                            return (
                                                <div key={idx} style={{ display: "flex", flexDirection: "column", alignItems: "center", width: "60px", height: "100%", justifyContent: "flex-end" }}>
                                                    <span style={{ fontSize: "9px", color: "#94a3b8", marginBottom: "4px" }}>
                                                        {day.total_tokens > 1000 ? `${(day.total_tokens/1000).toFixed(1)}k` : day.total_tokens}
                                                    </span>
                                                    
                                                    {/* Bar wrapper with fixed height to allow percentage sizing */}
                                                    <div style={{ height: "120px", width: "100%", display: "flex", alignItems: "flex-end", justifyContent: "center" }}>
                                                        <div style={{
                                                            width: "24px",
                                                            height: `${Math.max(heightPercent, 4)}%`,
                                                            background: "linear-gradient(180deg, #ff7e21 0%, rgba(255, 126, 33, 0.2) 100%)",
                                                            borderRadius: "4px 4px 0 0",
                                                            boxShadow: "0 0 6px rgba(255, 126, 33, 0.4)"
                                                        }}></div>
                                                    </div>
                                                    
                                                    <span style={{ fontSize: "9px", color: "#64748b", marginTop: "6px", whiteSpace: "nowrap" }}>{day.date.substring(5)}</span>
                                                </div>
                                            );
                                        })
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* Recent Thread Usage Table */}
                        <div style={{ background: "rgba(30, 41, 59, 0.2)", border: "1px solid rgba(255, 255, 255, 0.05)", borderRadius: "8px", padding: "20px" }}>
                            <h3 style={{ fontSize: "16px", fontWeight: "600", marginBottom: "16px", color: "#ff7e21" }}>Recent Thread Usage</h3>
                            <div className="tableContainer">
                                <table className="customTable" style={{ width: "100%" }}>
                                    <thead>
                                        <tr>
                                            <th>User / Thread ID</th>
                                            <th>LLM Requests</th>
                                            <th>Input Tokens</th>
                                            <th>Output Tokens</th>
                                            <th>Total Tokens</th>
                                            <th>Total Cost</th>
                                            <th>Last Active</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {recentLlmCalls.length === 0 ? (
                                            <tr>
                                                <td colSpan="7" style={{ textAlign: "center", color: "#94a3b8" }}>No recent thread logs recorded.</td>
                                            </tr>
                                        ) : (
                                            recentLlmCalls.map((c, index) => {
                                                const timeString = new Date(c.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'});
                                                const dateString = new Date(c.timestamp).toLocaleDateString([], {month: 'short', day: 'numeric'});
                                                return (
                                                    <tr key={index}>
                                                        <td>
                                                            <button 
                                                                onClick={() => {
                                                                    setSelectedThreadId(c.thread_id);
                                                                    fetchThreadMessages(c.thread_id);
                                                                    setActiveTab("chats");
                                                                }}
                                                                style={{
                                                                    background: "transparent",
                                                                    border: "none",
                                                                    color: "#ff7e21",
                                                                    cursor: "pointer",
                                                                    fontWeight: "700",
                                                                    textDecoration: "underline",
                                                                    padding: 0,
                                                                    textAlign: "left"
                                                                }}
                                                                title={`Thread ID: ${c.thread_id}`}
                                                            >
                                                                {c.display_name}
                                                            </button>
                                                        </td>
                                                        <td>{c.total_requests}</td>
                                                        <td>{c.input_tokens?.toLocaleString()}</td>
                                                        <td>{c.output_tokens?.toLocaleString()}</td>
                                                        <td><strong>{c.total_tokens?.toLocaleString()}</strong></td>
                                                        <td style={{ color: "#10b981" }}>${c.total_cost}</td>
                                                        <td><span style={{ color: "#94a3b8" }}>{dateString} {timeString}</span></td>
                                                    </tr>
                                                );
                                            })
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                    </div>
                )}

                {!loading && activeTab === "meetings" && (
                    <div>
                        {meetings.length === 0 ? (
                            <p>No booked meetings found.</p>
                        ) : (
                            <div className="tableContainer">
                                <table className="customTable">
                                    <thead>
                                        <tr>
                                            <th>Client Name</th>
                                            <th>Contact Info</th>
                                            <th>Company Name</th>
                                            <th>Meeting Mode</th>
                                            <th>Date & Time Slot</th>
                                            <th>Topic / Details</th>
                                            <th>Status</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {meetings.map((m) => {
                                            const id = m.id || m._id;
                                            const name = m.profile?.name || "N/A";
                                            const email = m.profile?.email || "N/A";
                                            const phone = m.profile?.phone || "N/A";
                                            const company = m.profile?.company || "N/A";
                                            const mode = m.profile?.meeting_mode || "N/A";
                                            const date = m.profile?.date || "N/A";
                                            const slot = m.profile?.time_slot || "N/A";
                                            const details = m.profile?.work_details || "N/A";
                                            const status = m.profile?.status || "confirmed";
                                            return (
                                                <tr key={id}>
                                                    <td>
                                                        <button 
                                                            onClick={() => {
                                                                setSelectedThreadId(m.thread_id);
                                                                fetchThreadMessages(m.thread_id);
                                                                setActiveTab("chats");
                                                            }}
                                                            style={{
                                                                background: "transparent",
                                                                border: "none",
                                                                color: "#ff7e21",
                                                                cursor: "pointer",
                                                                fontWeight: "700",
                                                                textDecoration: "underline",
                                                                padding: 0,
                                                                textAlign: "left"
                                                            }}
                                                            title={`View Chat History`}
                                                        >
                                                            {name}
                                                        </button>
                                                    </td>
                                                    <td>
                                                        <div>📧 {email}</div>
                                                        <div>📞 {phone}</div>
                                                    </td>
                                                    <td>{company}</td>
                                                    <td>
                                                        <span style={{
                                                            padding: "4px 8px",
                                                            borderRadius: "4px",
                                                            fontSize: "12px",
                                                            fontWeight: "600",
                                                            background: mode === "google_meet" ? "#e0f2fe" : "#fef3c7",
                                                            color: mode === "google_meet" ? "#0369a1" : "#b45309"
                                                        }}>
                                                            {mode === "google_meet" ? "💻 Google Meet" : "📞 Phone Call"}
                                                        </span>
                                                    </td>
                                                    <td><strong>📅 {date}</strong><br/><span style={{color: "#94a3b8"}}>⏰ {slot}</span></td>
                                                    <td style={{ maxWidth: "250px", wordBreak: "break-word" }}>{details}</td>
                                                    <td>
                                                        <select 
                                                            value={status} 
                                                            onChange={(e) => handleUpdateMeetingStatus(id, e.target.value)}
                                                            style={{
                                                                padding: "4px 8px",
                                                                borderRadius: "4px",
                                                                border: "1px solid #cbd5e1"
                                                            }}
                                                        >
                                                            <option value="confirmed">Confirmed</option>
                                                            <option value="completed">Completed</option>
                                                            <option value="cancelled">Cancelled</option>
                                                            <option value="needs_reschedule">Needs Reschedule</option>
                                                        </select>
                                                    </td>
                                                    <td>
                                                        <button 
                                                            className="secondaryBtn"
                                                            style={{ padding: "4px 8px", fontSize: "12px" }}
                                                            onClick={() => {
                                                                setSelectedThreadId(m.thread_id);
                                                                fetchThreadMessages(m.thread_id);
                                                                setActiveTab("chats");
                                                            }}
                                                        >
                                                            View Chat
                                                        </button>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}
            </main>

            {/* ==========================================
                KNOWLEDGE SOURCE EDIT MODAL OVERLAY
                ========================================== */}
            {isEditModalOpen && (
                <div className="modalOverlay">
                    <div className="modalContent">
                        <h3>Modify Knowledge Source</h3>
                        <form onSubmit={handleSaveEdit}>
                            <div className="formGroup">
                                <label>Title</label>
                                <input 
                                    type="text" 
                                    value={editForm.title}
                                    onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
                                    required
                                />
                            </div>
                            <div className="formGroup">
                                <label>Category</label>
                                <select value={editForm.category} onChange={(e) => setEditForm({ ...editForm, category: e.target.value })}>
                                    <option value="Company Information">Company Information</option>
                                    <option value="Services">Services</option>
                                    <option value="Pricing">Pricing</option>
                                    <option value="Policies">Policies</option>
                                    <option value="FAQs">FAQs</option>
                                    <option value="Support Guides">Support Guides</option>
                                    <option value="Hiring Information">Hiring Information</option>
                                </select>
                            </div>
                            {editForm.type === "website" && (
                                <div className="formGroup">
                                    <label>Website URL</label>
                                    <input
                                        type="url"
                                        value={editForm.url}
                                        onChange={(e) => setEditForm({ ...editForm, url: e.target.value })}
                                        required
                                    />
                                </div>
                            )}
                            {editForm.type === "database" && (
                                <>
                                    <div className="formGroup">
                                        <label>Connection Name</label>
                                        <input
                                            type="text"
                                            value={editForm.connection_name}
                                            onChange={(e) => setEditForm({ ...editForm, connection_name: e.target.value })}
                                            required
                                        />
                                    </div>
                                    <div className="formGroup">
                                        <label>Database Type</label>
                                        <select value={editForm.db_type} onChange={(e) => setEditForm({ ...editForm, db_type: e.target.value })}>
                                            <option value="mongodb">MongoDB</option>
                                            <option value="mysql">MySQL</option>
                                            <option value="postgres">PostgreSQL</option>
                                            <option value="mssql">MSSQL</option>
                                        </select>
                                    </div>
                                    <div className="formGroup">
                                        <label>Connection String</label>
                                        <input
                                            type="text"
                                            value={editForm.connection_string}
                                            onChange={(e) => setEditForm({ ...editForm, connection_string: e.target.value })}
                                            required
                                        />
                                    </div>
                                    <div className="formGroup">
                                        <label>Database Name</label>
                                        <input
                                            type="text"
                                            value={editForm.db_name}
                                            onChange={(e) => setEditForm({ ...editForm, db_name: e.target.value })}
                                        />
                                    </div>
                                    <div className="formGroup">
                                        <label>Target Collection/Table</label>
                                        <input
                                            type="text"
                                            value={editForm.target_collection}
                                            onChange={(e) => setEditForm({ ...editForm, target_collection: e.target.value })}
                                        />
                                    </div>
                                </>
                            )}
                            {(editForm.type === "manual" || editForm.type === "website") && (
                                <div className="formGroup">
                                    <label>Content Context</label>
                                    <textarea 
                                        rows="6"
                                        value={editForm.content}
                                        onChange={(e) => setEditForm({ ...editForm, content: e.target.value })}
                                        required
                                    />
                                </div>
                            )}
                            {editForm.type === "document" && (
                                <div className="formGroup">
                                    <label>Document Text</label>
                                    <textarea 
                                        rows="10"
                                        value={editForm.full_content}
                                        onChange={(e) => setEditForm({ ...editForm, full_content: e.target.value })}
                                        required
                                    />
                                </div>
                            )}
                            <div className="formGroup">
                                <label>Intent Scope</label>
                                <select value={editForm.intent_scope} onChange={(e) => setEditForm({ ...editForm, intent_scope: e.target.value })}>
                                    <option value="Auto">Auto</option>
                                    <option value="all">all</option>
                                    <option value="client">client</option>
                                    <option value="support">support</option>
                                    <option value="hiring">hiring</option>
                                    <option value="greet">greet</option>
                                </select>
                            </div>
                            <div className="formGroup">
                                <label>Topic</label>
                                <select value={editForm.topic} onChange={(e) => setEditForm({ ...editForm, topic: e.target.value })}>
                                    <option value="Auto">Auto</option>
                                    <option value="general">general</option>
                                    <option value="services">services</option>
                                    <option value="technologies">technologies</option>
                                    <option value="pricing">pricing</option>
                                    <option value="contact">contact</option>
                                    <option value="portfolio">portfolio</option>
                                    <option value="faq">faq</option>
                                    <option value="policies">policies</option>
                                </select>
                            </div>
                            <div className="formGroup">
                                <label>Service</label>
                                <select value={editForm.service} onChange={(e) => setEditForm({ ...editForm, service: e.target.value })}>
                                    <option value="Auto">Auto</option>
                                    <option value="client">client</option>
                                    <option value="support">support</option>
                                    <option value="hiring">hiring</option>
                                    <option value="sales">sales</option>
                                </select>
                            </div>
                            <div className="formGroup">
                                <label>Tags</label>
                                <input
                                    type="text"
                                    value={editForm.tags}
                                    onChange={(e) => setEditForm({ ...editForm, tags: e.target.value })}
                                    placeholder="tag1, tag2"
                                />
                            </div>
                            <div className="formActions">
                                <button className="secondaryBtn" type="button" onClick={() => setIsEditModalOpen(false)}>
                                    Cancel
                                </button>
                                <button className="primaryBtn" type="submit">
                                    Save Edits
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}

export default Admin;
