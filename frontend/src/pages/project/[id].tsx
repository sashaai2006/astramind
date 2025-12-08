import React from "react";
import dynamic from "next/dynamic";
import { ProjectProvider, useProject } from "../../contexts/ProjectContext";
import FileTree from "../../components/FileTree";
import ChatPanel from "../../components/ChatPanel";
import LogPanel from "../../components/LogPanel";
import { soundManager } from "../../utils/sound";

// Dynamic imports for heavy components
const Editor = dynamic(() => import("../../components/Editor"), {
  loading: () => <div style={{ height: "100%", background: "#1e1e1e", display: "flex", alignItems: "center", justifyContent: "center", color: "#666" }}>Loading Editor...</div>,
  ssr: false // Editor usually depends on browser APIs
});

const DAGView = dynamic(() => import("../../components/DAGView"), {
  loading: () => <div style={{ height: "100%", background: "#1e1e1e", display: "flex", alignItems: "center", justifyContent: "center", color: "#666" }}>Loading Graph...</div>,
  ssr: false
});

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const languageFromPath = (path: string) => {
  if (path.endsWith(".py")) return "python";
  if (path.endsWith(".ts") || path.endsWith(".tsx")) return "typescript";
  if (path.endsWith(".js") || path.endsWith(".jsx")) return "javascript";
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".md")) return "markdown";
  return "plaintext";
};

const ProjectContent: React.FC = () => {
  const {
    projectId,
    files,
    selectedFile,
    fileContent,
    version,
    logs,
    steps,
    status,
    chatHistory,
    activeTab,
    setSelectedFile,
    setVersion,
    setActiveTab,
    setChatHistory,
    fetchFiles,
    handleSave,
    handleChat,
    handleDeepReview
  } = useProject();

  const downloadHref = projectId
    ? `${API_BASE}/api/projects/${projectId}/download?version=${version}`
    : undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", color: "#e0e0e0" }}>
      <header style={{ padding: "0.75rem 1rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 600, letterSpacing: "1px", background: "linear-gradient(90deg, #fff, #aaa)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>AstraMind / {projectId}</h1>
          <p style={{ margin: 0, fontSize: "0.8rem", color: "#9ca3af" }}>Status: <span style={{ color: status === "done" ? "#4ade80" : "#facc15", fontWeight: "bold" }}>{status.toUpperCase()}</span></p>
        </div>
        <div>
           <a href="/" style={{ fontSize: "0.9rem", color: "#60a5fa", display: "flex", alignItems: "center", gap: "4px" }}>
             <span>←</span> Back to Home
           </a>
        </div>
      </header>
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "250px 1fr", overflow: "hidden", padding: "1rem", gap: "1rem" }}>
        <FileTree
          files={files}
          selectedPath={selectedFile}
          onSelect={(path) => { setSelectedFile(path); soundManager.playHover(); }}
          version={version}
          onVersionChange={setVersion}
          onRefresh={fetchFiles}
        />
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", borderBottom: "1px solid rgba(255,255,255,0.1)", paddingBottom: "0.5rem", alignItems: "center" }}>
            <button
              onClick={() => { setActiveTab("editor"); soundManager.playHover(); }}
              style={{
                flex: 1,
                background: activeTab === "editor" ? "rgba(59, 130, 246, 0.3)" : "transparent",
                color: activeTab === "editor" ? "#60a5fa" : "#9ca3af",
                border: activeTab === "editor" ? "1px solid rgba(59, 130, 246, 0.5)" : "1px solid transparent",
                padding: "0.5rem",
                borderRadius: "4px",
                cursor: "pointer"
              }}
            >
              Code Editor
            </button>
            <button
              onClick={() => { setActiveTab("dag"); soundManager.playHover(); }}
              style={{
                flex: 1,
                background: activeTab === "dag" ? "rgba(59, 130, 246, 0.3)" : "transparent",
                color: activeTab === "dag" ? "#60a5fa" : "#9ca3af",
                border: activeTab === "dag" ? "1px solid rgba(59, 130, 246, 0.5)" : "1px solid transparent",
                padding: "0.5rem",
                borderRadius: "4px",
                cursor: "pointer"
              }}
            >
              Execution Graph
            </button>
          </div>

          {activeTab === "editor" ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 500px", gap: "1rem", height: "calc(100vh - 140px)", overflow: "hidden" }}>
              {/* Left: Editor */}
              <div style={{ height: "100%", overflow: "hidden" }}>
                  <Editor
                    path={selectedFile}
                    content={fileContent}
                    language={selectedFile ? languageFromPath(selectedFile) : "plaintext"}
                    onSave={handleSave}
                    onDeepReview={handleDeepReview}
                  />
                </div>
                
                {/* Right: Chat (Center of attention) + Actions */}
                <div style={{ display: "flex", flexDirection: "column", gap: "1rem", height: "100%" }}>
                  {/* Chat takes most space */}
                  <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                     <ChatPanel 
                       onSendMessage={handleChat} 
                       selectedFile={selectedFile}
                       messages={chatHistory}
                       onMessagesChange={setChatHistory}
                     />
                  </div>
                  
                  {/* Compact actions panel */}
                  <div className="glass-panel" style={{ padding: "0.75rem", borderRadius: "8px" }}>
                    <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                      <a
                        href={downloadHref || "#"}
                        style={{ 
                          flex: 1,
                          textAlign: "center",
                          padding: "0.5rem",
                          background: downloadHref ? "linear-gradient(135deg, #10b981 0%, #059669 100%)" : "rgba(55, 65, 81, 0.5)",
                          color: "white",
                          borderRadius: "6px",
                          pointerEvents: downloadHref ? "auto" : "none", 
                          textDecoration: "none",
                          fontSize: "0.85rem",
                          fontWeight: "bold",
                          border: "1px solid rgba(255,255,255,0.1)"
                        }}
                        download
                        onClick={() => soundManager.playClick()}
                      >
                        📦 ZIP
                      </a>
                      <div style={{ 
                        flex: 1,
                        textAlign: "center",
                        padding: "0.5rem",
                        background: "rgba(168, 85, 247, 0.2)",
                        color: "#c4b5fd",
                        borderRadius: "6px",
                        fontSize: "0.85rem",
                        border: "1px solid rgba(168, 85, 247, 0.3)"
                      }}>
                        {status.toUpperCase()}
                      </div>
                    </div>
                  </div>
                  
                  {/* Compact logs */}
                  <div style={{ height: "150px", display: "flex", flexDirection: "column" }}>
                    <h3 style={{ fontSize: "0.75rem", margin: "0 0 0.5rem 0", textTransform: "uppercase", color: "#9ca3af", letterSpacing: "1px" }}>Live Logs</h3>
                    <div style={{ flex: 1, overflow: "hidden" }}>
                       <LogPanel events={logs} />
                    </div>
                  </div>
                </div>
              </div>
            ) : (
            <div style={{ height: "calc(100vh - 140px)", display: "grid", gridTemplateColumns: "1fr 320px", gap: "1rem" }}>
              <div style={{ height: "100%", overflow: "hidden" }}>
                <DAGView steps={steps} lastEvent={logs.length > 0 ? logs[logs.length - 1] : undefined} />
              </div>
              <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
                  <h3 style={{ fontSize: "0.9rem", margin: "0 0 0.5rem 0", textTransform: "uppercase", color: "#9ca3af", letterSpacing: "1px" }}>Live Logs</h3>
                  <div style={{ flex: 1, overflow: "hidden" }}>
                     <LogPanel events={logs} />
                  </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ProjectPage() {
  return (
    <ProjectProvider>
      <ProjectContent />
    </ProjectProvider>
  );
}
