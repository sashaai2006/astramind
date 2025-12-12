import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/router';
import { FileEntry } from '../components/FileTree';
import { LogEvent } from '../components/LogPanel';
import { Step } from '../components/DAGView';
import { Message } from '../components/ChatPanel';
import { soundManager } from '../utils/sound';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace("http", "ws");

interface ProjectContextType {
  projectId: string | undefined;
  files: FileEntry[];
  selectedFile: string | null;
  fileContent: string;
  version: number;
  logs: LogEvent[];
  steps: Step[];
  status: string;
  chatHistory: Message[];
  activeTab: "editor" | "dag";
  
  setSelectedFile: (path: string | null) => void;
  setVersion: (v: number) => void;
  setActiveTab: (tab: "editor" | "dag") => void;
  setChatHistory: React.Dispatch<React.SetStateAction<Message[]>>;
  
  fetchFiles: () => Promise<void>;
  handleSave: (content: string) => Promise<void>;
  handleChat: (message: string, history: Message[]) => Promise<string>;
  handleDeepReview: () => Promise<void>;
}

const ProjectContext = createContext<ProjectContextType | undefined>(undefined);

export const ProjectProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const router = useRouter();
  const { id } = router.query;
  const projectId = id as string | undefined;

  const [files, setFiles] = useState<FileEntry[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [version, setVersion] = useState<number>(1);
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [steps, setSteps] = useState<Step[]>([]);
  const [status, setStatus] = useState<string>("");
  const [chatHistory, setChatHistory] = useState<Message[]>([]);
  const [activeTab, setActiveTab] = useState<"editor" | "dag">("editor");

  const selectedFileRef = useRef(selectedFile);
  useEffect(() => { selectedFileRef.current = selectedFile; }, [selectedFile]);

  const fetchFiles = useCallback(async () => {
    if (!projectId) return;
    const response = await fetch(`${API_BASE}/api/projects/${projectId}/files`);
    if (response.ok) {
      setFiles(await response.json());
    }
  }, [projectId]);

  const statusRef = useRef<string>("");
  useEffect(() => { statusRef.current = status; }, [status]);

  const fetchStatus = useCallback(async () => {
    if (!projectId) return;
    const response = await fetch(`${API_BASE}/api/projects/${projectId}/status`);
    if (response.ok) {
      const data = await response.json();
      const newStatus = data.status;
      setSteps(data.steps);
      setStatus(newStatus);
      // Refresh files when project completes
      if (newStatus === "done" && statusRef.current !== "done") {
        setTimeout(() => fetchFiles(), 300);
      }
    }
  }, [projectId, fetchFiles]);

  const fetchFileContent = useCallback(
    async (path: string, versionOverride?: number) => {
      if (!projectId) return;
      const versionToUse = versionOverride ?? version;
      const response = await fetch(
        `${API_BASE}/api/projects/${projectId}/file?path=${encodeURIComponent(path)}&version=${versionToUse}`,
      );
      if (response.ok) {
        const text = await response.text();
        setFileContent(text);
      }
    },
    [projectId, version],
  );

  useEffect(() => {
    fetchFiles();
    fetchStatus();
  }, [fetchFiles, fetchStatus]);

  // Ensure files are loaded when status becomes "done"
  useEffect(() => {
    if (status === "done") {
      // Small delay to ensure backend has finished writing files
      const timer = setTimeout(() => {
        fetchFiles();
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [status, fetchFiles]);

  useEffect(() => {
    if (selectedFile) {
      fetchFileContent(selectedFile);
    }
  }, [selectedFile, fetchFileContent, version]);

  useEffect(() => {
    if (!projectId) return;
    const ws = new WebSocket(`${WS_BASE}/ws/projects/${projectId}`);
    
    ws.onopen = () => {
      console.log(`[WebSocket] Connected to project ${projectId}`);
    };
    
    ws.onerror = (error) => {
      console.error(`[WebSocket] Error for project ${projectId}:`, error);
    };
    
    ws.onclose = () => {
      console.log(`[WebSocket] Disconnected from project ${projectId}`);
    };
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log(`[WebSocket] Received:`, data);
        
        // Accept both "event" type (from ProjectEvent) and "info" type (from websocket.py)
        if (data.type === "event" || data.type === "info") {
          // Normalize to LogEvent format
          const logEvent: LogEvent = {
            type: data.type || "event",
            timestamp: data.timestamp || new Date().toISOString(),
            project_id: data.project_id || projectId || "",
            agent: data.agent || "system",
            level: data.level || "info",
            msg: data.msg || data.message || JSON.stringify(data),
            artifact_path: data.data?.artifact_path || data.artifact_path,
          };
          
          setLogs((prev) => [...prev.slice(-199), logEvent]);
          fetchStatus();
          
          // Refresh files when artifact is created or project completes
          if (logEvent.artifact_path) {
            fetchFiles();
            soundManager.playSuccess();
            if (selectedFileRef.current && logEvent.artifact_path === selectedFileRef.current) {
                 fetchFileContent(selectedFileRef.current);
            }
          } else if (logEvent.msg && (logEvent.msg.includes("completed successfully") || logEvent.msg.includes("Project completed"))) {
            // Refresh files when project completes
            setTimeout(() => fetchFiles(), 500);
          }
        } else {
          console.warn(`[WebSocket] Unknown event type: ${data.type}`, data);
        }
      } catch (err) {
        console.error(`[WebSocket] Failed to parse message:`, err, event.data);
      }
    };
    
    return () => {
      ws.close();
    };
  }, [projectId, fetchStatus, fetchFiles, fetchFileContent]);

  const handleSave = async (content: string) => {
    if (!projectId || !selectedFile) return;
    soundManager.playClick();
    await fetch(`${API_BASE}/api/projects/${projectId}/file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: selectedFile, content }),
    });
    await fetchFiles();
  };

  const handleChat = async (message: string, history: Message[]) => {
    if (!projectId) return "Error: No project ID";
    const response = await fetch(`${API_BASE}/api/projects/${projectId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });
    if (!response.ok) {
      throw new Error("Failed to send message");
    }
    const data = await response.json();
    fetchFiles();
    return data.response;
  };

  const handleDeepReview = async () => {
    if (!projectId || !selectedFile) return;
    
    soundManager.playClick();
    
    try {
        const response = await fetch(`${API_BASE}/api/projects/${projectId}/review`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paths: [selectedFile] }),
        });
        
        if (response.ok) {
            const result = await response.json();
            soundManager.playSuccess();
            
            if (result.approved) {
                alert(`✅ Code Approved!\n\nNo critical issues found.`);
            } else {
                alert(`⚠️ Review Comments:\n\n${result.comments.join('\n\n')}`);
            }
        }
    } catch (e) {
        console.error(e);
    }
  };

  return (
    <ProjectContext.Provider value={{
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
    }}>
      {children}
    </ProjectContext.Provider>
  );
};

export const useProject = () => {
  const context = useContext(ProjectContext);
  if (context === undefined) {
    throw new Error('useProject must be used within a ProjectProvider');
  }
  return context;
};

