import { FormEvent, useState, useEffect } from "react";
import Link from "next/link";
import { soundManager } from "../utils/sound";
import { ApiClient } from "../utils/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const templates = [
  {
    title: "FastAPI Backend",
    description: "A robust REST API using FastAPI with SQLite database, Pydantic schemas, and JWT authentication.",
    target: "api"
  },
  {
    title: "React To-Do App",
    description: "A modern To-Do application with drag-and-drop sorting, categories, and local storage persistence.",
    target: "web"
  }
];

type ProjectItem = {
  id: string;
  title: string;
  description: string;
  target: string;
  status: string;
  created_at: string | null;
};

type DocumentItem = {
  id: string;
  title: string;
  description: string;
  doc_type: string;
  status: string;
  created_at: string | null;
};

type AgentPreset = {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  popular: boolean;
  tags: string[];
  requires_document_mode?: boolean;
};

type CustomAgentItem = {
  id: string;
  name: string;
  prompt: string;
  tech_stack: string[];
  created_at: string | null;
  updated_at: string | null;
};

type TeamItem = {
  id: string;
  name: string;
  description: string;
  agent_ids: string[];
  preset_ids: string[];
  created_at: string | null;
  updated_at: string | null;
};

const statusChipStyle = (status: string) => {
  switch (status) {
    case "done":
      return { bg: "rgba(74, 222, 128, 0.2)", fg: "#4ade80", border: "#4ade8033" };
    case "failed":
      return { bg: "rgba(239, 68, 68, 0.2)", fg: "#ef4444", border: "#ef444433" };
    case "stopped":
      return { bg: "rgba(148, 163, 184, 0.2)", fg: "#94a3b8", border: "#94a3b833" };
    default:
      return { bg: "rgba(250, 204, 21, 0.2)", fg: "#facc15", border: "#facc1533" };
  }
};

const categoryColors: Record<string, { bg: string; border: string }> = {
  development: { bg: "rgba(59, 130, 246, 0.15)", border: "#3b82f655" },
  writing: { bg: "rgba(16, 185, 129, 0.15)", border: "#10b98155" },
  management: { bg: "rgba(139, 92, 246, 0.15)", border: "#8b5cf655" },
};

export default function HomePage() {
  const [entityMode, setEntityMode] = useState<"projects" | "documents">("projects");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [target, setTarget] = useState<"web" | "api" | "telegram">("web");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [agentPreset, setAgentPreset] = useState<string>("");
  const [customAgentId, setCustomAgentId] = useState<string>("");
  const [teamId, setTeamId] = useState<string>("");
  const [docType, setDocType] = useState<"latex_article" | "latex_beamer">("latex_article");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  
  // Gallery state
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [showGallery, setShowGallery] = useState(true);
  
  // Marketplace presets state
  const [presets, setPresets] = useState<AgentPreset[]>([]);
  const [showMarketplace, setShowMarketplace] = useState(false);
  const [marketplaceFilter, setMarketplaceFilter] = useState<string>("all");

  // Custom agents + teams state
  const [customAgents, setCustomAgents] = useState<CustomAgentItem[]>([]);
  const [teams, setTeams] = useState<TeamItem[]>([]);
  const [showBuilder, setShowBuilder] = useState(false);

  // Builder form state
  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentTech, setNewAgentTech] = useState("");
  const [newAgentPrompt, setNewAgentPrompt] = useState("");
  const [newTeamName, setNewTeamName] = useState("");
  const [newTeamDesc, setNewTeamDesc] = useState("");
  const [newTeamAgentIds, setNewTeamAgentIds] = useState<string[]>([]);
  const [newTeamPresetIds, setNewTeamPresetIds] = useState<string[]>([]);

  // Fetch projects and presets on mount
  useEffect(() => {
    fetchProjects();
    fetchDocuments();
    fetchPresets();
    fetchCustomAgents();
    fetchTeams();
  }, []);

  const fetchProjects = async () => {
    try {
      const data = await ApiClient.getProjects(20);
      setProjects(data.projects || []);
    } catch (e) {
      console.error("Failed to fetch projects:", e);
    }
  };

  const fetchDocuments = async () => {
    try {
      const data = await ApiClient.getDocuments(20);
      setDocuments(data.documents || []);
    } catch (e) {
      console.error("Failed to fetch documents:", e);
    }
  };

  const fetchPresets = async () => {
    try {
      const data = await ApiClient.getPresets();
      setPresets(data.presets || []);
    } catch (e) {
      console.error("Failed to fetch presets:", e);
    }
  };

  const fetchCustomAgents = async () => {
    try {
      const data = await ApiClient.getCustomAgents(100);
      setCustomAgents(data.agents || []);
    } catch (e) {
      console.error("Failed to fetch custom agents:", e);
    }
  };

  const fetchTeams = async () => {
    try {
      const data = await ApiClient.getTeams(100);
      setTeams(data.teams || []);
    } catch (e) {
      console.error("Failed to fetch teams:", e);
    }
  };

  const selectPreset = (presetId: string) => {
    soundManager.playClick();
    setAgentPreset(presetId);
    setCustomAgentId("");
    setTeamId("");
    setShowMarketplace(false);
    setShowGallery(false);
    
    // Auto-switch to Documents mode for writing presets (e.g. latex_writer)
    const preset = presets.find(p => p.id === presetId);
    if (preset?.requires_document_mode) {
      setEntityMode("documents");
    }
  };

  const filteredPresets = marketplaceFilter === "all" 
    ? presets 
    : presets.filter(p => p.category === marketplaceFilter);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setCreating(true);
    soundManager.playClick();
    
    try {
      let data;
      if (entityMode === "projects") {
        const res = await ApiClient.createProject({
          title,
          description,
          target,
          agent_preset: agentPreset || null,
          custom_agent_id: customAgentId || null,
          team_id: teamId || null,
        });
        setProjectId(res.project_id);
      } else {
        const res = await ApiClient.createDocument({
          title,
          description,
          doc_type: docType,
          agent_preset: agentPreset || null,
          custom_agent_id: customAgentId || null,
          team_id: teamId || null,
        });
        setProjectId(res.document_id);
      }
      soundManager.playSuccess();
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : "Failed to create project";
      setError(errorMessage);
    } finally {
      setCreating(false);
    }
  };

  const createCustomAgent = async () => {
    setError(null);
    try {
      const tech_stack = newAgentTech
        .split(",")
        .map(s => s.trim())
        .filter(Boolean)
        .slice(0, 50);

      await ApiClient.createCustomAgent({ name: newAgentName, prompt: newAgentPrompt, tech_stack });

      setNewAgentName("");
      setNewAgentTech("");
      setNewAgentPrompt("");
      await fetchCustomAgents();
      soundManager.playSuccess();
    } catch (e) {
      setError(`Failed to create custom agent: ${String(e)}`);
    }
  };

  const deleteCustomAgent = async (id: string) => {
    if (!confirm("Delete this custom agent?")) return;
    try {
      await ApiClient.deleteCustomAgent(id);
      if (customAgentId === id) setCustomAgentId("");
      setNewTeamAgentIds(prev => prev.filter(a => a !== id));
      await fetchCustomAgents();
      await fetchTeams();
    } catch (e) {
      alert(String(e));
    }
  };

  const createTeam = async () => {
    setError(null);
    try {
      await ApiClient.createTeam({
        name: newTeamName,
        description: newTeamDesc,
        agent_ids: newTeamAgentIds,
        preset_ids: newTeamPresetIds,
      });

      setNewTeamName("");
      setNewTeamDesc("");
      setNewTeamAgentIds([]);
      setNewTeamPresetIds([]);
      await fetchTeams();
      soundManager.playSuccess();
    } catch (e) {
      setError(`Failed to create team: ${String(e)}`);
    }
  };

  const deleteTeam = async (id: string) => {
    if (!confirm("Delete this team?")) return;
    try {
      await ApiClient.deleteTeam(id);
      if (teamId === id) setTeamId("");
      await fetchTeams();
    } catch (e) {
      alert(String(e));
    }
  };

  const fillTemplate = (t: typeof templates[0]) => {
    soundManager.playHover();
    setTitle(t.title);
    setDescription(t.description);
    setTarget(t.target as any);
  };

  const handleDelete = async (e: React.MouseEvent, projectId: string, projectTitle: string) => {
    e.preventDefault(); // Don't navigate to project
    e.stopPropagation();
    
    if (!confirm(`Are you sure you want to delete "${projectTitle}"?\n\nThis will permanently delete all files and cannot be undone.`)) {
      return;
    }
    
    soundManager.playClick();
    
    try {
      await ApiClient.deleteProject(projectId);
      soundManager.playSuccess();
      // Remove from local state
      setProjects(prev => prev.filter(p => p.id !== projectId));
    } catch (e) {
      alert(`Error: ${e}`);
    }
  };

  return (
    <div style={{ 
      minHeight: "100vh", 
      display: "flex", 
      flexDirection: "column", 
      alignItems: "center", 
      justifyContent: "center",
      padding: "2rem",
      background: "radial-gradient(circle at center, #1a1a2e 0%, #000 100%)"
    }}>
      <main className="glass-panel" style={{ padding: "2rem", width: "100%", maxWidth: 800, borderRadius: "12px" }}>
        <h1 style={{ 
          textAlign: "center", 
          marginBottom: "0.5rem", 
          background: "linear-gradient(90deg, #fff, #aaa)", 
          WebkitBackgroundClip: "text", 
          WebkitTextFillColor: "transparent",
          fontSize: "2.5rem"
        }}>
          AstraMind
        </h1>
        <p style={{ textAlign: "center", color: "#9ca3af", marginBottom: "1rem" }}>
          Virtual AI Company: Describe your idea and let the agents build the MVP.
        </p>

        {/* Entity mode */}
        <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center", marginBottom: "1rem" }}>
          <button
            type="button"
            onClick={() => setEntityMode("projects")}
            style={{
              background: entityMode === "projects" ? "rgba(59, 130, 246, 0.3)" : "transparent",
              color: entityMode === "projects" ? "#60a5fa" : "#9ca3af",
              border: "1px solid rgba(255,255,255,0.2)",
              padding: "0.4rem 1.0rem",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: entityMode === "projects" ? "bold" : "normal"
            }}
          >
            Projects
          </button>
          <button
            type="button"
            onClick={() => setEntityMode("documents")}
            style={{
              background: entityMode === "documents" ? "rgba(59, 130, 246, 0.3)" : "transparent",
              color: entityMode === "documents" ? "#60a5fa" : "#9ca3af",
              border: "1px solid rgba(255,255,255,0.2)",
              padding: "0.4rem 1.0rem",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: entityMode === "documents" ? "bold" : "normal"
            }}
          >
            Documents
          </button>
        </div>

        {/* Toggle between Gallery, Marketplace and Create */}
        <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center", marginBottom: "2rem", flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => { setShowGallery(true); setShowMarketplace(false); }}
            style={{
              background: showGallery && !showMarketplace ? "rgba(59, 130, 246, 0.3)" : "transparent",
              color: showGallery && !showMarketplace ? "#60a5fa" : "#9ca3af",
              border: "1px solid rgba(255,255,255,0.2)",
              padding: "0.5rem 1.25rem",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: showGallery && !showMarketplace ? "bold" : "normal"
            }}
          >
            📚 Gallery ({entityMode === "projects" ? projects.length : documents.length})
          </button>
          <button
            type="button"
            onClick={() => { setShowMarketplace(true); setShowGallery(false); }}
            style={{
              background: showMarketplace ? "rgba(139, 92, 246, 0.3)" : "transparent",
              color: showMarketplace ? "#a78bfa" : "#9ca3af",
              border: "1px solid rgba(255,255,255,0.2)",
              padding: "0.5rem 1.25rem",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: showMarketplace ? "bold" : "normal"
            }}
          >
            🛒 Marketplace ({presets.length})
          </button>
          <button
            type="button"
            onClick={() => { setShowGallery(false); setShowMarketplace(false); }}
            style={{
              background: !showGallery && !showMarketplace ? "rgba(59, 130, 246, 0.3)" : "transparent",
              color: !showGallery && !showMarketplace ? "#60a5fa" : "#9ca3af",
              border: "1px solid rgba(255,255,255,0.2)",
              padding: "0.5rem 1.25rem",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: !showGallery && !showMarketplace ? "bold" : "normal"
            }}
          >
            ➕ Create New
          </button>
        </div>

        {showMarketplace ? (
          // MARKETPLACE VIEW
          <div>
            <h2 style={{ 
              textAlign: "center", 
              marginBottom: "1rem", 
              fontSize: "1.3rem",
              background: "linear-gradient(90deg, #a78bfa, #818cf8)", 
              WebkitBackgroundClip: "text", 
              WebkitTextFillColor: "transparent"
            }}>
              Agent Marketplace
            </h2>
            <p style={{ textAlign: "center", color: "#9ca3af", marginBottom: "1.5rem", fontSize: "0.9rem" }}>
              Choose a specialized agent to help with your project
            </p>
            
            {/* Category Filter */}
            <div style={{ display: "flex", gap: "0.5rem", justifyContent: "center", marginBottom: "1.5rem", flexWrap: "wrap" }}>
              {["all", "development", "writing", "management"].map(cat => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => setMarketplaceFilter(cat)}
                  style={{
                    background: marketplaceFilter === cat ? "rgba(139, 92, 246, 0.25)" : "transparent",
                    color: marketplaceFilter === cat ? "#a78bfa" : "#9ca3af",
                    border: "1px solid rgba(255,255,255,0.15)",
                    padding: "0.4rem 0.9rem",
                    borderRadius: "20px",
                    cursor: "pointer",
                    fontSize: "0.8rem",
                    textTransform: "capitalize"
                  }}
                >
                  {cat === "all" ? "All Agents" : cat}
                </button>
              ))}
            </div>
            
            {/* Presets Grid */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "1rem" }}>
              {filteredPresets.map((preset) => (
                <div
                  key={preset.id}
                  onClick={() => selectPreset(preset.id)}
                  className="glass-panel"
                  style={{
                    padding: "1.25rem",
                    borderRadius: "12px",
                    cursor: "pointer",
                    transition: "all 0.2s",
                    border: `1px solid ${agentPreset === preset.id ? "#a78bfa" : "rgba(255,255,255,0.1)"}`,
                    background: agentPreset === preset.id ? "rgba(139, 92, 246, 0.15)" : (categoryColors[preset.category]?.bg || "rgba(255,255,255,0.03)"),
                    position: "relative"
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = "#a78bfa";
                    e.currentTarget.style.transform = "translateY(-2px)";
                    soundManager.playHover();
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = agentPreset === preset.id ? "#a78bfa" : "rgba(255,255,255,0.1)";
                    e.currentTarget.style.transform = "translateY(0)";
                  }}
                >
                  {preset.popular && (
                    <span style={{
                      position: "absolute",
                      top: "8px",
                      right: "8px",
                      fontSize: "0.65rem",
                      padding: "2px 6px",
                      background: "rgba(250, 204, 21, 0.2)",
                      color: "#facc15",
                      borderRadius: "4px",
                      border: "1px solid #facc1533"
                    }}>
                      ⭐ POPULAR
                    </span>
                  )}
                  <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>{preset.icon}</div>
                  <h3 style={{ margin: "0 0 0.5rem 0", color: "#fff", fontSize: "1rem", fontWeight: "bold" }}>
                    {preset.name}
                  </h3>
                  <p style={{ margin: 0, color: "#9ca3af", fontSize: "0.8rem", lineHeight: 1.4 }}>
                    {preset.description}
                  </p>
                  <div style={{ marginTop: "0.75rem", display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                    {preset.tags.slice(0, 3).map(tag => (
                      <span key={tag} style={{
                        fontSize: "0.65rem",
                        padding: "2px 6px",
                        background: "rgba(255,255,255,0.1)",
                        color: "#9ca3af",
                        borderRadius: "4px"
                      }}>
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            
            {agentPreset && (
              <div style={{ textAlign: "center", marginTop: "1.5rem" }}>
                <p style={{ color: "#a78bfa", marginBottom: "0.5rem" }}>
                  Selected: <strong>{presets.find(p => p.id === agentPreset)?.name || agentPreset}</strong>
                </p>
                <button
                  type="button"
                  onClick={() => { setShowMarketplace(false); setShowGallery(false); }}
                  style={{
                    background: "linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)",
                    color: "white",
                    padding: "0.6rem 1.5rem",
                    borderRadius: "6px",
                    border: "none",
                    cursor: "pointer",
                    fontWeight: "bold"
                  }}
                >
                  Continue to Create →
                </button>
              </div>
            )}
          </div>
        ) : showGallery ? (
          // GALLERY VIEW
          <div>
            {/* Search */}
            <input
              type="text"
              placeholder="🔍 Search projects..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ 
                width: "100%", 
                marginBottom: "1.5rem",
                background: "rgba(0,0,0,0.3)",
                border: "1px solid rgba(255,255,255,0.2)",
                padding: "0.75rem",
                borderRadius: "8px",
                color: "white"
              }}
            />

            {/* Projects Grid */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "1rem", marginBottom: "1rem" }}>
              {(entityMode === "projects" ? projects : documents)
                .filter((p: any) => !searchQuery || p.title.toLowerCase().includes(searchQuery.toLowerCase()) || p.description.toLowerCase().includes(searchQuery.toLowerCase()))
                .map((item: any) => (
                <div key={item.id} style={{ position: "relative" }}>
                  <Link href={entityMode === "projects" ? `/project/${item.id}` : `/document/${item.id}`} style={{ textDecoration: "none" }}>
                    <div
                      className="glass-panel"
                      style={{
                        padding: "1.25rem",
                        borderRadius: "10px",
                        cursor: "pointer",
                        height: "100%",
                        display: "flex",
                        flexDirection: "column",
                        transition: "all 0.2s",
                        border: "1px solid rgba(255,255,255,0.1)"
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = "rgba(59, 130, 246, 0.5)";
                        e.currentTarget.style.transform = "translateY(-2px)";
                        soundManager.playHover();
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)";
                        e.currentTarget.style.transform = "translateY(0)";
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: "0.75rem" }}>
                        <h3 style={{ margin: 0, color: "#fff", fontSize: "1.1rem", fontWeight: "bold" }}>{item.title}</h3>
                        <span style={{ 
                          fontSize: "0.7rem", 
                          padding: "2px 8px", 
                          borderRadius: "4px",
                          background: statusChipStyle(item.status).bg,
                          color: statusChipStyle(item.status).fg,
                          border: `1px solid ${statusChipStyle(item.status).border}`
                        }}>
                          {item.status.toUpperCase()}
                        </span>
                      </div>
                      <p style={{ margin: 0, color: "#9ca3af", fontSize: "0.85rem", lineHeight: 1.4, flex: 1 }}>
                        {item.description.length > 100 ? item.description.slice(0, 100) + "..." : item.description}
                      </p>
                      <div style={{ marginTop: "0.75rem", fontSize: "0.7rem", color: "#6b7280", display: "flex", gap: "0.5rem" }}>
                        {entityMode === "projects" ? <span>🎯 {item.target}</span> : <span>📄 {item.doc_type}</span>}
                        {item.created_at && <span>📅 {new Date(item.created_at).toLocaleDateString()}</span>}
                      </div>
                    </div>
                  </Link>
                </div>
              ))}
            </div>

            {(entityMode === "projects" ? projects.length : documents.length) === 0 && (
              <div style={{ textAlign: "center", color: "#9ca3af", padding: "3rem", fontSize: "0.9rem" }}>
                No items yet. Create your first one! ➕
              </div>
            )}
          </div>
        ) : (
          // CREATE VIEW
          <div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
          {templates.map((t, i) => (
            <button
              key={i}
              type="button"
              onClick={() => fillTemplate(t)}
              onMouseEnter={() => soundManager.playHover()}
              style={{
                background: "rgba(255,255,255,0.05)",
                border: "1px solid rgba(255,255,255,0.1)",
                padding: "1rem",
                borderRadius: "8px",
                cursor: "pointer",
                textAlign: "left",
                transition: "all 0.2s"
              }}
            >
              <div style={{ color: "#60a5fa", fontWeight: "bold", marginBottom: "0.5rem" }}>{t.title}</div>
              <div style={{ fontSize: "0.8rem", color: "#9ca3af", lineHeight: 1.4 }}>
                {t.description.length > 60 ? t.description.slice(0, 60) + "..." : t.description}
              </div>
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div style={{ display: "flex", gap: "1rem" }}>
            <input
              type="text"
              placeholder="Project Title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
              style={{ flex: 1 }}
            />
            {entityMode === "projects" ? (
              <select 
                value={target} 
                onChange={(event) => setTarget(event.target.value as any)}
                style={{ width: "140px" }}
              >
                <option value="web">Web</option>
                <option value="api">API</option>
                <option value="telegram">Telegram</option>
              </select>
            ) : (
              <select
                value={docType}
                onChange={(event) => setDocType(event.target.value as any)}
                style={{ width: "140px" }}
              >
                <option value="latex_article">LaTeX Article</option>
                <option value="latex_beamer">LaTeX Beamer</option>
              </select>
            )}
          </div>

          {/* Agent Preset Selection - Warning for document-mode presets */}
          {agentPreset && presets.find(p => p.id === agentPreset)?.requires_document_mode && entityMode === "projects" && (
            <div style={{
              background: "rgba(250, 204, 21, 0.15)",
              border: "1px solid rgba(250, 204, 21, 0.3)",
              color: "#facc15",
              padding: "0.5rem 0.75rem",
              borderRadius: "6px",
              fontSize: "0.8rem",
              textAlign: "center"
            }}>
              ⚠️ <strong>{presets.find(p => p.id === agentPreset)?.name}</strong> works best with Documents mode. 
              <button 
                type="button"
                onClick={() => setEntityMode("documents")}
                style={{ marginLeft: "0.5rem", background: "#facc15", color: "#000", border: "none", padding: "0.2rem 0.5rem", borderRadius: "4px", cursor: "pointer", fontWeight: "bold" }}
              >
                Switch to Documents
              </button>
            </div>
          )}
          {/* Team Selection - Warning if team contains document-mode presets */}
          {teamId && entityMode === "projects" && (() => {
            const selectedTeam = teams.find(t => t.id === teamId);
            const docModePresets = selectedTeam?.preset_ids?.filter(pid => presets.find(p => p.id === pid)?.requires_document_mode) || [];
            if (docModePresets.length === 0) return null;
            const presetNames = docModePresets.map(pid => presets.find(p => p.id === pid)?.name || pid).join(", ");
            return (
              <div style={{
                background: "rgba(250, 204, 21, 0.15)",
                border: "1px solid rgba(250, 204, 21, 0.3)",
                color: "#facc15",
                padding: "0.5rem 0.75rem",
                borderRadius: "6px",
                fontSize: "0.8rem",
                textAlign: "center"
              }}>
                ⚠️ Team <strong>{selectedTeam?.name}</strong> contains <strong>{presetNames}</strong> which works best with Documents mode.
                <button 
                  type="button"
                  onClick={() => setEntityMode("documents")}
                  style={{ marginLeft: "0.5rem", background: "#facc15", color: "#000", border: "none", padding: "0.2rem 0.5rem", borderRadius: "4px", cursor: "pointer", fontWeight: "bold" }}
                >
                  Switch to Documents
                </button>
              </div>
            );
          })()}
          <div style={{ 
            display: "flex", 
            gap: "0.75rem", 
            alignItems: "center",
            background: agentPreset ? "rgba(139, 92, 246, 0.1)" : "transparent",
            padding: "0.75rem",
            borderRadius: "8px",
            border: "1px solid rgba(255,255,255,0.1)"
          }}>
            {agentPreset ? (
              <>
                <span style={{ fontSize: "1.5rem" }}>{presets.find(p => p.id === agentPreset)?.icon || "🤖"}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: "bold", color: "#a78bfa" }}>
                    {presets.find(p => p.id === agentPreset)?.name || agentPreset}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>
                    {presets.find(p => p.id === agentPreset)?.description?.slice(0, 50) || "Custom preset"}...
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setAgentPreset("")}
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "#9ca3af",
                    cursor: "pointer",
                    fontSize: "1.2rem"
                  }}
                >
                  ✕
                </button>
              </>
            ) : (
              <>
                <span style={{ fontSize: "1.5rem" }}>🤖</span>
                <select
                  value={agentPreset}
                  onChange={(event) => { 
                    const presetId = event.target.value;
                    setAgentPreset(presetId); 
                    setCustomAgentId(""); 
                    setTeamId("");
                    // Auto-switch to Documents mode for writing presets
                    const preset = presets.find(p => p.id === presetId);
                    if (preset?.requires_document_mode) {
                      setEntityMode("documents");
                    }
                  }}
                  style={{ flex: 1, background: "transparent", border: "none", color: "white" }}
                >
                  <option value="">Auto (select agent or visit Marketplace)</option>
                  {presets.map((p) => (
                    <option key={p.id} value={p.id}>{p.icon} {p.name}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => setShowMarketplace(true)}
                  style={{
                    background: "rgba(139, 92, 246, 0.2)",
                    border: "1px solid #8b5cf655",
                    color: "#a78bfa",
                    padding: "0.3rem 0.6rem",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: "0.75rem"
                  }}
                >
                  🛒 Browse
                </button>
              </>
            )}
          </div>

          {/* Custom Agent / Team selection */}
          <div style={{
            display: "flex",
            gap: "0.75rem",
            alignItems: "center",
            padding: "0.75rem",
            borderRadius: "8px",
            border: "1px solid rgba(255,255,255,0.1)"
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: "0.75rem", color: "#9ca3af", marginBottom: "0.25rem" }}>Custom Agent (optional)</div>
              <select
                value={customAgentId}
                onChange={(e) => { setCustomAgentId(e.target.value); setAgentPreset(""); setTeamId(""); }}
                style={{ width: "100%", background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.15)", color: "white", padding: "0.45rem", borderRadius: "6px" }}
              >
                <option value="">— None —</option>
                {customAgents.map(a => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: "0.75rem", color: "#9ca3af", marginBottom: "0.25rem" }}>Team (optional)</div>
              <select
                value={teamId}
                onChange={(e) => { 
                  const newTeamId = e.target.value;
                  setTeamId(newTeamId); 
                  setAgentPreset(""); 
                  setCustomAgentId("");
                  // Auto-switch to Documents mode if team contains document-mode presets
                  if (newTeamId) {
                    const selectedTeam = teams.find(t => t.id === newTeamId);
                    const hasDocModePreset = selectedTeam?.preset_ids?.some(pid => presets.find(p => p.id === pid)?.requires_document_mode);
                    if (hasDocModePreset) {
                      setEntityMode("documents");
                    }
                  }
                }}
                style={{ width: "100%", background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.15)", color: "white", padding: "0.45rem", borderRadius: "6px" }}
              >
                <option value="">— None —</option>
                {teams.map(t => {
                  const hasDocMode = t.preset_ids?.some(pid => presets.find(p => p.id === pid)?.requires_document_mode);
                  return <option key={t.id} value={t.id}>{t.name}{hasDocMode ? " 📄" : ""}</option>;
                })}
              </select>
            </div>
            <button
              type="button"
              onClick={() => { setShowBuilder(v => !v); soundManager.playClick(); }}
              style={{
                background: "rgba(59, 130, 246, 0.15)",
                border: "1px solid rgba(59, 130, 246, 0.35)",
                color: "#60a5fa",
                padding: "0.5rem 0.75rem",
                borderRadius: "6px",
                cursor: "pointer",
                fontSize: "0.8rem",
                whiteSpace: "nowrap"
              }}
            >
              🧩 Builder
            </button>
          </div>

          {showBuilder && (
            <div className="glass-panel" style={{ padding: "1rem", borderRadius: "10px", border: "1px solid rgba(255,255,255,0.08)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                {/* Create Custom Agent */}
                <div>
                  <div style={{ fontWeight: "bold", color: "white", marginBottom: "0.5rem" }}>Create Custom Agent</div>
                  <input
                    type="text"
                    placeholder="Agent name"
                    value={newAgentName}
                    onChange={(e) => setNewAgentName(e.target.value)}
                    style={{ width: "100%", marginBottom: "0.5rem" }}
                  />
                  <input
                    type="text"
                    placeholder="Tech stack (comma-separated)"
                    value={newAgentTech}
                    onChange={(e) => setNewAgentTech(e.target.value)}
                    style={{ width: "100%", marginBottom: "0.5rem" }}
                  />
                  <textarea
                    placeholder="Persona / system prompt"
                    value={newAgentPrompt}
                    onChange={(e) => setNewAgentPrompt(e.target.value)}
                    rows={6}
                    style={{ width: "100%", resize: "vertical", marginBottom: "0.5rem" }}
                  />
                  <button
                    type="button"
                    onClick={createCustomAgent}
                    disabled={!newAgentName.trim() || !newAgentPrompt.trim()}
                    style={{
                      width: "100%",
                      background: "linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)",
                      color: "white",
                      padding: "0.55rem",
                      borderRadius: "6px",
                      border: "none",
                      cursor: "pointer",
                      fontWeight: "bold",
                      opacity: (!newAgentName.trim() || !newAgentPrompt.trim()) ? 0.6 : 1
                    }}
                  >
                    + Create Agent
                  </button>

                  <div style={{ marginTop: "0.75rem", color: "#9ca3af", fontSize: "0.75rem" }}>Existing agents</div>
                  <div style={{ marginTop: "0.35rem", display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                    {customAgents.map(a => (
                      <div key={a.id} style={{ display: "flex", gap: "0.5rem", alignItems: "center", justifyContent: "space-between", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "6px", padding: "0.45rem 0.6rem" }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ color: "white", fontSize: "0.85rem", fontWeight: "bold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</div>
                          <div style={{ color: "#9ca3af", fontSize: "0.7rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{(a.tech_stack || []).join(", ")}</div>
                        </div>
                        <button type="button" onClick={() => deleteCustomAgent(a.id)} style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid rgba(239, 68, 68, 0.35)", color: "#ef4444", padding: "0.25rem 0.5rem", borderRadius: "6px", cursor: "pointer", fontSize: "0.75rem" }}>
                          Delete
                        </button>
                      </div>
                    ))}
                    {customAgents.length === 0 && (
                      <div style={{ color: "#6b7280", fontSize: "0.75rem" }}>No custom agents yet.</div>
                    )}
                  </div>
                </div>

                {/* Create Team */}
                <div>
                  <div style={{ fontWeight: "bold", color: "white", marginBottom: "0.5rem" }}>Create Team</div>
                  <input
                    type="text"
                    placeholder="Team name"
                    value={newTeamName}
                    onChange={(e) => setNewTeamName(e.target.value)}
                    style={{ width: "100%", marginBottom: "0.5rem" }}
                  />
                  <input
                    type="text"
                    placeholder="Description (optional)"
                    value={newTeamDesc}
                    onChange={(e) => setNewTeamDesc(e.target.value)}
                    style={{ width: "100%", marginBottom: "0.5rem" }}
                  />
                  <div style={{ color: "#9ca3af", fontSize: "0.75rem", marginBottom: "0.35rem" }}>Members</div>
                  <div style={{ maxHeight: 220, overflow: "auto", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "6px", padding: "0.5rem", marginBottom: "0.5rem" }}>
                    <div style={{ color: "#9ca3af", fontSize: "0.75rem", marginBottom: "0.25rem" }}>🛒 Marketplace Presets ({presets.length})</div>
                    {presets.map(p => {
                      const checked = newTeamPresetIds.includes(p.id);
                      return (
                        <label key={p.id} style={{ display: "flex", gap: "0.5rem", alignItems: "center", color: "white", fontSize: "0.85rem", padding: "0.2rem 0" }}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => {
                              setNewTeamPresetIds(prev => checked ? prev.filter(x => x !== p.id) : [...prev, p.id]);
                            }}
                          />
                          <span style={{ opacity: 0.9 }}>{p.icon} {p.name}</span>
                          {p.popular && <span style={{ fontSize: "0.6rem", color: "#facc15", marginLeft: "auto" }}>⭐</span>}
                        </label>
                      );
                    })}
                    {presets.length === 0 && (
                      <div style={{ color: "#6b7280", fontSize: "0.75rem" }}>No presets found.</div>
                    )}

                    <div style={{ height: 8 }} />
                    <div style={{ color: "#9ca3af", fontSize: "0.75rem", marginBottom: "0.25rem" }}>Custom agents</div>
                    {customAgents.map(a => {
                      const checked = newTeamAgentIds.includes(a.id);
                      return (
                        <label key={a.id} style={{ display: "flex", gap: "0.5rem", alignItems: "center", color: "white", fontSize: "0.85rem", padding: "0.2rem 0" }}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => {
                              setNewTeamAgentIds(prev => checked ? prev.filter(x => x !== a.id) : [...prev, a.id]);
                            }}
                          />
                          <span>{a.name}</span>
                        </label>
                      );
                    })}
                    {customAgents.length === 0 && (
                      <div style={{ color: "#6b7280", fontSize: "0.75rem" }}>Create at least one custom agent first.</div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={createTeam}
                    disabled={!newTeamName.trim()}
                    style={{
                      width: "100%",
                      background: "linear-gradient(135deg, #10b981 0%, #059669 100%)",
                      color: "white",
                      padding: "0.55rem",
                      borderRadius: "6px",
                      border: "none",
                      cursor: "pointer",
                      fontWeight: "bold",
                      opacity: !newTeamName.trim() ? 0.6 : 1
                    }}
                  >
                    + Create Team
                  </button>

                  <div style={{ marginTop: "0.75rem", color: "#9ca3af", fontSize: "0.75rem" }}>Existing teams</div>
                  <div style={{ marginTop: "0.35rem", display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                    {teams.map(t => {
                      const presetMembers = (t.preset_ids || []).map(pid => presets.find(p => p.id === pid)).filter(Boolean);
                      const hasDocMode = presetMembers.some(p => p?.requires_document_mode);
                      return (
                        <div key={t.id} style={{ display: "flex", gap: "0.5rem", alignItems: "center", justifyContent: "space-between", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "6px", padding: "0.45rem 0.6rem" }}>
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ color: "white", fontSize: "0.85rem", fontWeight: "bold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {t.name} {hasDocMode && <span title="Contains document-mode agents">📄</span>}
                            </div>
                            <div style={{ color: "#9ca3af", fontSize: "0.7rem" }}>
                              {(t.agent_ids || []).length > 0 && `${(t.agent_ids || []).length} custom`}
                              {(t.agent_ids || []).length > 0 && (t.preset_ids || []).length > 0 && " + "}
                              {(t.preset_ids || []).length > 0 && `${(t.preset_ids || []).length} preset`}
                              {((t.agent_ids || []).length + (t.preset_ids || []).length) === 0 && "Empty team"}
                            </div>
                            {presetMembers.length > 0 && (
                              <div style={{ color: "#6b7280", fontSize: "0.65rem", marginTop: "0.15rem" }}>
                                {presetMembers.map(p => p?.icon || "🤖").join(" ")} {presetMembers.map(p => p?.name).join(", ")}
                              </div>
                            )}
                          </div>
                          <button type="button" onClick={() => deleteTeam(t.id)} style={{ background: "rgba(239, 68, 68, 0.15)", border: "1px solid rgba(239, 68, 68, 0.35)", color: "#ef4444", padding: "0.25rem 0.5rem", borderRadius: "6px", cursor: "pointer", fontSize: "0.75rem" }}>
                            Delete
                          </button>
                        </div>
                      );
                    })}
                    {teams.length === 0 && (
                      <div style={{ color: "#6b7280", fontSize: "0.75rem" }}>No teams yet.</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
          
          <textarea
            placeholder="Describe your project in detail..."
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={6}
            required
            style={{ resize: "vertical" }}
          />
          
          <button 
            type="submit" 
            disabled={creating}
            style={{ 
              padding: "1rem", 
              fontSize: "1.1rem",
              marginTop: "1rem"
            }}
          >
            {creating ? "Initializing Agents..." : "Launch Project 🚀"}
          </button>
        </form>

        {error && (
          <div style={{ 
            marginTop: "1.5rem", 
            padding: "1rem", 
            background: "rgba(239, 68, 68, 0.1)", 
            border: "1px solid rgba(239, 68, 68, 0.2)", 
            color: "#ef4444", 
            borderRadius: "6px",
            textAlign: "center"
          }}>
            {error}
          </div>
        )}

        {projectId && (
          <div style={{ 
            marginTop: "1.5rem", 
            padding: "1.5rem", 
            background: "rgba(16, 185, 129, 0.1)", 
            border: "1px solid rgba(16, 185, 129, 0.2)", 
            borderRadius: "8px",
            textAlign: "center"
          }}>
            <h3 style={{ color: "#10b981", marginTop: 0 }}>Project Created!</h3>
            <p style={{ color: "#d1d5db", marginBottom: "1.5rem" }}>Your agents are ready to start working.</p>
            <Link 
              href={entityMode === "projects" ? `/project/${projectId}` : `/document/${projectId}`}
              style={{ 
                display: "inline-block",
                background: "#10b981",
                color: "white",
                padding: "0.75rem 2rem",
                borderRadius: "4px",
                textDecoration: "none",
                fontWeight: "bold"
              }}
              onClick={() => soundManager.playClick()}
            >
              Open Dashboard
            </Link>
          </div>
        )}
          </div>
        )}
      </main>
    </div>
  );
}
