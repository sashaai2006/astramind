const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export class ApiClient {
  private static async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    if (!response.ok) {
        let message = `API Error: ${response.status} ${response.statusText}`;
        try {
            const data = await response.json();
            message = data.detail || data.message || message;
        } catch {}
        throw new Error(message);
    }
    // Some endpoints might return empty body
    if (response.status === 204) return {} as T;
    return response.json();
  }

  // Projects
  static async getProjects(limit = 20) {
    return this.request<{ projects: any[] }>(`/api/projects?limit=${limit}`);
  }
  
  static async createProject(data: any) {
    return this.request<{ project_id: string }>(`/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  }

  static async getProjectStatus(id: string) {
      return this.request<{ status: string, steps: any[] }>(`/api/projects/${id}/status`);
  }

  static async getProjectFiles(id: string) {
      return this.request<any[]>(`/api/projects/${id}/files`);
  }

  static async getFileContent(projectId: string, path: string, version: number) {
      // Return text directly, not JSON
      const response = await fetch(
          `${API_BASE}/api/projects/${projectId}/file?path=${encodeURIComponent(path)}&version=${version}`
      );
      if (!response.ok) throw new Error("Failed to fetch file content");
      return response.text();
  }

  static async saveFile(projectId: string, path: string, content: string) {
      return this.request(`/api/projects/${projectId}/file`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, content }),
      });
  }
  
  static async deleteProject(id: string) {
      const response = await fetch(`${API_BASE}/api/projects/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Failed to delete project");
      return true;
  }

  // Documents
  static async getDocuments(limit = 20) {
      return this.request<{ documents: any[] }>(`/api/documents?limit=${limit}`);
  }

  static async createDocument(data: any) {
       return this.request<{ document_id: string }>(`/api/documents`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
       });
  }

  // Presets & Teams
  static async getPresets() {
      return this.request<{ presets: any[] }>(`/api/presets`);
  }

  static async getCustomAgents(limit = 100) {
      return this.request<{ agents: any[] }>(`/api/custom-agents?limit=${limit}`);
  }

  static async createCustomAgent(data: any) {
      return this.request(`/api/custom-agents`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
      });
  }
  
  static async deleteCustomAgent(id: string) {
      const response = await fetch(`${API_BASE}/api/custom-agents/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Failed to delete agent");
      return true;
  }

  static async getTeams(limit = 100) {
      return this.request<{ teams: any[] }>(`/api/teams?limit=${limit}`);
  }

  static async createTeam(data: any) {
      return this.request(`/api/teams`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
      });
  }

  static async deleteTeam(id: string) {
      const response = await fetch(`${API_BASE}/api/teams/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Failed to delete team");
      return true;
  }

  // Chat & Review
  static async chat(projectId: string, message: string, history: any[]) {
      return this.request<{ response: string }>(`/api/projects/${projectId}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, history }),
      });
  }

  static async review(projectId: string, paths: string[]) {
      return this.request<{ approved: boolean, comments: string[] }>(`/api/projects/${projectId}/review`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paths }),
      });
  }
}

