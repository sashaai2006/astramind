# AstraMind

**Virtual AI Company: Describe your idea and let the agents build the MVP.**

---

## 🎯 What is AstraMind?

AstraMind is an AI-powered project management and autonomous development platform that transforms your ideas into working prototypes. Describe your project vision, and our team of intelligent AI agents will handle everything:

- **Code Generation** - Write production-ready code
- **Architecture Design** - Plan scalable system architecture  
- **Testing & Quality** - Ensure code reliability
- **Documentation** - Generate comprehensive docs
- **Real-time Execution** - Watch agents work live

---

## ✨ Key Features

### 🤖 Intelligent AI Agents
- **CEO Agent** - Project oversight and task orchestration
- **Senior Python Developer** - Backend API development
- **Senior C++ Developer** - System-level optimization
- **DevOps Engineer** - Infrastructure and deployment
- **Technical Writer** - Documentation generation

### 🚀 Real-time Project Execution
Watch the execution graph in real-time as agents collaborate and complete tasks. Each step is tracked with detailed logs.

### 📊 Multi-LLM Support
- Groq API (fast, free tier available)
- OpenAI GPT models
- DeepSeek (cost-effective)
- Cerebras (high-performance)
- Local Ollama support

### 💾 Project Management
- Create and manage multiple projects
- Browse project gallery (20+ templates)
- Track execution progress
- Access generated code and documents

---

## 📸 Product Screenshots

### Dashboard Interface

![AstraMind Dashboard](./screenshots/dashboard-main.png)

*The main dashboard showing available projects and quick-start templates*

### Project Creation & Configuration

![Project Configuration](./screenshots/project-setup.png)

*Easy project setup with customizable agents and tech stack selection*

### Real-time Execution Graph

![Execution Graph](./screenshots/execution-graph.png)

*Watch AI agents collaborate in real-time with detailed task tracking*

### Agent Marketplace

![Agent Marketplace](./screenshots/agent-marketplace.png)

*Browse and select from 9+ pre-built agents for your project*

### Code Editor Integration

![Code Editor](./screenshots/code-editor.png)

*View and edit generated code with syntax highlighting*

### Generated Results

![Generated Results](./screenshots/results.png)

*Access all generated files, documentation, and artifacts*

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (optional)

### Local Development

1. **Clone and install dependencies:**
   ```bash
   git clone https://github.com/sashaai2006/AstraMind.git
   cd AstraMind
   make init
   ```

2. **Set up environment:**
   ```bash
   cp .env.example .env
   # Add your LLM API keys to .env
   ```

3. **Run the application:**
   ```bash
   make dev
   ```

4. **Access the app:**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

### Docker Setup

```bash
docker-compose up --build
```

---

## 📁 Project Structure

```
AstraMind/
├── backend/              # FastAPI backend
│   ├── agents/          # AI agents implementation
│   ├── api/             # REST API endpoints
│   ├── core/            # Orchestration engine
│   ├── llm/             # LLM adapters (Groq, OpenAI, etc.)
│   ├── memory/          # Database & vector storage
│   └── sandbox/         # Code execution sandbox
├── frontend/            # Next.js web application
│   └── src/
│       ├── components/  # React components
│       ├── contexts/    # React state management
│       └── pages/       # Application pages
└── docker-compose.yml   # Container orchestration
```

---

## ⚙️ Configuration

Create `.env` file with the following:

```env
# LLM Selection (choose one)
LLM_MODE=groq

# API Keys (based on LLM_MODE)
GROQ_API_KEY=your_api_key_here
OPENAI_API_KEY=your_openai_key
DEEPSEEK_API_KEY=your_deepseek_key
CEREBRAS_API_KEY=your_cerebras_key

# Optional Settings
ENABLE_WEB_SEARCH=false
ADMIN_API_KEY=your_admin_key
```

---

## 🎓 How It Works

1. **Describe Your Idea** - Write a project description with tech requirements
2. **Select Agents** - Choose which AI agents to work on your project
3. **Launch Project** - System starts autonomous development
4. **Monitor Progress** - Watch real-time execution graph and logs
5. **Get Results** - Download generated code, docs, and artifacts

---

## 🧪 Testing

```bash
make test
# or
pytest
```

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| **Port already in use** | Change ports in `run_dev.py` or kill process on port 3000/8000 |
| **Database locked** | Restart Docker containers or close other database connections |
| **ModuleNotFoundError** | Run `pip install -r requirements.txt` in activated venv |
| **Frontend can't reach API** | Check `NEXT_PUBLIC_API_BASE_URL` env variable |
| **Missing API keys** | Set LLM API keys in `.env` file |

---

## 📊 Technology Stack

### Backend
- **Framework**: FastAPI (async, high-performance)
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **LLM Integration**: LangChain, LiteLLM
- **Code Execution**: Custom sandbox with timeout protection
- **Database**: SQLite (local), PostgreSQL (production-ready)

### Frontend
- **Framework**: Next.js 14+ (React, TypeScript)
- **Styling**: Tailwind CSS
- **Real-time Updates**: Server-Sent Events (SSE)
- **State Management**: React Context API

### Infrastructure
- **Containerization**: Docker & Docker Compose
- **Deployment**: Cloud-ready configuration
- **Scaling**: Horizontal scaling support

---

## 🤝 Contributing

Contributions are welcome! Please follow the existing code style and submit pull requests with detailed descriptions.

---

## 📄 License

[Choose your license here]

---

## 🌐 Links

- **GitHub**: [sashaai2006/AstraMind](https://github.com/sashaai2006/AstraMind)
- **Issues**: [Report bugs and request features](https://github.com/sashaai2006/AstraMind/issues)
- **Discussions**: [Join the community](https://github.com/sashaai2006/AstraMind/discussions)

---

**Built with ❤️ for autonomous AI-powered development**
