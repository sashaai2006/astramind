import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import { FileEntry } from '../components/FileTree';
import { LogEvent } from '../components/LogPanel';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace("http", "ws");

interface DocumentContextType {
  documentId: string | undefined;
  files: FileEntry[];
  selectedFile: string | null;
  fileContent: string;
  logs: LogEvent[];
  status: string;
  isRunning: boolean;

  setSelectedFile: (path: string | null) => void;
  fetchFiles: () => Promise<void>;
  fetchStatus: () => Promise<void>;
  fetchFileContent: (path: string) => Promise<void>;
  handleSave: (content: string) => Promise<void>;
  sendStop: () => void;
}

const DocumentContext = createContext<DocumentContextType | undefined>(undefined);

export const DocumentProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const router = useRouter();
  const { id } = router.query;
  const documentId = id as string | undefined;

  const [files, setFiles] = useState<FileEntry[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [status, setStatus] = useState<string>("");

  const wsRef = useRef<WebSocket | null>(null);
  const selectedFileRef = useRef(selectedFile);
  useEffect(() => { selectedFileRef.current = selectedFile; }, [selectedFile]);

  const fetchFiles = useCallback(async () => {
    if (!documentId) return;
    const response = await fetch(`${API_BASE}/api/documents/${documentId}/files`);
    if (response.ok) {
      setFiles(await response.json());
    }
  }, [documentId]);

  const fetchStatus = useCallback(async () => {
    if (!documentId) return;
    const response = await fetch(`${API_BASE}/api/documents/${documentId}/status`);
    if (response.ok) {
      const data = await response.json();
      setStatus(data.status || "");
    }
  }, [documentId]);

  const fetchFileContent = useCallback(async (path: string) => {
    if (!documentId) return;
    const response = await fetch(`${API_BASE}/api/documents/${documentId}/file?path=${encodeURIComponent(path)}`);
    if (response.ok) {
      const text = await response.text();
      setFileContent(text);
    }
  }, [documentId]);

  useEffect(() => {
    fetchFiles();
    fetchStatus();
  }, [fetchFiles, fetchStatus]);

  useEffect(() => {
    if (selectedFile) {
      fetchFileContent(selectedFile);
    }
  }, [selectedFile, fetchFileContent]);

  useEffect(() => {
    if (!documentId) return;
    const ws = new WebSocket(`${WS_BASE}/ws/documents/${documentId}`);
    wsRef.current = ws;
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "event") {
          setLogs((prev) => [...prev.slice(-199), data]);
          fetchStatus();
          if (data.data?.artifact_path || data.artifact_path) {
            fetchFiles();
            const ap = data.data?.artifact_path || data.artifact_path;
            if (selectedFileRef.current && ap === selectedFileRef.current) {
              fetchFileContent(selectedFileRef.current);
            }
          }
        }
      } catch {
        // ignore
      }
    };
    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [documentId, fetchFiles, fetchStatus, fetchFileContent]);

  const handleSave = async (content: string) => {
    if (!documentId || !selectedFile) return;
    await fetch(`${API_BASE}/api/documents/${documentId}/file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: selectedFile, content }),
    });
    await fetchFiles();
  };

  const sendStop = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "command", command: "stop" }));
    }
  }, []);

  const isRunning = ["creating", "planning", "writing", "reviewing", "compiling", "running"].includes(status);

  return (
    <DocumentContext.Provider value={{
      documentId,
      files,
      selectedFile,
      fileContent,
      logs,
      status,
      isRunning,
      setSelectedFile,
      fetchFiles,
      fetchStatus,
      fetchFileContent,
      handleSave,
      sendStop,
    }}>
      {children}
    </DocumentContext.Provider>
  );
};

export const useDocument = () => {
  const context = useContext(DocumentContext);
  if (context === undefined) {
    throw new Error('useDocument must be used within a DocumentProvider');
  }
  return context;
};

