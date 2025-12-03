import { FormEvent, useState, useEffect } from "react";
import Link from "next/link";
import { soundManager } from "../utils/sound";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const templates = [
  {
    title: "3D Snake Game",
    description: "A classic Snake game built with Three.js and React. It should feature a 3D grid, a snake that grows when eating food, and score tracking.",
    target: "web"
  },
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

export default function HomePage() {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [target, setTarget] = useState<"web" | "api" | "telegram">("web");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  
  // Gallery state
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [showGallery, setShowGallery] = useState(true);

  // Fetch projects on mount
  useEffect(() => {
    fetchProjects();
  }, []);

  const fetchProjects = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/projects?limit=20`);
      if (response.ok) {
        const data = await response.json();
        setProjects(data.projects || []);
      }
    } catch (e) {
      console.error("Failed to fetch projects:", e);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setCreating(true);
    soundManager.playClick();
    
    try {
      const response = await fetch(`${API_BASE}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, target }),
      });
      if (!response.ok) {
        setError("Failed to create project");
        return;
      }
      const data = await response.json();
      setProjectId(data.project_id);
      soundManager.playSuccess();
    } catch (e) {
      setError("Failed to create project");
    } finally {
      setCreating(false);
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
      const response = await fetch(`${API_BASE}/api/projects/${projectId}`, {
        method: "DELETE",
      });
      
      if (response.ok) {
        soundManager.playSuccess();
        // Remove from local state
        setProjects(prev => prev.filter(p => p.id !== projectId));
      } else {
        alert("Failed to delete project");
      }
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

        {/* Toggle between Gallery and Create */}
        <div style={{ display: "flex", gap: "1rem", justifyContent: "center", marginBottom: "2rem" }}>
          <button
            type="button"
            onClick={() => setShowGallery(true)}
            style={{
              background: showGallery ? "rgba(59, 130, 246, 0.3)" : "transparent",
              color: showGallery ? "#60a5fa" : "#9ca3af",
              border: "1px solid rgba(255,255,255,0.2)",
              padding: "0.5rem 1.5rem",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: showGallery ? "bold" : "normal"
            }}
          >
            📚 Gallery ({projects.length})
          </button>
          <button
            type="button"
            onClick={() => setShowGallery(false)}
            style={{
              background: !showGallery ? "rgba(59, 130, 246, 0.3)" : "transparent",
              color: !showGallery ? "#60a5fa" : "#9ca3af",
              border: "1px solid rgba(255,255,255,0.2)",
              padding: "0.5rem 1.5rem",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: !showGallery ? "bold" : "normal"
            }}
          >
            ➕ Create New
          </button>
        </div>

        {showGallery ? (
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
              {projects
                .filter(p => !searchQuery || p.title.toLowerCase().includes(searchQuery.toLowerCase()) || p.description.toLowerCase().includes(searchQuery.toLowerCase()))
                .map((project) => (
                <div key={project.id} style={{ position: "relative" }}>
                  <Link href={`/project/${project.id}`} style={{ textDecoration: "none" }}>
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
                        <h3 style={{ margin: 0, color: "#fff", fontSize: "1.1rem", fontWeight: "bold" }}>{project.title}</h3>
                        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                          <span style={{ 
                            fontSize: "0.7rem", 
                            padding: "2px 8px", 
                            borderRadius: "4px",
                            background: project.status === "done" ? "rgba(74, 222, 128, 0.2)" : project.status === "failed" ? "rgba(239, 68, 68, 0.2)" : "rgba(250, 204, 21, 0.2)",
                            color: project.status === "done" ? "#4ade80" : project.status === "failed" ? "#ef4444" : "#facc15",
                            border: `1px solid ${project.status === "done" ? "#4ade80" : project.status === "failed" ? "#ef4444" : "#facc15"}33`
                          }}>
                            {project.status.toUpperCase()}
                          </span>
                          <button
                            type="button"
                            onClick={(e) => handleDelete(e, project.id, project.title)}
                            title="Delete project"
                            style={{
                              background: "rgba(239, 68, 68, 0.2)",
                              color: "#ef4444",
                              border: "1px solid rgba(239, 68, 68, 0.3)",
                              width: "24px",
                              height: "24px",
                              borderRadius: "4px",
                              cursor: "pointer",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              fontSize: "0.8rem",
                              padding: 0
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.background = "rgba(239, 68, 68, 0.4)";
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.background = "rgba(239, 68, 68, 0.2)";
                            }}
                          >
                            🗑️
                          </button>
                        </div>
                      </div>
                      <p style={{ margin: 0, color: "#9ca3af", fontSize: "0.85rem", lineHeight: 1.4, flex: 1 }}>
                        {project.description.length > 100 ? project.description.slice(0, 100) + "..." : project.description}
                      </p>
                      <div style={{ marginTop: "0.75rem", fontSize: "0.7rem", color: "#6b7280", display: "flex", gap: "0.5rem" }}>
                        <span>🎯 {project.target}</span>
                        {project.created_at && <span>📅 {new Date(project.created_at).toLocaleDateString()}</span>}
                      </div>
                    </div>
                  </Link>
                </div>
              ))}
            </div>

            {projects.length === 0 && (
              <div style={{ textAlign: "center", color: "#9ca3af", padding: "3rem", fontSize: "0.9rem" }}>
                No projects yet. Create your first one! ➕
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
            <select 
              value={target} 
              onChange={(event) => setTarget(event.target.value as any)}
              style={{ width: "120px" }}
            >
              <option value="web">Web</option>
              <option value="api">API</option>
              <option value="telegram">Telegram</option>
            </select>
          </div>
          
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
              href={`/project/${projectId}`}
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
