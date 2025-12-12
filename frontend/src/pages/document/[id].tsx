import React from "react";
import dynamic from "next/dynamic";
import { DocumentProvider, useDocument } from "../../contexts/DocumentContext";
import FileTree from "../../components/FileTree";
import LogPanel from "../../components/LogPanel";

const Editor = dynamic(() => import("../../components/Editor"), {
  loading: () => <div style={{ height: "100%", background: "#1e1e1e", display: "flex", alignItems: "center", justifyContent: "center", color: "#666" }}>Loading Editor...</div>,
  ssr: false
});

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const statusColor = (status: string) => {
  switch (status) {
    case "done":
      return "#4ade80";
    case "failed":
      return "#ef4444";
    case "stopped":
      return "#94a3b8";
    default:
      return "#facc15";
  }
};

const languageFromPath = (path: string) => {
  if (path.endsWith(".tex")) return "latex";
  if (path.endsWith(".bib")) return "bibtex";
  if (path.endsWith(".md")) return "markdown";
  return "plaintext";
};

const DocumentContent: React.FC = () => {
  const { documentId, files, selectedFile, fileContent, logs, status, isRunning, setSelectedFile, fetchFiles, handleSave, sendStop } = useDocument();

  const downloadHref = documentId ? `${API_BASE}/api/documents/${documentId}/download` : undefined;

  const handleStop = () => {
    if (confirm("Are you sure you want to stop document generation?")) {
      sendStop();
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", color: "#e0e0e0" }}>
      <header style={{ padding: "0.75rem 1rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 600, letterSpacing: "1px", background: "linear-gradient(90deg, #fff, #aaa)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
            AstraMind / Document / {documentId}
          </h1>
          <p style={{ margin: 0, fontSize: "0.8rem", color: "#9ca3af" }}>
            Status: <span style={{ color: statusColor(status), fontWeight: "bold" }}>{(status || "—").toUpperCase()}</span>
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          {isRunning && (
            <button
              type="button"
              onClick={handleStop}
              style={{
                background: "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)",
                color: "white",
                padding: "0.5rem 0.9rem",
                borderRadius: "6px",
                fontSize: "0.85rem",
                fontWeight: "bold",
                border: "1px solid rgba(255,255,255,0.1)",
                cursor: "pointer",
              }}
            >
              ⏹ Stop
            </button>
          )}
          <a
            href={downloadHref || "#"}
            style={{
              background: downloadHref ? "linear-gradient(135deg, #10b981 0%, #059669 100%)" : "rgba(55, 65, 81, 0.5)",
              color: "white",
              padding: "0.5rem 0.9rem",
              borderRadius: "6px",
              pointerEvents: downloadHref ? "auto" : "none",
              textDecoration: "none",
              fontSize: "0.85rem",
              fontWeight: "bold",
              border: "1px solid rgba(255,255,255,0.1)",
            }}
            download
          >
            📄 PDF
          </a>
          <a href="/" style={{ fontSize: "0.9rem", color: "#60a5fa" }}>← Home</a>
        </div>
      </header>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "250px 1fr 420px", overflow: "hidden", padding: "1rem", gap: "1rem" }}>
        <FileTree
          files={files}
          selectedPath={selectedFile}
          onSelect={(path) => setSelectedFile(path)}
          version={1}
          onVersionChange={() => {}}
          onRefresh={fetchFiles}
        />

        <div style={{ height: "100%", overflow: "hidden" }}>
          <Editor
            path={selectedFile}
            content={fileContent}
            language={selectedFile ? languageFromPath(selectedFile) : "plaintext"}
            onSave={handleSave}
            onDeepReview={async () => {}}
          />
        </div>

        <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
          <h3 style={{ fontSize: "0.9rem", margin: "0 0 0.5rem 0", textTransform: "uppercase", color: "#9ca3af", letterSpacing: "1px" }}>Live Logs</h3>
          <div style={{ flex: 1, overflow: "hidden" }}>
            <LogPanel events={logs} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default function DocumentPage() {
  return (
    <DocumentProvider>
      <DocumentContent />
    </DocumentProvider>
  );
}

